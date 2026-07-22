from __future__ import annotations

import argparse
from pathlib import Path

from shein_extractor.application.use_cases import AnalyzeCart, AnalyzeCartRequest
from shein_extractor.domain.errors import CartExtractionError
from shein_extractor.infrastructure.persistence import JsonExtractionRepository
from shein_extractor.application.validation import validate_shein_url
from shein_extractor.infrastructure.shein import PlaywrightCartGateway


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract all products from a SHEIN cart share link."
    )
    parser.add_argument("url", type=validate_shein_url)
    parser.add_argument("--headless", action="store_true", help="Hide Chromium.")
    parser.add_argument("--timeout", type=float, default=60)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    use_case = AnalyzeCart(
        PlaywrightCartGateway(),
        JsonExtractionRepository(Path("outputs")),
    )
    print("Opening the SHEIN shared link...")
    try:
        result = use_case.execute(
            AnalyzeCartRequest(
                args.url,
                headless=args.headless,
                timeout_seconds=args.timeout,
            )
        )
    except CartExtractionError as error:
        print(f"فشل الاستخراج: {error}")
        return 1
    extraction = result.extraction
    print(f"Group ID: {extraction.group_id}")
    print(f"Available: {extraction.counts['normalProducts']}")
    print(f"Out of stock: {extraction.counts['outStock']}")
    print(f"Unavailable: {extraction.counts['unavailable']}")
    print(f"Total extracted: {len(extraction.products)}")
    print(f"Output saved to: {result.output_path.resolve()}")
    return 0
