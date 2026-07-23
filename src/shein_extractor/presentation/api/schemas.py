from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from shein_extractor.application.jobs import JobStatus
from shein_extractor.application.processing import ProcessingStage


class ProcessRequestBody(BaseModel):
    raw_input: str = Field(min_length=1, max_length=20_000)
    customer_name: str | None = Field(default=None, max_length=200)
    order_number: str | None = Field(default=None, max_length=100)
    timeout_seconds: float = Field(default=60, ge=10, le=300)


class HealthResponse(BaseModel):
    status: str


class ApiErrorResponse(BaseModel):
    detail: str


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: JobStatus
    status_url: str
    pdf_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    sequence: int
    status: JobStatus
    stage: ProcessingStage | None
    progress_completed: int
    progress_total: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    product_count: int | None
    page_count: int | None
    unavailable_image_count: int | None
    json_path: str | None
    pdf_path: str | None
    error_type: str | None
    error_message: str | None
