from __future__ import annotations

import pytest

from shein_extractor.application.invoice_parser import parse_invoice_text
from shein_extractor.application.validation import validate_shein_url
from shein_extractor.domain.models import AvailabilityStatus
from shein_extractor.infrastructure.shein.payload_normalizer import normalize_payload


@pytest.mark.parametrize(
    ("customer", "order", "url"),
    [
        ("اكرام عبدالله", "H-2237", "https://api-shein.shein.com/h5/sharejump/appjump?link=test"),
        ("حياة شطوان", "T-501", "https://onelink.shein.com/43/example"),
    ],
)
def test_invoice_parser_extracts_supported_fields(customer: str, order: str, url: str) -> None:
    text = f"اسم العميل :\n• {customer}\nرقم الطلبية : {order}\nرابط الطلب:\n{url}"
    result = parse_invoice_text(text)
    assert result.customer_name == customer
    assert result.order_number == order
    assert result.cart_url == url


def test_invoice_parser_accepts_link_only_and_detects_multiple_links() -> None:
    single = parse_invoice_text("https://onelink.shein.com/43/first")
    assert single.customer_name is None
    assert single.order_number is None
    assert single.cart_url == "https://onelink.shein.com/43/first"

    multiple = parse_invoice_text(
        "https://onelink.shein.com/43/first\nhttps://onelink.shein.com/43/second"
    )
    assert multiple.has_multiple_cart_urls
    assert multiple.cart_url is None


def test_url_validation_rejects_non_shein_hosts() -> None:
    assert validate_shein_url(" https://onelink.shein.com/43/value ").endswith("/value")
    with pytest.raises(ValueError):
        validate_shein_url("https://example.com/cart")


def test_payload_normalizer_preserves_every_group_and_sku_contract() -> None:
    payload = {
        "info": {
            "allProductSize": 3,
            "normalProducts": [
                {
                    "goods_id": "1",
                    "goods_sn": "sr2601",
                    "sku_code": "internal-1",
                    "goods_name": "منتج متاح",
                    "goodsAttr": "أخضر / L",
                    "stock": 4,
                    "priceData": {
                        "unitPrice": {"price": {"amount": "10", "amountWithSymbol": "SR10"}}
                    },
                }
            ],
            "outStock": [
                {"goods_id": "2", "goods_sn": "sw2602", "sku_code": "internal-2"}
            ],
            "unavailable": [
                {"goods_id": "3", "goods_sn": "sh2603", "sku_code": "internal-3"}
            ],
        }
    }
    result = normalize_payload(
        "https://onelink.shein.com/43/value",
        "https://m.shein.com/ar/cart/share/landing?group_id=55&local_country=SA",
        payload,
    )
    assert len(result.products) == 3
    assert result.counts == {"normalProducts": 1, "outStock": 1, "unavailable": 1}
    assert [item.sku_code for item in result.products] == ["sr2601", "sw2602", "sh2603"]
    assert [item.goods_sn for item in result.products] == ["internal-1", "internal-2", "internal-3"]
    assert result.products[1].availability is AvailabilityStatus.OUT_OF_STOCK
    assert result.products[1].sold_out is True
    assert result.products[1].stock == 0
    assert result.products[2].availability is AvailabilityStatus.UNAVAILABLE

