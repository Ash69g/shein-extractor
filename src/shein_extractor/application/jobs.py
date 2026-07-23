from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Protocol
from uuid import uuid4

from shein_extractor.application.processing import (
    ProcessCart,
    ProcessCartRequest,
    ProcessCartResult,
    ProcessingProgress,
    ProcessingStage,
)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class ProcessingJob:
    job_id: str
    sequence: int
    status: JobStatus
    request: ProcessCartRequest
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    stage: ProcessingStage | None = None
    progress_completed: int = 0
    progress_total: int = 0
    json_path: Path | None = None
    pdf_path: Path | None = None
    product_count: int | None = None
    page_count: int | None = None
    unavailable_image_count: int | None = None
    failed_image_urls: tuple[str, ...] = ()
    error_type: str | None = None
    error_message: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in {JobStatus.COMPLETED, JobStatus.FAILED}


class JobRepository(Protocol):
    def initialize(self) -> None: ...

    def recover_interrupted(self) -> int: ...

    def enqueue(self, job_id: str, request: ProcessCartRequest) -> ProcessingJob: ...

    def claim_next(self) -> ProcessingJob | None: ...

    def update_progress(self, job_id: str, progress: ProcessingProgress) -> None: ...

    def complete(self, job_id: str, result: ProcessCartResult) -> None: ...

    def fail(self, job_id: str, error_type: str, error_message: str) -> None: ...

    def get(self, job_id: str) -> ProcessingJob | None: ...


class ProcessingQueue:
    def __init__(
        self,
        processor: ProcessCart,
        repository: JobRepository,
        *,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        self.processor = processor
        self.repository = repository
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = Event()
        self._wake_event = Event()
        self._lifecycle_lock = Lock()
        self._thread: Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.is_running:
                return
            self.repository.initialize()
            self.repository.recover_interrupted()
            self._stop_event.clear()
            self._thread = Thread(
                target=self._work,
                name="shein-processing-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout_seconds: float = 30) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_event.set()
            self._wake_event.set()
        thread.join(timeout=timeout_seconds)
        with self._lifecycle_lock:
            if not thread.is_alive():
                self._thread = None

    def submit(self, request: ProcessCartRequest) -> ProcessingJob:
        job = self.repository.enqueue(str(uuid4()), request)
        self._wake_event.set()
        return job

    def get(self, job_id: str) -> ProcessingJob | None:
        return self.repository.get(job_id)

    def wait(self, job_id: str, *, timeout_seconds: float) -> ProcessingJob | None:
        deadline = _monotonic_deadline(timeout_seconds)
        while True:
            job = self.repository.get(job_id)
            if job is None or job.is_terminal:
                return job
            remaining = deadline - _monotonic()
            if remaining <= 0:
                return job
            self._wake_event.wait(min(remaining, self.poll_interval_seconds))
            self._wake_event.clear()

    def _work(self) -> None:
        while not self._stop_event.is_set():
            job = self.repository.claim_next()
            if job is None:
                self._wake_event.wait(self.poll_interval_seconds)
                self._wake_event.clear()
                continue
            try:
                result = self.processor.execute(
                    job.request,
                    progress_callback=lambda progress: self.repository.update_progress(
                        job.job_id,
                        progress,
                    ),
                )
            except Exception as error:
                self.repository.fail(
                    job.job_id,
                    type(error).__name__,
                    str(error),
                )
            else:
                self.repository.complete(job.job_id, result)
            finally:
                self._wake_event.set()


def _monotonic() -> float:
    from time import monotonic

    return monotonic()


def _monotonic_deadline(timeout_seconds: float) -> float:
    return _monotonic() + timeout_seconds
