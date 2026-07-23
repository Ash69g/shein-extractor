from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from shein_extractor.application.ports import ImageFetchResult
from shein_extractor.application.processing import (
    ProcessCart,
    ProcessCartRequest,
    ProcessingProgress,
    ProcessingStage,
)
from shein_extractor.application.reporting import (
    ExportReport,
    ReportExportResult,
)
from shein_extractor.application.use_cases import AnalyzeCart
from shein_extractor.application.validation import validate_shein_url
from shein_extractor.domain.errors import InvalidProcessingInputError
from shein_extractor.domain.models import (
    AvailabilityStatus,
    CartExtraction,
    ExtractedCartItem,
)
from shein_extractor.infrastructure.images import (
    HttpxProductImageFetcher,
    optimize_product_image,
)
from shein_extractor.infrastructure.persistence import JsonExtractionRepository


class FakeGateway:
    def __init__(self, extraction: CartExtraction) -> None:
        self.extraction = extraction
        self.calls: list[tuple[str, bool, float]] = []

    def extract(
        self,
        url: str,
        *,
        headless: bool,
        timeout_seconds: float,
    ) -> CartExtraction:
        self.calls.append((url, headless, timeout_seconds))
        self.extraction.source_url = url
        return self.extraction


class FakeImageFetcher:
    def __init__(self) -> None:
        self.urls: tuple[str, ...] = ()

    def fetch(
        self,
        urls: Iterable[str],
        *,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ImageFetchResult:
        self.urls = tuple(urls)
        total = len(self.urls)
        if progress_callback is not None:
            for completed in range(1, total + 1):
                progress_callback(completed, total)
        return ImageFetchResult(
            images={url: b"\x89PNG\r\n\x1a\nimage" for url in self.urls},
            failed_urls=(),
        )


class FakeReportExporter:
    def __init__(self) -> None:
        self.images: Mapping[str, object] = {}
        self.json_name = ""

    def export(
        self,
        extraction: CartExtraction,
        output_path: Path,
        images: Mapping[str, object],
        *,
        json_name: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ReportExportResult:
        self.images = images
        self.json_name = json_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"%PDF-1.4\n%%EOF")
        if progress_callback is not None:
            progress_callback(1, 1)
        return ReportExportResult(output_path, 1, 0)


def sample_extraction() -> CartExtraction:
    image_url = "https://img.ltwebstatic.com/product.webp"
    return CartExtraction(
        source_url="https://onelink.shein.com/43/example",
        final_url="https://m.shein.com/ar/cart/share/landing?group_id=100",
        group_id="100",
        all_product_size=2,
        counts={"normalProducts": 2, "outStock": 0, "unavailable": 0},
        products=[
            ExtractedCartItem(
                goods_id="1",
                sku_code="sr2601",
                goods_img=image_url,
                source_group="normalProducts",
                availability=AvailabilityStatus.AVAILABLE,
            ),
            ExtractedCartItem(
                goods_id="2",
                sku_code="sr2602",
                goods_img=image_url,
                source_group="normalProducts",
                availability=AvailabilityStatus.AVAILABLE,
            ),
        ],
    )


def make_processor(
    tmp_path: Path,
) -> tuple[ProcessCart, FakeGateway, FakeImageFetcher, FakeReportExporter]:
    gateway = FakeGateway(sample_extraction())
    image_fetcher = FakeImageFetcher()
    report_exporter = FakeReportExporter()
    processor = ProcessCart(
        AnalyzeCart(gateway, JsonExtractionRepository(tmp_path / "outputs")),
        image_fetcher,
        ExportReport(report_exporter),
        tmp_path / "exports",
        link_validator=validate_shein_url,
    )
    return processor, gateway, image_fetcher, report_exporter


def test_process_cart_runs_complete_invoice_workflow(tmp_path: Path) -> None:
    processor, gateway, image_fetcher, report_exporter = make_processor(tmp_path)
    progress: list[ProcessingProgress] = []
    analyzed_at = datetime(2026, 7, 23, 10, 30, tzinfo=timezone.utc)
    invoice = """
    اسم العميل:
    • حياة شطوان
    رقم الطلبية: T-501
    رابط الطلب:
    https://onelink.shein.com/43/example
    """

    result = processor.execute(
        ProcessCartRequest(
            invoice,
            analyzed_at=analyzed_at,
            timeout_seconds=45,
        ),
        progress_callback=progress.append,
    )

    assert gateway.calls == [("https://onelink.shein.com/43/example", True, 45)]
    assert result.extraction.customer_name == "حياة شطوان"
    assert result.extraction.order_number == "T-501"
    assert result.json_path.exists()
    assert result.pdf_path.exists()
    assert result.json_path.stem == result.pdf_path.stem
    assert "T-501" in result.json_path.name
    assert image_fetcher.urls == ("https://img.ltwebstatic.com/product.webp",)
    assert tuple(report_exporter.images) == image_fetcher.urls
    assert report_exporter.json_name == result.json_path.name
    assert progress[0].stage is ProcessingStage.VALIDATING_INPUT
    assert progress[-1] == ProcessingProgress(ProcessingStage.COMPLETED, 1, 1)


def test_process_cart_accepts_direct_url_and_explicit_metadata(
    tmp_path: Path,
) -> None:
    processor, _, _, _ = make_processor(tmp_path)

    result = processor.execute(
        ProcessCartRequest(
            "https://onelink.shein.com/43/example",
            customer_name="عميل يدوي",
            order_number="H-2237",
        )
    )

    assert result.extraction.customer_name == "عميل يدوي"
    assert result.extraction.order_number == "H-2237"
    assert result.json_path.name.startswith("H-2237-عميل-يدوي-")


@pytest.mark.parametrize(
    "raw_input",
    [
        "لا يوجد رابط هنا",
        ("https://onelink.shein.com/43/first https://onelink.shein.com/43/second"),
    ],
)
def test_process_cart_rejects_missing_or_multiple_links(
    tmp_path: Path,
    raw_input: str,
) -> None:
    processor, gateway, _, _ = make_processor(tmp_path)

    with pytest.raises(InvalidProcessingInputError):
        processor.execute(ProcessCartRequest(raw_input))

    assert gateway.calls == []


def test_httpx_image_fetcher_retries_and_reports_failures() -> None:
    attempts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        attempts[url] = attempts.get(url, 0) + 1
        if url.endswith("retry.webp") and attempts[url] == 1:
            return httpx.Response(503, request=request)
        if url.endswith("missing.webp"):
            return httpx.Response(404, request=request)
        return httpx.Response(
            200,
            headers={"content-type": "image/webp"},
            content=b"RIFFxxxxWEBPimage",
            request=request,
        )

    progress: list[tuple[int, int]] = []
    fetcher = HttpxProductImageFetcher(
        max_attempts=3,
        retry_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    result = fetcher.fetch(
        [
            "https://example.com/retry.webp",
            "https://example.com/retry.webp",
            "https://example.com/missing.webp",
        ],
        progress_callback=lambda completed, total: progress.append((completed, total)),
    )

    assert result.images["https://example.com/retry.webp"].startswith(b"RIFF")
    assert result.failed_urls == ("https://example.com/missing.webp",)
    assert attempts["https://example.com/retry.webp"] == 2
    assert attempts["https://example.com/missing.webp"] == 3
    assert progress == [(1, 2), (2, 2)]


def test_product_image_optimizer_reduces_dimensions_and_file_size() -> None:
    source = Image.effect_noise((1600, 1200), 100).convert("RGB")
    original = BytesIO()
    source.save(original, format="JPEG", quality=95)

    optimized = optimize_product_image(original.getvalue())

    with Image.open(BytesIO(optimized)) as result:
        assert max(result.size) <= 512
        assert result.format == "JPEG"
    assert len(optimized) < len(original.getvalue()) / 4


def test_product_image_optimizer_preserves_unrecognized_content() -> None:
    content = b"RIFFxxxxWEBPimage"

    assert optimize_product_image(content) == content
