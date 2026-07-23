from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from shein_extractor.application.jobs import (
    JobStatus,
    ProcessingJob,
    ProcessingQueue,
)
from shein_extractor.application.processing import ProcessCartRequest
from shein_extractor.presentation.api.schemas import (
    ApiErrorResponse,
    HealthResponse,
    JobAcceptedResponse,
    JobStatusResponse,
    ProcessRequestBody,
)
from shein_extractor.presentation.api.security import ApiKeyVerifier


def create_app(
    queue: ProcessingQueue,
    *,
    api_key: str,
    output_directory: Path,
    export_directory: Path,
    synchronous_wait_seconds: float = 900,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        queue.start()
        try:
            yield
        finally:
            queue.stop()

    app = FastAPI(
        title="SHEIN Cart Processing API",
        version="0.2.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.queue = queue
    app.state.api_key_configured = bool(api_key)
    app.state.output_directory = output_directory
    app.state.export_directory = export_directory
    verify_api_key = ApiKeyVerifier(api_key)

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    def live() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get(
        "/health/ready",
        response_model=HealthResponse,
        responses={503: {"model": ApiErrorResponse}},
        tags=["health"],
    )
    def ready(response: Response) -> HealthResponse:
        if not app.state.api_key_configured or not queue.is_running:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return HealthResponse(status="not_ready")
        try:
            _ensure_directory_writable(output_directory)
            _ensure_directory_writable(export_directory)
        except OSError:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return HealthResponse(status="not_ready")
        return HealthResponse(status="ready")

    @app.post(
        "/v1/jobs",
        response_model=JobAcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
        responses={401: {"model": ApiErrorResponse}},
        tags=["processing"],
    )
    def create_job(
        body: ProcessRequestBody,
        _: None = Depends(verify_api_key),
    ) -> JobAcceptedResponse:
        job = queue.submit(_to_request(body))
        return _accepted_response(job)

    @app.get(
        "/v1/jobs/{job_id}",
        response_model=JobStatusResponse,
        responses={401: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
        tags=["processing"],
    )
    def get_job(
        job_id: str,
        _: None = Depends(verify_api_key),
    ) -> JobStatusResponse:
        return _status_response(_require_job(queue, job_id))

    @app.get(
        "/v1/jobs/{job_id}/pdf",
        response_class=FileResponse,
        responses={
            200: {"content": {"application/pdf": {}}},
            401: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
        },
        tags=["processing"],
    )
    def get_job_pdf(
        job_id: str,
        _: None = Depends(verify_api_key),
    ) -> FileResponse:
        return _pdf_response(_require_job(queue, job_id))

    @app.post(
        "/v1/process",
        response_class=FileResponse,
        responses={
            200: {"content": {"application/pdf": {}}},
            401: {"model": ApiErrorResponse},
            410: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
            502: {"model": ApiErrorResponse},
            504: {"model": ApiErrorResponse},
        },
        tags=["processing"],
    )
    async def process(
        body: ProcessRequestBody,
        _: None = Depends(verify_api_key),
    ) -> FileResponse:
        submitted = queue.submit(_to_request(body))
        job = await run_in_threadpool(
            queue.wait,
            submitted.job_id,
            timeout_seconds=synchronous_wait_seconds,
        )
        if job is None:
            raise HTTPException(status_code=404, detail="المهمة غير موجودة.")
        if not job.is_terminal:
            raise HTTPException(
                status_code=504,
                detail=f"انتهت مهلة الانتظار، وما زالت المهمة قيد التنفيذ: {job.job_id}",
                headers={"X-Job-ID": job.job_id},
            )
        return _pdf_response(job)

    return app


def _to_request(body: ProcessRequestBody) -> ProcessCartRequest:
    return ProcessCartRequest(
        raw_input=body.raw_input,
        customer_name=body.customer_name,
        order_number=body.order_number,
        timeout_seconds=body.timeout_seconds,
    )


def _accepted_response(job: ProcessingJob) -> JobAcceptedResponse:
    return JobAcceptedResponse(
        job_id=job.job_id,
        status=job.status,
        status_url=f"/v1/jobs/{job.job_id}",
        pdf_url=f"/v1/jobs/{job.job_id}/pdf",
    )


def _status_response(job: ProcessingJob) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        sequence=job.sequence,
        status=job.status,
        stage=job.stage,
        progress_completed=job.progress_completed,
        progress_total=job.progress_total,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        product_count=job.product_count,
        page_count=job.page_count,
        unavailable_image_count=job.unavailable_image_count,
        json_path=str(job.json_path) if job.json_path else None,
        pdf_path=str(job.pdf_path) if job.pdf_path else None,
        error_type=job.error_type,
        error_message=job.error_message,
    )


def _require_job(queue: ProcessingQueue, job_id: str) -> ProcessingJob:
    job = queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="المهمة غير موجودة.")
    return job


def _pdf_response(job: ProcessingJob) -> FileResponse:
    if job.status == JobStatus.FAILED:
        raise _job_failure(job)
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"ملف PDF غير جاهز بعد. حالة المهمة: {job.status.value}",
        )
    if job.pdf_path is None or not job.pdf_path.is_file():
        raise HTTPException(status_code=404, detail="ملف PDF الناتج غير موجود.")
    return FileResponse(
        job.pdf_path,
        media_type="application/pdf",
        filename=job.pdf_path.name,
        headers={
            "X-Job-ID": job.job_id,
            "X-Product-Count": str(job.product_count or 0),
            "X-PDF-Page-Count": str(job.page_count or 0),
            "X-Unavailable-Image-Count": str(job.unavailable_image_count or 0),
        },
    )


def _job_failure(job: ProcessingJob) -> HTTPException:
    status_code = {
        "InvalidProcessingInputError": 422,
        "ExpiredShareLinkError": 410,
        "CartExtractionError": 502,
    }.get(job.error_type or "", 500)
    return HTTPException(
        status_code=status_code,
        detail=job.error_message or "تعذرت معالجة السلة وإنشاء التقرير.",
    )


def _ensure_directory_writable(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / ".healthcheck"
    probe.touch(exist_ok=True)
    probe.unlink()
