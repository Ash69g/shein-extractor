from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from shein_extractor.application.ports import CartGateway, ExtractionRepository
from shein_extractor.domain.models import CartExtraction


@dataclass(frozen=True)
class AnalyzeCartRequest:
    url: str
    customer_name: str | None = None
    order_number: str | None = None
    analyzed_at: datetime | None = None
    headless: bool = True
    timeout_seconds: float = 60


@dataclass(frozen=True)
class AnalyzeCartResult:
    extraction: CartExtraction
    output_path: Path


class AnalyzeCart:
    def __init__(
        self,
        gateway: CartGateway,
        repository: ExtractionRepository,
    ) -> None:
        self.gateway = gateway
        self.repository = repository

    def execute(self, request: AnalyzeCartRequest) -> AnalyzeCartResult:
        extraction = self.gateway.extract(
            request.url,
            headless=request.headless,
            timeout_seconds=request.timeout_seconds,
        )
        output_path = self.repository.save(
            extraction,
            customer_name=request.customer_name,
            order_number=request.order_number,
            analyzed_at=request.analyzed_at,
        )
        return AnalyzeCartResult(extraction, output_path)


class LoadAnalysis:
    def __init__(self, repository: ExtractionRepository) -> None:
        self.repository = repository

    def execute(self, path: Path) -> CartExtraction:
        return self.repository.load(path)

