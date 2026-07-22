from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

from shein_extractor.application.use_cases import AnalyzeCart
from shein_extractor.application.reporting import ExportReport
from shein_extractor.infrastructure.pdf import QtPdfReportExporter
from shein_extractor.infrastructure.persistence import JsonExtractionRepository
from shein_extractor.infrastructure.shein import PlaywrightCartGateway
from shein_extractor.presentation.qt.main_window import MainWindow


def build_main_window() -> MainWindow:
    repository = JsonExtractionRepository(Path("outputs"))
    analyze_cart = AnalyzeCart(PlaywrightCartGateway(), repository)
    export_report = ExportReport(QtPdfReportExporter())
    return MainWindow(analyze_cart, export_report)


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("SHEIN Extractor")
    window = build_main_window()
    window.show()
    return application.exec()
