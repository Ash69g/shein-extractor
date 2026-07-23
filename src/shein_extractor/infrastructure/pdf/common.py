from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PdfExportResult:
    page_count: int
    unavailable_image_count: int


def truncate_product_name(value: str | None, limit: int = 100) -> str:
    name = (value or "—").strip()
    if len(name) <= limit:
        return name
    return f"{name[:limit].rstrip()}…"


def default_pdf_path(json_path: Path, export_directory: Path) -> Path:
    return export_directory / f"{json_path.stem}.pdf"
