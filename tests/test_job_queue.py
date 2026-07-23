from __future__ import annotations

from pathlib import Path

from shein_extractor.application.jobs import JobStatus, ProcessingQueue
from shein_extractor.application.processing import (
    ProcessCartRequest,
    ProcessCartResult,
    ProcessingProgress,
    ProcessingProgressCallback,
    ProcessingStage,
)
from shein_extractor.domain.models import CartExtraction
from shein_extractor.infrastructure.queue import SqliteJobRepository


class RecordingProcessor:
    def __init__(self, directory: Path, *, fail_on: str | None = None) -> None:
        self.directory = directory
        self.fail_on = fail_on
        self.processed: list[str] = []

    def execute(
        self,
        request: ProcessCartRequest,
        *,
        progress_callback: ProcessingProgressCallback | None = None,
    ) -> ProcessCartResult:
        self.processed.append(request.raw_input)
        if self.fail_on == request.raw_input:
            raise RuntimeError("processing failed")
        if progress_callback is not None:
            progress_callback(ProcessingProgress(ProcessingStage.EXTRACTING_CART, 1, 2))
        json_path = self.directory / f"{request.raw_input}.json"
        pdf_path = self.directory / f"{request.raw_input}.pdf"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text("{}", encoding="utf-8")
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")
        extraction = CartExtraction(
            source_url=request.raw_input,
            final_url=request.raw_input,
            group_id=request.raw_input,
            all_product_size=1,
            counts={"normalProducts": 1, "outStock": 0, "unavailable": 0},
            products=[],
        )
        return ProcessCartResult(
            extraction=extraction,
            json_path=json_path,
            pdf_path=pdf_path,
            page_count=1,
            unavailable_image_count=0,
            failed_image_urls=(),
        )


def test_sqlite_repository_claims_jobs_in_fifo_order(tmp_path: Path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.sqlite3")
    repository.initialize()
    first = repository.enqueue("first", ProcessCartRequest("first"))
    second = repository.enqueue("second", ProcessCartRequest("second"))

    claimed_first = repository.claim_next()
    claimed_second = repository.claim_next()

    assert first.sequence < second.sequence
    assert claimed_first is not None
    assert claimed_first.job_id == "first"
    assert claimed_first.status == JobStatus.RUNNING
    assert claimed_second is not None
    assert claimed_second.job_id == "second"


def test_sqlite_repository_recovers_interrupted_jobs(tmp_path: Path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.sqlite3")
    repository.initialize()
    repository.enqueue("job", ProcessCartRequest("input"))
    assert repository.claim_next() is not None

    recovered_count = repository.recover_interrupted()
    recovered = repository.get("job")

    assert recovered_count == 1
    assert recovered is not None
    assert recovered.status == JobStatus.QUEUED
    assert recovered.started_at is None


def test_processing_queue_completes_jobs_in_fifo_order(tmp_path: Path) -> None:
    processor = RecordingProcessor(tmp_path / "results")
    repository = SqliteJobRepository(tmp_path / "jobs.sqlite3")
    queue = ProcessingQueue(
        processor,  # type: ignore[arg-type]
        repository,
        poll_interval_seconds=0.01,
    )
    queue.start()
    try:
        first = queue.submit(ProcessCartRequest("first"))
        second = queue.submit(ProcessCartRequest("second"))
        first_result = queue.wait(first.job_id, timeout_seconds=2)
        second_result = queue.wait(second.job_id, timeout_seconds=2)
    finally:
        queue.stop()

    assert processor.processed == ["first", "second"]
    assert first_result is not None
    assert first_result.status == JobStatus.COMPLETED
    assert first_result.product_count == 1
    assert second_result is not None
    assert second_result.status == JobStatus.COMPLETED


def test_processing_queue_persists_failures(tmp_path: Path) -> None:
    processor = RecordingProcessor(tmp_path / "results", fail_on="bad")
    repository = SqliteJobRepository(tmp_path / "jobs.sqlite3")
    queue = ProcessingQueue(
        processor,  # type: ignore[arg-type]
        repository,
        poll_interval_seconds=0.01,
    )
    queue.start()
    try:
        submitted = queue.submit(ProcessCartRequest("bad"))
        result = queue.wait(submitted.job_id, timeout_seconds=2)
    finally:
        queue.stop()

    assert result is not None
    assert result.status == JobStatus.FAILED
    assert result.error_type == "RuntimeError"
    assert result.error_message == "processing failed"
