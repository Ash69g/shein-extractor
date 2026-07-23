from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from shein_extractor.application.processing import ProcessCart, ProcessCartRequest
from shein_extractor.domain.errors import (
    CartExtractionError,
    ExpiredShareLinkError,
    InvalidProcessingInputError,
)
from shein_extractor.presentation.api.schemas import (
    ApiErrorResponse,
    HealthResponse,
    ProcessRequestBody,
)
from shein_extractor.presentation.api.security import ApiKeyVerifier


def create_app(
    processor: ProcessCart,
    *,
    api_key: str,
    output_directory: Path,
    export_directory: Path,
) -> FastAPI:
    app = FastAPI(
        title="SHEIN Cart Processing API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.processor = processor
    app.state.api_key_configured = bool(api_key)
    app.state.output_directory = output_directory
    app.state.export_directory = export_directory
    verify_api_key = ApiKeyVerifier(api_key)

    @app.get(
        "/health/live",
        response_model=HealthResponse,
        tags=["health"],
    )
    def live() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get(
        "/health/ready",
        response_model=HealthResponse,
        responses={503: {"model": ApiErrorResponse}},
        tags=["health"],
    )
    def ready(response: Response) -> HealthResponse:
        if not app.state.api_key_configured:
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
        "/v1/process",
        response_class=FileResponse,
        responses={
            200: {
                "content": {"application/pdf": {}},
                "description": "ملف PDF الناتج عن تحليل السلة.",
            },
            401: {"model": ApiErrorResponse},
            410: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            502: {"model": ApiErrorResponse},
            503: {"model": ApiErrorResponse},
        },
        tags=["processing"],
    )
    async def process(
        body: ProcessRequestBody,
        _: None = Depends(verify_api_key),
    ) -> FileResponse:
        request_id = str(uuid4())
        try:
            result = await run_in_threadpool(
                processor.execute,
                ProcessCartRequest(
                    raw_input=body.raw_input,
                    customer_name=body.customer_name,
                    order_number=body.order_number,
                    timeout_seconds=body.timeout_seconds,
                ),
            )
        except InvalidProcessingInputError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ExpiredShareLinkError as error:
            raise HTTPException(status_code=410, detail=str(error)) from error
        except CartExtractionError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except (OSError, RuntimeError) as error:
            raise HTTPException(
                status_code=500,
                detail="تعذر إكمال معالجة السلة وإنشاء التقرير.",
            ) from error

        return FileResponse(
            result.pdf_path,
            media_type="application/pdf",
            filename=result.pdf_path.name,
            headers={
                "X-Request-ID": request_id,
                "X-Product-Count": str(result.extraction.all_product_size),
                "X-PDF-Page-Count": str(result.page_count),
                "X-Unavailable-Image-Count": str(result.unavailable_image_count),
            },
        )

    return app


def _ensure_directory_writable(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / ".healthcheck"
    probe.touch(exist_ok=True)
    probe.unlink()
