from __future__ import annotations

import re
import unicodedata

from shein_extractor.domain.models import AvailabilityStatus, ExtractedCartItem


STATUS_LABELS = {
    AvailabilityStatus.AVAILABLE: "متاح",
    AvailabilityStatus.OUT_OF_STOCK: "نافد",
    AvailabilityStatus.UNAVAILABLE: "غير متوفر",
    AvailabilityStatus.UNKNOWN: "غير معروف",
}
ARABIC_DIACRITICS_PATTERN = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")


def normalize_product_search(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = ARABIC_DIACRITICS_PATTERN.sub("", normalized).replace("ـ", "")
    return " ".join(normalized.split())


def product_matches_query(product: ExtractedCartItem, query: str) -> bool:
    normalized_query = normalize_product_search(query)
    if not normalized_query:
        return True
    searchable_values = (
        product.goods_name,
        product.sku_code,
        product.goods_attr,
        STATUS_LABELS[product.availability],
        product.amountWithSymbol,
    )
    return any(
        normalized_query in normalize_product_search(value)
        for value in searchable_values
    )

