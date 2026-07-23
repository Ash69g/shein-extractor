from __future__ import annotations

from pydantic import BaseModel, Field


class ProcessRequestBody(BaseModel):
    raw_input: str = Field(min_length=1, max_length=20_000)
    customer_name: str | None = Field(default=None, max_length=200)
    order_number: str | None = Field(default=None, max_length=100)
    timeout_seconds: float = Field(default=60, ge=10, le=300)


class HealthResponse(BaseModel):
    status: str


class ApiErrorResponse(BaseModel):
    detail: str
