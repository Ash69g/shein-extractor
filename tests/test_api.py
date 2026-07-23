from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shein_extractor.application.jobs import ProcessingQueue
from shein_extractor.application.processing import (
    ProcessCartRequest,
    ProcessCartResult,
    ProcessingProgressCallback,
)
from shein_extractor.domain.errors import (
    CartExtractionError,
    ExpiredShareLinkError,
    InvalidProcessingInputError,
)
from shein_extractor.domain.models import CartExtraction
from shein_extractor.infrastructure.queue import SqliteJobRepository
from shein_extractor.presentation.api import create_app


class StubProcessor:
    def __init__(
        self,
        result: ProcessCartResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.requests: list[ProcessCartRequest] = []

    def execute(
        self,
        request: ProcessCartRequest,
        *,
        progress_callback: ProcessingProgressCallback | None = None,
    ) -> ProcessCartResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def sample_result(tmp_path: Path) -> ProcessCartResult:
    pdf_path = tmp_path / "exports" / "T-501-customer.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")
    json_path = tmp_path / "outputs" / "T-501-customer.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text("{}", encoding="utf-8")
    extraction = CartExtraction(
        source_url="https://onelink.shein.com/43/example",
        final_url="https://m.shein.com/ar/cart/share/landing?group_id=100",
        group_id="100",
        all_product_size=2,
        counts={"normalProducts": 2, "outStock": 0, "unavailable": 0},
        products=[],
    )
    return ProcessCartResult(
        extraction=extraction,
        json_path=json_path,
        pdf_path=pdf_path,
        page_count=3,
        unavailable_image_count=1,
        failed_image_urls=("https://img.example/missing.webp",),
    )


def make_app(
    tmp_path: Path,
    processor: StubProcessor,
    *,
    api_key: str = "secret-key",
):
    queue = ProcessingQueue(
        processor,  # type: ignore[arg-type]
        SqliteJobRepository(tmp_path / "data" / "jobs.sqlite3"),
        poll_interval_seconds=0.01,
    )
    return create_app(
        queue,
        api_key=api_key,
        output_directory=tmp_path / "outputs",
        export_directory=tmp_path / "exports",
        synchronous_wait_seconds=2,
    )


def test_health_endpoints_report_liveness_and_readiness(tmp_path: Path) -> None:
    app = make_app(tmp_path, StubProcessor(), api_key="secret-key")

    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        ready = client.get("/health/ready")

    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert (tmp_path / "outputs").is_dir()
    assert (tmp_path / "exports").is_dir()


def test_readiness_and_processing_fail_when_api_key_is_not_configured(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path, StubProcessor(), api_key="")

    with TestClient(app) as client:
        ready = client.get("/health/ready")
        process = client.post("/v1/process", json={"raw_input": "invoice"})

    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready"}
    assert process.status_code == 503


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
def test_processing_rejects_missing_or_invalid_api_key(
    tmp_path: Path,
    headers: dict[str, str],
) -> None:
    app = make_app(tmp_path, StubProcessor())

    with TestClient(app) as client:
        response = client.post(
            "/v1/process",
            json={"raw_input": "invoice"},
            headers=headers,
        )

    assert response.status_code == 401


def test_job_endpoints_create_track_and_download_pdf(tmp_path: Path) -> None:
    processor = StubProcessor(sample_result(tmp_path))
    app = make_app(tmp_path, processor)
    headers = {"X-API-Key": "secret-key"}

    with TestClient(app) as client:
        accepted = client.post(
            "/v1/jobs",
            headers=headers,
            json={
                "raw_input": "invoice text",
                "customer_name": "حياة شطوان",
                "order_number": "T-501",
                "timeout_seconds": 90,
            },
        )
        job_id = accepted.json()["job_id"]
        status_response = _wait_for_terminal(client, job_id, headers)
        pdf_response = client.get(f"/v1/jobs/{job_id}/pdf", headers=headers)

    assert accepted.status_code == 202
    assert accepted.json()["status"] == "queued"
    assert accepted.json()["status_url"] == f"/v1/jobs/{job_id}"
    assert status_response.json()["status"] == "completed"
    assert status_response.json()["product_count"] == 2
    assert pdf_response.status_code == 200
    assert pdf_response.content.startswith(b"%PDF-1.4")
    assert pdf_response.headers["x-job-id"] == job_id
    assert pdf_response.headers["x-product-count"] == "2"
    assert processor.requests == [
        ProcessCartRequest(
            raw_input="invoice text",
            customer_name="حياة شطوان",
            order_number="T-501",
            timeout_seconds=90,
        )
    ]


def test_compatibility_endpoint_returns_pdf_through_queue(tmp_path: Path) -> None:
    app = make_app(tmp_path, StubProcessor(sample_result(tmp_path)))

    with TestClient(app) as client:
        response = client.post(
            "/v1/process",
            headers={"X-API-Key": "secret-key"},
            json={"raw_input": "invoice text"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-job-id"]


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (InvalidProcessingInputError("invalid input"), 422),
        (ExpiredShareLinkError("expired"), 410),
        (CartExtractionError("gateway failed"), 502),
        (RuntimeError("pdf failed"), 500),
    ],
)
def test_processing_maps_background_failures(
    tmp_path: Path,
    error: Exception,
    expected_status: int,
) -> None:
    app = make_app(tmp_path, StubProcessor(error=error))

    with TestClient(app) as client:
        response = client.post(
            "/v1/process",
            headers={"X-API-Key": "secret-key"},
            json={"raw_input": "invoice"},
        )

    assert response.status_code == expected_status


def test_pending_and_unknown_pdf_responses(tmp_path: Path) -> None:
    app = make_app(tmp_path, StubProcessor(sample_result(tmp_path)))
    headers = {"X-API-Key": "secret-key"}

    with TestClient(app) as client:
        unknown = client.get("/v1/jobs/missing/pdf", headers=headers)

    assert unknown.status_code == 404


def test_processing_validates_request_body_before_enqueue(tmp_path: Path) -> None:
    processor = StubProcessor()
    app = make_app(tmp_path, processor)

    with TestClient(app) as client:
        response = client.post(
            "/v1/process",
            headers={"X-API-Key": "secret-key"},
            json={"raw_input": "", "timeout_seconds": 5},
        )

    assert response.status_code == 422
    assert processor.requests == []


def _wait_for_terminal(
    client: TestClient,
    job_id: str,
    headers: dict[str, str],
):
    for _ in range(100):
        response = client.get(f"/v1/jobs/{job_id}", headers=headers)
        if response.json()["status"] in {"completed", "failed"}:
            return response
    raise AssertionError("The test job did not reach a terminal status.")
