from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from shein_extractor.application.jobs import JobStatus, ProcessingJob
from shein_extractor.application.processing import (
    ProcessCartRequest,
    ProcessCartResult,
    ProcessingProgress,
    ProcessingStage,
)


class SqliteJobRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS processing_jobs (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    raw_input TEXT NOT NULL,
                    customer_name TEXT,
                    order_number TEXT,
                    analyzed_at TEXT,
                    headless INTEGER NOT NULL,
                    timeout_seconds REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    stage TEXT,
                    progress_completed INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    json_path TEXT,
                    pdf_path TEXT,
                    product_count INTEGER,
                    page_count INTEGER,
                    unavailable_image_count INTEGER,
                    failed_image_urls TEXT NOT NULL DEFAULT '[]',
                    error_type TEXT,
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_processing_jobs_status_sequence
                ON processing_jobs(status, sequence);
                """
            )

    def recover_interrupted(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE processing_jobs
                SET status = ?, started_at = NULL, stage = NULL,
                    progress_completed = 0, progress_total = 0
                WHERE status = ?
                """,
                (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
            )
            return cursor.rowcount

    def enqueue(self, job_id: str, request: ProcessCartRequest) -> ProcessingJob:
        created_at = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO processing_jobs (
                    job_id, status, raw_input, customer_name, order_number,
                    analyzed_at, headless, timeout_seconds, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    JobStatus.QUEUED.value,
                    request.raw_input,
                    request.customer_name,
                    request.order_number,
                    _serialize_datetime(request.analyzed_at),
                    int(request.headless),
                    request.timeout_seconds,
                    _serialize_datetime(created_at),
                ),
            )
        job = self.get(job_id)
        if job is None:
            raise RuntimeError("The queued job could not be loaded.")
        return job

    def claim_next(self) -> ProcessingJob | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT job_id
                FROM processing_jobs
                WHERE status = ?
                ORDER BY sequence
                LIMIT 1
                """,
                (JobStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            started_at = _serialize_datetime(_utc_now())
            connection.execute(
                """
                UPDATE processing_jobs
                SET status = ?, started_at = ?, completed_at = NULL,
                    error_type = NULL, error_message = NULL
                WHERE job_id = ? AND status = ?
                """,
                (
                    JobStatus.RUNNING.value,
                    started_at,
                    row["job_id"],
                    JobStatus.QUEUED.value,
                ),
            )
            claimed = connection.execute(
                "SELECT * FROM processing_jobs WHERE job_id = ?",
                (row["job_id"],),
            ).fetchone()
            connection.commit()
        return _row_to_job(claimed) if claimed is not None else None

    def update_progress(self, job_id: str, progress: ProcessingProgress) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE processing_jobs
                SET stage = ?, progress_completed = ?, progress_total = ?
                WHERE job_id = ? AND status = ?
                """,
                (
                    progress.stage.value,
                    progress.completed,
                    progress.total,
                    job_id,
                    JobStatus.RUNNING.value,
                ),
            )

    def complete(self, job_id: str, result: ProcessCartResult) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE processing_jobs
                SET status = ?, completed_at = ?, stage = ?,
                    progress_completed = 1, progress_total = 1,
                    json_path = ?, pdf_path = ?, product_count = ?,
                    page_count = ?, unavailable_image_count = ?,
                    failed_image_urls = ?, error_type = NULL, error_message = NULL
                WHERE job_id = ?
                """,
                (
                    JobStatus.COMPLETED.value,
                    _serialize_datetime(_utc_now()),
                    ProcessingStage.COMPLETED.value,
                    str(result.json_path),
                    str(result.pdf_path),
                    result.extraction.all_product_size,
                    result.page_count,
                    result.unavailable_image_count,
                    json.dumps(result.failed_image_urls, ensure_ascii=False),
                    job_id,
                ),
            )

    def fail(self, job_id: str, error_type: str, error_message: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE processing_jobs
                SET status = ?, completed_at = ?, error_type = ?, error_message = ?
                WHERE job_id = ?
                """,
                (
                    JobStatus.FAILED.value,
                    _serialize_datetime(_utc_now()),
                    error_type,
                    error_message,
                    job_id,
                ),
            )

    def get(self, job_id: str) -> ProcessingJob | None:
        if not self.database_path.exists():
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM processing_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return _row_to_job(row) if row is not None else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection


def _row_to_job(row: sqlite3.Row) -> ProcessingJob:
    stage_value = row["stage"]
    return ProcessingJob(
        job_id=row["job_id"],
        sequence=row["sequence"],
        status=JobStatus(row["status"]),
        request=ProcessCartRequest(
            raw_input=row["raw_input"],
            customer_name=row["customer_name"],
            order_number=row["order_number"],
            analyzed_at=_parse_datetime(row["analyzed_at"]),
            headless=bool(row["headless"]),
            timeout_seconds=row["timeout_seconds"],
        ),
        created_at=_required_datetime(row["created_at"]),
        started_at=_parse_datetime(row["started_at"]),
        completed_at=_parse_datetime(row["completed_at"]),
        stage=ProcessingStage(stage_value) if stage_value else None,
        progress_completed=row["progress_completed"],
        progress_total=row["progress_total"],
        json_path=Path(row["json_path"]) if row["json_path"] else None,
        pdf_path=Path(row["pdf_path"]) if row["pdf_path"] else None,
        product_count=row["product_count"],
        page_count=row["page_count"],
        unavailable_image_count=row["unavailable_image_count"],
        failed_image_urls=tuple(json.loads(row["failed_image_urls"] or "[]")),
        error_type=row["error_type"],
        error_message=row["error_message"],
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _required_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)
