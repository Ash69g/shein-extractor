from __future__ import annotations

import base64
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

from shein_extractor.application.reporting import ExportReport
from shein_extractor.domain.models import (
    AvailabilityStatus,
    CartExtraction,
    ExtractedCartItem,
)
from shein_extractor.infrastructure.pdf import PlaywrightPdfReportExporter
from shein_extractor.infrastructure.pdf.headless import render_report_html


PNG_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def sample_extraction() -> CartExtraction:
    return CartExtraction(
        source_url="https://onelink.shein.com/43/example",
        final_url="https://m.shein.com/cart?group_id=10",
        group_id="10",
        local_country="SA",
        all_product_size=2,
        counts={"normalProducts": 1, "outStock": 0, "unavailable": 1},
        customer_name="حياة شطوان",
        order_number="T-501",
        analyzed_at=datetime(2026, 7, 23, 10, 30, tzinfo=UTC),
        products=[
            ExtractedCartItem(
                goods_id="1",
                sku_code="sr26011111111111111111",
                goods_name="منتج عربي طويل " * 12,
                goods_img="https://img.example/1.png",
                goods_attr="أخضر / L",
                amountWithSymbol="SR10",
                source_group="normalProducts",
                availability=AvailabilityStatus.AVAILABLE,
            ),
            ExtractedCartItem(
                goods_id="2",
                sku_code="sw26022222222222222222",
                goods_name="منتج غير متوفر",
                goods_img="https://img.example/2.png",
                source_group="unavailable",
                availability=AvailabilityStatus.UNAVAILABLE,
            ),
        ],
    )


def test_headless_html_contains_rtl_cards_and_all_products() -> None:
    document, unavailable_images = render_report_html(
        sample_extraction(),
        {"https://img.example/1.png": PNG_IMAGE},
        json_name="T-501-customer.json",
    )

    assert '<html lang="ar" dir="rtl">' in document
    assert "حياة شطوان" in document
    assert "T-501" in document
    assert 'href="https://onelink.shein.com/43/example"' in document
    assert "sr26011111111111111111" in document
    assert "sw26022222222222222222" in document
    assert document.count("<tr>") == 3
    assert unavailable_images == 1
    assert "…" in document


def test_headless_pdf_adapter_creates_readable_report(tmp_path: Path) -> None:
    output = tmp_path / "report.pdf"
    progress: list[tuple[int, int]] = []

    result = ExportReport(PlaywrightPdfReportExporter()).execute(
        sample_extraction(),
        output,
        {"https://img.example/1.png": PNG_IMAGE},
        json_name="T-501-customer.json",
        progress_callback=lambda current, maximum: progress.append((current, maximum)),
    )

    reader = PdfReader(output)
    assert result.path == output
    assert result.page_count == len(reader.pages)
    assert result.page_count >= 1
    assert result.unavailable_image_count == 1
    assert output.read_bytes().startswith(b"%PDF")
    assert progress[-1] == (result.page_count, result.page_count)
    assert reader.pages[0].get("/Annots")


def test_importing_headless_pdf_does_not_import_pyside() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from shein_extractor.infrastructure.pdf import "
                "PlaywrightPdfReportExporter; "
                "assert PlaywrightPdfReportExporter; "
                "assert 'PySide6' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
