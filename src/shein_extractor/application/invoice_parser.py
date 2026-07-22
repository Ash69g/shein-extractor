from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse


CUSTOMER_PATTERN = re.compile(
    r"اسم\s*العميل[ \t]*[:：]?[ \t]*"
    r"(?:\r?\n[ \t]*[•·\-–—]?[ \t]*)?([^\r\n]+)",
    re.IGNORECASE,
)
ORDER_PATTERN = re.compile(
    r"رقم\s*(?:الطلبي(?:ة|ه)|الطلب)[ \t]*[:：]?[ \t]*"
    r"([A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)*)",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
TRAILING_URL_CHARACTERS = ".,،؛;:!?؟)]}»"
TEXT_DECORATIONS = " \t*•·-–—_:："


@dataclass(frozen=True)
class InvoiceData:
    customer_name: str | None
    order_number: str | None
    cart_urls: tuple[str, ...]

    @property
    def cart_url(self) -> str | None:
        return self.cart_urls[0] if len(self.cart_urls) == 1 else None

    @property
    def has_multiple_cart_urls(self) -> bool:
        return len(self.cart_urls) > 1


def _clean_text_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip(TEXT_DECORATIONS).strip()
    return cleaned or None


def _is_shein_url(value: str) -> bool:
    hostname = (urlparse(value).hostname or "").lower()
    return hostname == "shein.com" or hostname.endswith(".shein.com")


def parse_invoice_text(value: str) -> InvoiceData:
    normalized = value.replace("\u200e", "").replace("\u200f", "").replace("\ufeff", "")
    customer_match = CUSTOMER_PATTERN.search(normalized)
    order_match = ORDER_PATTERN.search(normalized)
    cart_urls: list[str] = []
    for match in URL_PATTERN.finditer(normalized):
        candidate = match.group(0).rstrip(TRAILING_URL_CHARACTERS)
        if _is_shein_url(candidate) and candidate not in cart_urls:
            cart_urls.append(candidate)
    return InvoiceData(
        customer_name=_clean_text_value(customer_match.group(1) if customer_match else None),
        order_number=_clean_text_value(order_match.group(1) if order_match else None),
        cart_urls=tuple(cart_urls),
    )

