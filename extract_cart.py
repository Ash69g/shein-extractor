from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from _bootstrap import ensure_src_path

ensure_src_path()

from shein_extractor.application.naming import (  # noqa: E402,F401
    sanitize_filename_component,
    unique_output_path,
)
from shein_extractor.domain.errors import (  # noqa: E402,F401
    CartExtractionError,
    ExpiredShareLinkError,
)
from shein_extractor.domain.models import CartExtraction  # noqa: E402
from shein_extractor.infrastructure.persistence import (  # noqa: E402
    JsonExtractionRepository,
)
from shein_extractor.infrastructure.shein.payload_normalizer import (  # noqa: E402,F401
    as_optional_bool,
    as_optional_int,
    as_optional_string,
    normalize_image_url,
    normalize_item,
    normalize_payload,
    select_display_price,
)
from shein_extractor.infrastructure.shein.playwright_gateway import (  # noqa: E402,F401
    PlaywrightCartGateway,
    capture_failure_error,
)
from shein_extractor.infrastructure.shein.url_validator import (  # noqa: E402
    validate_shein_url,
)
from shein_extractor.cli.extract_cart import main as clean_main  # noqa: E402


OUTPUT_DIRECTORY = Path("outputs")


def extract_cart(url: str, *, headless: bool, timeout_seconds: float) -> CartExtraction:
    return PlaywrightCartGateway().extract(
        url,
        headless=headless,
        timeout_seconds=timeout_seconds,
    )


def write_output(
    extraction: CartExtraction,
    *,
    customer_name: str | None = None,
    order_number: str | None = None,
    analyzed_at: datetime | None = None,
) -> Path:
    return JsonExtractionRepository(OUTPUT_DIRECTORY).save(
        extraction,
        customer_name=customer_name,
        order_number=order_number,
        analyzed_at=analyzed_at,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract all products from a SHEIN cart share link."
    )
    parser.add_argument("url", type=validate_shein_url)
    parser.add_argument("--headless", action="store_true", help="Hide Chromium.")
    parser.add_argument("--timeout", type=float, default=60)
    return parser.parse_args()


def main() -> int:
    return clean_main()


if __name__ == "__main__":
    raise SystemExit(main())
