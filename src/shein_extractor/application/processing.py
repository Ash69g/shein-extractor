from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from shein_extractor.application.invoice_parser import parse_invoice_text
from shein_extractor.application.naming import report_path_for
from shein_extractor.application.ports import ProductImageFetcher
from shein_extractor.application.reporting import ExportReport
from shein_extractor.application.use_cases import AnalyzeCart, AnalyzeCartRequest
from shein_extractor.domain.errors import InvalidProcessingInputError
from shein_extractor.domain.models import CartExtraction


class ProcessingStage(StrEnum):
    VALIDATING_INPUT = "validating_input"
    EXTRACTING_CART = "extracting_cart"
    DOWNLOADING_IMAGES = "downloading_images"
    EXPORTING_PDF = "exporting_pdf"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ProcessingProgress:
    stage: ProcessingStage
    completed: int = 0
    total: int = 0


ProcessingProgressCallback = Callable[[ProcessingProgress], None]


@dataclass(frozen=True)
class ProcessCartRequest:
    raw_input: str
    customer_name: str | None = None
    order_number: str | None = None
    analyzed_at: datetime | None = None
    headless: bool = True
    timeout_seconds: float = 60


@dataclass(frozen=True)
class ProcessCartResult:
    extraction: CartExtraction
    json_path: Path
    pdf_path: Path
    page_count: int
    unavailable_image_count: int
    failed_image_urls: tuple[str, ...]


class ProcessCart:
    def __init__(
        self,
        analyzer: AnalyzeCart,
        image_fetcher: ProductImageFetcher,
        report_exporter: ExportReport,
        export_directory: Path = Path("exports"),
        *,
        link_validator: Callable[[str], str],
    ) -> None:
        self.analyzer = analyzer
        self.image_fetcher = image_fetcher
        self.report_exporter = report_exporter
        self.export_directory = export_directory
        self.link_validator = link_validator

    def execute(
        self,
        request: ProcessCartRequest,
        *,
        progress_callback: ProcessingProgressCallback | None = None,
    ) -> ProcessCartResult:
        self._emit(progress_callback, ProcessingStage.VALIDATING_INPUT)
        invoice = parse_invoice_text(request.raw_input)
        if not invoice.cart_urls:
            raise InvalidProcessingInputError(
                "لم يتم العثور على رابط سلة SHEIN صالح في النص المرسل."
            )
        if invoice.has_multiple_cart_urls:
            raise InvalidProcessingInputError(
                "يجب أن تحتوي كل عملية معالجة على رابط سلة SHEIN واحد فقط."
            )

        url = self.link_validator(invoice.cart_urls[0])
        customer_name = self._prefer(request.customer_name, invoice.customer_name)
        order_number = self._prefer(request.order_number, invoice.order_number)

        self._emit(progress_callback, ProcessingStage.EXTRACTING_CART)
        analysis = self.analyzer.execute(
            AnalyzeCartRequest(
                url=url,
                customer_name=customer_name,
                order_number=order_number,
                analyzed_at=request.analyzed_at,
                headless=request.headless,
                timeout_seconds=request.timeout_seconds,
            )
        )

        image_urls = tuple(
            dict.fromkeys(
                product.goods_img
                for product in analysis.extraction.products
                if product.goods_img
            )
        )
        self._emit(
            progress_callback,
            ProcessingStage.DOWNLOADING_IMAGES,
            total=len(image_urls),
        )
        fetched = self.image_fetcher.fetch(
            image_urls,
            progress_callback=lambda completed, total: self._emit(
                progress_callback,
                ProcessingStage.DOWNLOADING_IMAGES,
                completed,
                total,
            ),
        )

        pdf_path = report_path_for(analysis.output_path, self.export_directory)
        self._emit(progress_callback, ProcessingStage.EXPORTING_PDF)
        report = self.report_exporter.execute(
            analysis.extraction,
            pdf_path,
            fetched.images,
            json_name=analysis.output_path.name,
            progress_callback=lambda completed, total: self._emit(
                progress_callback,
                ProcessingStage.EXPORTING_PDF,
                completed,
                total,
            ),
        )
        self._emit(progress_callback, ProcessingStage.COMPLETED, 1, 1)
        return ProcessCartResult(
            extraction=analysis.extraction,
            json_path=analysis.output_path,
            pdf_path=report.path,
            page_count=report.page_count,
            unavailable_image_count=report.unavailable_image_count,
            failed_image_urls=fetched.failed_urls,
        )

    @staticmethod
    def _prefer(explicit: str | None, parsed: str | None) -> str | None:
        explicit_value = (explicit or "").strip()
        if explicit_value:
            return explicit_value
        parsed_value = (parsed or "").strip()
        return parsed_value or None

    @staticmethod
    def _emit(
        callback: ProcessingProgressCallback | None,
        stage: ProcessingStage,
        completed: int = 0,
        total: int = 0,
    ) -> None:
        if callback is not None:
            callback(ProcessingProgress(stage, completed, total))
