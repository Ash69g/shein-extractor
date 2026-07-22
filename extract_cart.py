from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import re
from time import monotonic
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Response, sync_playwright

from diagnose_link import validate_shein_url
from models import AvailabilityStatus, CartExtraction, ExtractedCartItem, Price


TARGET_ENDPOINT = "/bff-api/order/cart/share/landing"
OUTPUT_DIRECTORY = Path("outputs")
DEFAULT_CUSTOMER_NAME = "shein-cart"
INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class CartExtractionError(RuntimeError):
    pass


class ExpiredShareLinkError(CartExtractionError):
    pass


def as_optional_string(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return bool(value)


def normalize_image_url(value: Any) -> str | None:
    image_url = as_optional_string(value)
    if image_url and image_url.startswith("//"):
        return f"https:{image_url}"
    return image_url


def sanitize_filename_component(value: str | None) -> str:
    customer_name = (value or "").strip() or DEFAULT_CUSTOMER_NAME
    sanitized = INVALID_FILENAME_CHARACTERS.sub("-", customer_name)
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


def capture_failure_error(final_url: str) -> CartExtractionError:
    parsed = urlparse(final_url)
    if parsed.path.rstrip("/") == "/h5/sharejump/appjump":
        return ExpiredShareLinkError(
            "رابط مشاركة SHEIN منتهي الصلاحية أو لم يعد يحتوي سلة متاحة."
        )
    return CartExtractionError(
        "تعذر التقاط بيانات سلة SHEIN قبل انتهاء المهلة. "
        "تحقق من الرابط والاتصال ثم أعد المحاولة."
    )


def select_display_price(item: dict[str, Any]) -> tuple[Price | None, str | None]:
    candidates = (
        (
            "priceData.unitPrice.price",
            item.get("priceData", {}).get("unitPrice", {}).get("price"),
        ),
        ("showUnitPriceInfo.price", item.get("showUnitPriceInfo", {}).get("price")),
        ("salePrice", item.get("salePrice")),
        ("retailPrice", item.get("retailPrice")),
    )
    for source, value in candidates:
        if not isinstance(value, dict):
            continue
        price = Price(
            source=source,
            amount=as_optional_string(value.get("amount")),
            amountWithSymbol=as_optional_string(value.get("amountWithSymbol")),
            currency=as_optional_string(value.get("currency")),
        )
        return price, price.amountWithSymbol
    return None, None


def normalize_item(
    item: dict[str, Any],
    *,
    source_group: str,
    availability: AvailabilityStatus,
) -> ExtractedCartItem:
    display_price, amount_with_symbol = select_display_price(item)
    sold_out = as_optional_bool(item.get("soldOutStatus"))
    stock = as_optional_int(item.get("stock"))

    if availability is AvailabilityStatus.OUT_OF_STOCK:
        sold_out = True
        if stock is None:
            stock = 0

    return ExtractedCartItem(
        goods_id=as_optional_string(item.get("goods_id") or item.get("goodsId")),
        goods_sn=as_optional_string(item.get("sku_code") or item.get("skuCode")),
        sku_code=as_optional_string(item.get("goods_sn") or item.get("goodsSn")),
        goods_name=as_optional_string(item.get("goods_name") or item.get("goodsName")),
        goods_img=normalize_image_url(item.get("goods_img") or item.get("goodsImg")),
        goods_attr=as_optional_string(item.get("goodsAttr") or item.get("goods_attr")),
        stock=stock,
        sold_out=sold_out,
        availability=availability,
        source_group=source_group,
        display_price=display_price,
        amountWithSymbol=amount_with_symbol,
        is_on_sale=as_optional_int(item.get("is_on_sale")),
    )


def normalize_payload(
    source_url: str, final_url: str, payload: dict[str, Any]
) -> CartExtraction:
    info = payload.get("info")
    if not isinstance(info, dict):
        raise ValueError("SHEIN response did not contain an info object.")

    group_definitions = (
        ("normalProducts", AvailabilityStatus.AVAILABLE),
        ("outStock", AvailabilityStatus.OUT_OF_STOCK),
        ("unavailable", AvailabilityStatus.UNAVAILABLE),
    )
    products: list[ExtractedCartItem] = []
    counts: dict[str, int] = {}

    for source_group, availability in group_definitions:
        group_items = info.get(source_group) or []
        if not isinstance(group_items, list):
            group_items = []
        counts[source_group] = len(group_items)
        products.extend(
            normalize_item(item, source_group=source_group, availability=availability)
            for item in group_items
            if isinstance(item, dict)
        )

    query = parse_qs(urlparse(final_url).query)
    return CartExtraction(
        source_url=source_url,
        final_url=final_url,
        group_id=query.get("group_id", [None])[0],
        local_country=query.get("local_country", ["SA"])[0],
        all_product_size=as_optional_int(info.get("allProductSize")) or len(products),
        counts=counts,
        products=products,
    )


def extract_cart(url: str, *, headless: bool, timeout_seconds: float) -> CartExtraction:
    captured_payload: dict[str, Any] | None = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            **playwright.devices["iPhone 13"],
            locale="ar-SA",
            timezone_id="Asia/Riyadh",
            extra_http_headers={"Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8"},
        )
        page = context.new_page()

        def capture_response(response: Response) -> None:
            nonlocal captured_payload
            if TARGET_ENDPOINT not in response.url:
                return
            try:
                value = response.json()
            except (PlaywrightError, json.JSONDecodeError):
                return
            if isinstance(value, dict):
                captured_payload = value

        page.on("response", capture_response)
        page.goto(
            url, wait_until="domcontentloaded", timeout=int(timeout_seconds * 1000)
        )

        deadline = monotonic() + timeout_seconds
        while captured_payload is None and monotonic() < deadline:
            page.wait_for_timeout(250)

        final_url = page.url
        context.close()
        browser.close()

    if captured_payload is None:
        raise capture_failure_error(final_url)
    return normalize_payload(url, final_url, captured_payload)


def write_output(
    extraction: CartExtraction,
    *,
    customer_name: str | None = None,
    order_number: str | None = None,
    analyzed_at: datetime | None = None,
) -> Path:
    OUTPUT_DIRECTORY.mkdir(exist_ok=True)
    analysis_time = analyzed_at or datetime.now().astimezone()
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
    output_path = unique_output_path(OUTPUT_DIRECTORY, f"{identity}-{timestamp}")
    extraction.customer_name = display_name
    extraction.order_number = display_order_number
    extraction.analyzed_at = analysis_time
    extraction.output_file = output_path.name
    output_path.write_text(extraction.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract all products from a SHEIN cart share link."
    )
    parser.add_argument("url", type=validate_shein_url)
    parser.add_argument(
        "--headless", action="store_true", help="Hide the Chromium window."
    )
    parser.add_argument(
        "--timeout", type=float, default=60, help="Maximum wait time in seconds."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("Opening the SHEIN shared link...")
    try:
        extraction = extract_cart(
            args.url, headless=args.headless, timeout_seconds=args.timeout
        )
    except CartExtractionError as error:
        print(f"فشل الاستخراج: {error}")
        return 1
    output_path = write_output(extraction)
    print(f"Group ID: {extraction.group_id}")
    print(f"Available: {extraction.counts['normalProducts']}")
    print(f"Out of stock: {extraction.counts['outStock']}")
    print(f"Unavailable: {extraction.counts['unavailable']}")
    print(f"Total extracted: {len(extraction.products)}")
    print(f"Output saved to: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
