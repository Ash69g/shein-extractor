from __future__ import annotations

from datetime import datetime
from pathlib import Path

from shein_extractor.application.naming import (
    DEFAULT_CUSTOMER_NAME,
    sanitize_filename_component,
    unique_output_path,
)
from shein_extractor.application.timezones import gmt_plus_3_time
from shein_extractor.domain.models import CartExtraction


class JsonExtractionRepository:
    def __init__(self, output_directory: Path = Path("outputs")) -> None:
        self.output_directory = output_directory

    def save(
        self,
        extraction: CartExtraction,
        *,
        customer_name: str | None = None,
        order_number: str | None = None,
        analyzed_at: datetime | None = None,
    ) -> Path:
        self.output_directory.mkdir(parents=True, exist_ok=True)
        analysis_time = gmt_plus_3_time(analyzed_at)
        display_name = (customer_name or "").strip() or DEFAULT_CUSTOMER_NAME
        safe_name = sanitize_filename_component(display_name)
        display_order_number = (order_number or "").strip() or None
        safe_order_number = (
            sanitize_filename_component(display_order_number)
            if display_order_number
            else None
        )
        timestamp = analysis_time.strftime("%Y%m%d-%H%M%S")
        identity = f"{safe_order_number}-{safe_name}" if safe_order_number else safe_name
        output_path = unique_output_path(self.output_directory, f"{identity}-{timestamp}")
        extraction.customer_name = display_name
        extraction.order_number = display_order_number
        extraction.analyzed_at = analysis_time
        extraction.output_file = output_path.name
        output_path.write_text(extraction.model_dump_json(indent=2), encoding="utf-8")
        return output_path

    def load(self, path: Path) -> CartExtraction:
        return CartExtraction.model_validate_json(path.read_text(encoding="utf-8"))
