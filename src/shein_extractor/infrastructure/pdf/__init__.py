from .common import PdfExportResult, default_pdf_path, truncate_product_name

__all__ = [
    "PdfExportResult",
    "default_pdf_path",
    "export_cart_pdf",
    "truncate_product_name",
    "QtPdfReportExporter",
    "PlaywrightPdfReportExporter",
]


def __getattr__(name: str):
    if name == "QtPdfReportExporter":
        from .adapter import QtPdfReportExporter

        return QtPdfReportExporter
    if name == "PlaywrightPdfReportExporter":
        from .headless import PlaywrightPdfReportExporter

        return PlaywrightPdfReportExporter
    if name == "export_cart_pdf":
        from .exporter import export_cart_pdf

        return export_cart_pdf
    raise AttributeError(name)
