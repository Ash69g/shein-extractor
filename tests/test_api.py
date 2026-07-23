from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shein_extractor.application.processing import (
    ProcessCartRequest,
    ProcessCartResult,
)
from shein_extractor.domain.errors import (
    CartExtractionError,
    ExpiredShareLinkError,
    InvalidProcessingInputError,
)
from shein_extractor.domain.models import CartExtraction
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

    def execute(self, request: ProcessCartRequest) -> ProcessCartResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def sample_result(tmp_path: Path) -> ProcessCartResult:
    pdf_path = tmp_path / "exports" / "T-501-customer.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")
    json_path = tmp_path / "outputs" / "T-501-customer.json"
    json_path.parent.mkdir(parents=True)
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


def make_client(
    tmp_path: Path,
    processor: StubProcessor,
    *,
    api_key: str = "secret-key",
) -> TestClient:
    app = create_app(
        processor,  # type: ignore[arg-type]
        api_key=api_key,
        output_directory=tmp_path / "outputs",
        export_directory=tmp_path / "exports",
    )
    return TestClient(app)


def test_health_endpoints_report_liveness_and_readiness(tmp_path: Path) -> None:
    client = make_client(tmp_path, StubProcessor(), api_key="secret-key")

    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")

    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert (tmp_path / "outputs").is_dir()
    assert (tmp_path / "exports").is_dir()


def test_readiness_and_processing_fail_when_api_key_is_not_configured(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, StubProcessor(), api_key="")

    ready = client.get("/health/ready")
    process = client.post("/v1/process", json={"raw_input": "invoice"})

    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready"}
    assert process.status_code == 503
    assert process.json()["detail"] == "لم يتم إعداد مفتاح API على الخادم."


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
def test_processing_rejects_missing_or_invalid_api_key(
    tmp_path: Path,
    headers: dict[str, str],
) -> None:
    client = make_client(tmp_path, StubProcessor())

    response = client.post(
        "/v1/process",
        json={"raw_input": "invoice"},
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "مفتاح API غير صالح."


def test_processing_returns_pdf_and_metadata_headers(tmp_path: Path) -> None:
    processor = StubProcessor(sample_result(tmp_path))
    client = make_client(tmp_path, processor)

    response = client.post(
        "/v1/process",
        headers={"X-API-Key": "secret-key"},
        json={
            "raw_input": "invoice text",
            "customer_name": "حياة شطوان",
            "order_number": "T-501",
            "timeout_seconds": 90,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-1.4")
    assert response.headers["x-product-count"] == "2"
    assert response.headers["x-pdf-page-count"] == "3"
    assert response.headers["x-unavailable-image-count"] == "1"
    assert response.headers["x-request-id"]
    assert "attachment;" in response.headers["content-disposition"]
    assert processor.requests == [
        ProcessCartRequest(
            raw_input="invoice text",
            customer_name="حياة شطوان",
            order_number="T-501",
            timeout_seconds=90,
        )
    ]


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (InvalidProcessingInputError("invalid input"), 422),
        (ExpiredShareLinkError("expired"), 410),
        (CartExtractionError("gateway failed"), 502),
        (RuntimeError("pdf failed"), 500),
    ],
)
def test_processing_maps_domain_and_runtime_errors(
    tmp_path: Path,
    error: Exception,
    expected_status: int,
) -> None:
    client = make_client(tmp_path, StubProcessor(error=error))

    response = client.post(
        "/v1/process",
        headers={"X-API-Key": "secret-key"},
        json={"raw_input": "invoice"},
    )

    assert response.status_code == expected_status


def test_processing_validates_request_body_before_execution(tmp_path: Path) -> None:
    processor = StubProcessor()
    client = make_client(tmp_path, processor)

    response = client.post(
        "/v1/process",
        headers={"X-API-Key": "secret-key"},
        json={"raw_input": "", "timeout_seconds": 5},
    )

    assert response.status_code == 422
    assert processor.requests == []
