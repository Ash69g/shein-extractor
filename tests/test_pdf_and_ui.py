from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from shein_extractor.application.reporting import ExportReport
from shein_extractor.application.use_cases import AnalyzeCart
from shein_extractor.domain.models import AvailabilityStatus, CartExtraction, ExtractedCartItem
from shein_extractor.infrastructure.pdf import QtPdfReportExporter
from shein_extractor.infrastructure.persistence import JsonExtractionRepository
from shein_extractor.presentation.qt.main_window import MainWindow


def sample_extraction() -> CartExtraction:
    return CartExtraction(
        source_url="https://onelink.shein.com/43/value",
        final_url="https://m.shein.com/cart?group_id=10",
        group_id="10",
        all_product_size=2,
        counts={"normalProducts": 1, "outStock": 0, "unavailable": 1},
        products=[
            ExtractedCartItem(
                goods_id="1",
                sku_code="sr2601",
                goods_name="منتج للاختبار",
                goods_attr="أخضر / L",
                amountWithSymbol="SR10",
                source_group="normalProducts",
                availability=AvailabilityStatus.AVAILABLE,
            ),
            ExtractedCartItem(
                goods_id="2",
                sku_code="sw2602",
                goods_name="منتج غير متوفر",
                source_group="unavailable",
                availability=AvailabilityStatus.UNAVAILABLE,
            ),
        ],
    )


def application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_pdf_adapter_creates_readable_report(tmp_path: Path) -> None:
    application()
    output = tmp_path / "report.pdf"
    result = ExportReport(QtPdfReportExporter()).execute(
        sample_extraction(),
        output,
        {},
        json_name="analysis.json",
    )
    assert result.path == output
    assert result.page_count >= 1
    assert result.unavailable_image_count == 2
    assert output.read_bytes().startswith(b"%PDF")


def test_main_window_opens_and_closes_without_starting_deferred_export(tmp_path: Path) -> None:
    application()
    repository = JsonExtractionRepository(tmp_path)

    class UnusedGateway:
        def extract(self, *args, **kwargs):
            raise AssertionError("not called")

    class GuardExporter:
        def __init__(self) -> None:
            self.calls = 0

        def export(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("export must not start after close")

    guard = GuardExporter()
    window = MainWindow(AnalyzeCart(UnusedGateway(), repository), ExportReport(guard))
    output_path = repository.save(sample_extraction())
    window.current_output_path = output_path
    window.current_extraction = repository.load(output_path)
    window.auto_export_pending = True
    window.close()
    window._auto_export_pdf()
    assert window.is_closing
    assert not window.auto_export_pending
    assert guard.calls == 0
