from __future__ import annotations

import uvicorn

from shein_extractor.application.jobs import ProcessingQueue
from shein_extractor.application.processing import ProcessCart
from shein_extractor.application.reporting import ExportReport
from shein_extractor.application.use_cases import AnalyzeCart
from shein_extractor.application.validation import validate_shein_url
from shein_extractor.infrastructure.images import HttpxProductImageFetcher
from shein_extractor.infrastructure.pdf import PlaywrightPdfReportExporter
from shein_extractor.infrastructure.persistence import JsonExtractionRepository
from shein_extractor.infrastructure.queue import SqliteJobRepository
from shein_extractor.infrastructure.shein.playwright_gateway import (
    PlaywrightCartGateway,
)
from shein_extractor.presentation.api.app import create_app
from shein_extractor.presentation.api.settings import ApiSettings


def build_app():
    settings = ApiSettings.from_env()
    analyzer = AnalyzeCart(
        PlaywrightCartGateway(),
        JsonExtractionRepository(settings.output_directory),
    )
    processor = ProcessCart(
        analyzer,
        HttpxProductImageFetcher(
            max_attempts=settings.image_max_attempts,
            timeout_seconds=settings.image_timeout_seconds,
        ),
        ExportReport(PlaywrightPdfReportExporter()),
        settings.export_directory,
        link_validator=validate_shein_url,
    )
    queue = ProcessingQueue(
        processor,
        SqliteJobRepository(settings.queue_database),
    )
    return create_app(
        queue,
        api_key=settings.api_key,
        output_directory=settings.output_directory,
        export_directory=settings.export_directory,
        synchronous_wait_seconds=settings.synchronous_wait_seconds,
    )


app = build_app()


def main() -> None:
    settings = ApiSettings.from_env()
    uvicorn.run(
        "shein_extractor.presentation.api.bootstrap:app",
        host=settings.host,
        port=settings.port,
        workers=1,
    )


if __name__ == "__main__":
    main()
