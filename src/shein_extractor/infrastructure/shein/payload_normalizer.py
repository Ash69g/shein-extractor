from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from shein_extractor.domain.models import (
    AvailabilityStatus,
    CartExtraction,
    ExtractedCartItem,
    Price,
)


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
    return f"https:{image_url}" if image_url and image_url.startswith("//") else image_url


def select_display_price(item: dict[str, Any]) -> tuple[Price | None, str | None]:
    candidates = (
        ("priceData.unitPrice.price", item.get("priceData", {}).get("unitPrice", {}).get("price")),
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
        stock = 0 if stock is None else stock
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
    source_url: str,
    final_url: str,
    payload: dict[str, Any],
) -> CartExtraction:
    info = payload.get("info")
    if not isinstance(info, dict):
        raise ValueError("SHEIN response did not contain an info object.")
    definitions = (
        ("normalProducts", AvailabilityStatus.AVAILABLE),
        ("outStock", AvailabilityStatus.OUT_OF_STOCK),
        ("unavailable", AvailabilityStatus.UNAVAILABLE),
    )
    products: list[ExtractedCartItem] = []
    counts: dict[str, int] = {}
    for source_group, availability in definitions:
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

