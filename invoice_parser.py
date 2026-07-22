"""Backward-compatible imports for invoice parsing."""

from _bootstrap import ensure_src_path

ensure_src_path()

from shein_extractor.application.invoice_parser import (  # noqa: E402,F401
    InvoiceData,
    parse_invoice_text,
)

__all__ = ["InvoiceData", "parse_invoice_text"]
