from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from shein_extractor.domain.models import CartExtraction


@dataclass(frozen=True)
class ReportExportResult:
    path: Path
    page_count: int
    unavailable_image_count: int


class ReportExporter(Protocol):
    def export(
        self,
        extraction: CartExtraction,
        output_path: Path,
        images: Mapping[str, object],
        *,
        json_name: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ReportExportResult: ...


class ExportReport:
    def __init__(self, exporter: ReportExporter) -> None:
        self.exporter = exporter

    def execute(
        self,
        extraction: CartExtraction,
        output_path: Path,
        images: Mapping[str, object],
        *,
        json_name: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ReportExportResult:
        return self.exporter.export(
            extraction,
            output_path,
            images,
            json_name=json_name,
            progress_callback=progress_callback,
        )

