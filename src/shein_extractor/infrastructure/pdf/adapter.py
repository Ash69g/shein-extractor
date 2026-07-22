from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from PySide6.QtGui import QPixmap

from shein_extractor.application.reporting import ReportExportResult
from shein_extractor.domain.models import CartExtraction
from shein_extractor.infrastructure.pdf.exporter import export_cart_pdf


class QtPdfReportExporter:
    def export(
        self,
        extraction: CartExtraction,
        output_path: Path,
        images: Mapping[str, object],
        *,
        json_name: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ReportExportResult:
        pixmaps = {
            url: image
            for url, image in images.items()
            if isinstance(image, QPixmap)
        }
        result = export_cart_pdf(
            extraction,
            output_path,
            pixmaps,
            json_name=json_name,
            progress_callback=progress_callback,
        )
        return ReportExportResult(
            path=output_path,
            page_count=result.page_count,
            unavailable_image_count=result.unavailable_image_count,
        )
