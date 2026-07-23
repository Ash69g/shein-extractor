from __future__ import annotations

from datetime import datetime
from pathlib import Path
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ImageFetchResult:
    images: Mapping[str, bytes]
    failed_urls: tuple[str, ...]


class ProductImageFetcher(Protocol):
    def fetch(
        self,
        urls: Iterable[str],
        *,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ImageFetchResult: ...
