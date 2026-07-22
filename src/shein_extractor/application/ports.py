from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from shein_extractor.domain.models import CartExtraction


class CartGateway(Protocol):
    def extract(
        self,
        url: str,
        *,
        headless: bool,
        timeout_seconds: float,
    ) -> CartExtraction: ...


class ExtractionRepository(Protocol):
    def save(
        self,
        extraction: CartExtraction,
        *,
        customer_name: str | None = None,
        order_number: str | None = None,
        analyzed_at: datetime | None = None,
    ) -> Path: ...

    def load(self, path: Path) -> CartExtraction: ...


class LinkValidator(Protocol):
    def __call__(self, value: str) -> str: ...

