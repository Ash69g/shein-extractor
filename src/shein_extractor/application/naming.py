from __future__ import annotations

from pathlib import Path
import re


DEFAULT_CUSTOMER_NAME = "shein-cart"
INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename_component(value: str | None) -> str:
    component = (value or "").strip() or DEFAULT_CUSTOMER_NAME
    sanitized = INVALID_FILENAME_CHARACTERS.sub("-", component)
    sanitized = re.sub(r"\s+", "-", sanitized).strip(" .-")
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    return sanitized or DEFAULT_CUSTOMER_NAME


def unique_output_path(directory: Path, stem: str) -> Path:
    candidate = directory / f"{stem}.json"
    sequence = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{sequence}.json"
        sequence += 1
    return candidate


def report_path_for(json_path: Path, export_directory: Path) -> Path:
    return export_directory / f"{json_path.stem}.pdf"
