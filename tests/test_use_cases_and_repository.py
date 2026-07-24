from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from shein_extractor.application.use_cases import AnalyzeCart, AnalyzeCartRequest
from shein_extractor.domain.models import AvailabilityStatus, CartExtraction, ExtractedCartItem
from shein_extractor.infrastructure.persistence import JsonExtractionRepository


def sample_extraction() -> CartExtraction:
    return CartExtraction(
        source_url="https://onelink.shein.com/43/value",
        final_url="https://m.shein.com/cart?group_id=10",
        group_id="10",
        all_product_size=1,
        counts={"normalProducts": 1, "outStock": 0, "unavailable": 0},
        products=[
            ExtractedCartItem(
                goods_id="1",
                sku_code="sr2601",
                source_group="normalProducts",
                availability=AvailabilityStatus.AVAILABLE,
            )
        ],
    )


class FakeGateway:
    def __init__(self, extraction: CartExtraction) -> None:
        self.extraction = extraction
        self.calls: list[tuple[str, bool, float]] = []

    def extract(self, url: str, *, headless: bool, timeout_seconds: float) -> CartExtraction:
        self.calls.append((url, headless, timeout_seconds))
        return self.extraction


def test_analyze_cart_coordinates_gateway_and_repository(tmp_path: Path) -> None:
    extraction = sample_extraction()
    gateway = FakeGateway(extraction)
    repository = JsonExtractionRepository(tmp_path)
    analyzed_at = datetime(2026, 7, 22, 8, 30, 0, tzinfo=timezone.utc)
    result = AnalyzeCart(gateway, repository).execute(
        AnalyzeCartRequest(
            extraction.source_url,
            customer_name="حياة شطوان",
            order_number="T-501",
            analyzed_at=analyzed_at,
            headless=True,
            timeout_seconds=45,
        )
    )
    assert gateway.calls == [(extraction.source_url, True, 45)]
    assert result.output_path.exists()
    assert "T-501" in result.output_path.name
    assert "20260722-113000" in result.output_path.name
    loaded = repository.load(result.output_path)
    assert loaded.customer_name == "حياة شطوان"
    assert loaded.order_number == "T-501"
    assert loaded.analyzed_at == datetime(
        2026,
        7,
        22,
        11,
        30,
        tzinfo=timezone(timedelta(hours=3), name="GMT+3"),
    )
    assert loaded.products[0].sku_code == "sr2601"
