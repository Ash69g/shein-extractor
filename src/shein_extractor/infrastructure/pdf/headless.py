from __future__ import annotations

import base64
import html
import mimetypes
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from shein_extractor.application.reporting import ReportExportResult
from shein_extractor.domain.models import (
    AvailabilityStatus,
    CartExtraction,
    ExtractedCartItem,
)
from shein_extractor.infrastructure.pdf.common import truncate_product_name


STATUS_LABELS = {
    AvailabilityStatus.AVAILABLE: "متاح",
    AvailabilityStatus.OUT_OF_STOCK: "نافد",
    AvailabilityStatus.UNAVAILABLE: "غير متوفر",
    AvailabilityStatus.UNKNOWN: "غير معروف",
}

STATUS_CLASSES = {
    AvailabilityStatus.AVAILABLE: "available",
    AvailabilityStatus.OUT_OF_STOCK: "out-of-stock",
    AvailabilityStatus.UNAVAILABLE: "unavailable",
    AvailabilityStatus.UNKNOWN: "unknown",
}


def _escape(value: object | None, fallback: str = "—") -> str:
    text = str(value).strip() if value is not None else ""
    return html.escape(text or fallback)


def _image_mime_type(data: bytes, source: Path | None = None) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if source is not None:
        guessed, _ = mimetypes.guess_type(source.name)
        if guessed and guessed.startswith("image/"):
            return guessed
    return "application/octet-stream"


def _image_data_uri(value: object | None) -> str | None:
    source: Path | None = None
    data: bytes
    if isinstance(value, str) and value.startswith("data:image/"):
        return value
    if isinstance(value, (str, Path)):
        source = Path(value)
        if not source.is_file():
            return None
        data = source.read_bytes()
    elif isinstance(value, bytes):
        data = value
    elif isinstance(value, bytearray):
        data = bytes(value)
    elif isinstance(value, memoryview):
        data = value.tobytes()
    else:
        return None
    if not data:
        return None
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{_image_mime_type(data, source)};base64,{encoded}"


def _product_price(product: ExtractedCartItem) -> str:
    if product.amountWithSymbol:
        return product.amountWithSymbol
    if product.display_price:
        return (
            product.display_price.amountWithSymbol
            or product.display_price.amount
            or "—"
        )
    return "—"


def _count(extraction: CartExtraction, key: str) -> int:
    return int(extraction.counts.get(key, 0))


def _info_card(label: str, value: str, css_class: str = "") -> str:
    return (
        f'<section class="info-card {css_class}">'
        f'<div class="card-label">{html.escape(label)}</div>'
        f'<div class="card-value">{value}</div>'
        "</section>"
    )


def _counts_card(extraction: CartExtraction) -> str:
    total = extraction.all_product_size
    available = _count(extraction, "normalProducts")
    out_of_stock = _count(extraction, "outStock")
    unavailable = _count(extraction, "unavailable")
    return f"""
    <section class="info-card counts-card">
      <div class="card-label">أعداد المنتجات</div>
      <div class="counts-grid">
        <span class="total">الإجمالي <b>{total}</b></span>
        <span class="available">المتاح <b>{available}</b></span>
        <span class="out-of-stock">النافد <b>{out_of_stock}</b></span>
        <span class="unavailable">غير المتوفر <b>{unavailable}</b></span>
      </div>
    </section>
    """


def _product_row(
    product: ExtractedCartItem,
    image_value: object | None,
) -> tuple[str, bool]:
    image_uri = _image_data_uri(image_value)
    if image_uri:
        image_markup = (
            f'<img class="product-image" src="{html.escape(image_uri, quote=True)}" '
            'alt="صورة المنتج">'
        )
    else:
        image_markup = '<div class="missing-image">غير متوفر</div>'

    status_class = STATUS_CLASSES.get(product.availability, "unknown")
    status_label = STATUS_LABELS.get(product.availability, "غير معروف")
    return (
        f"""
        <tr>
          <td class="status {status_class}">{status_label}</td>
          <td class="image-cell">{image_markup}</td>
          <td class="product-name">{_escape(truncate_product_name(product.goods_name))}</td>
          <td class="sku" dir="ltr">{_escape(product.sku_code)}</td>
          <td class="attributes">{_escape(product.goods_attr)}</td>
          <td class="price" dir="ltr">{_escape(_product_price(product))}</td>
        </tr>
        """,
        image_uri is not None,
    )


def render_report_html(
    extraction: CartExtraction,
    images: Mapping[str, object],
    *,
    json_name: str,
) -> tuple[str, int]:
    analyzed_at = extraction.analyzed_at or datetime.now().astimezone()
    analyzed_text = analyzed_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    source_url = extraction.source_url
    escaped_url = html.escape(source_url)

    first_cards = "".join(
        [
            _info_card("اسم العميل", _escape(extraction.customer_name), "customer"),
            _info_card("رقم الطلبية", _escape(extraction.order_number), "order"),
            _info_card("معرف المجموعة", _escape(extraction.group_id), "group"),
            _info_card("السوق", _escape(extraction.local_country), "market"),
            _info_card("وقت التحليل", _escape(analyzed_text), "time"),
        ]
    )
    second_cards = "".join(
        [
            _info_card("ملف البيانات", _escape(json_name), "data-file"),
            _info_card(
                "رابط السلة",
                f'<a href="{html.escape(source_url, quote=True)}">{escaped_url}</a>',
                "cart-link",
            ),
            _counts_card(extraction),
        ]
    )

    rows: list[str] = []
    unavailable_images = 0
    for product in extraction.products:
        image_value = images.get(product.goods_img or "")
        row, image_available = _product_row(product, image_value)
        rows.append(row)
        unavailable_images += int(not image_available)

    document = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>تقرير استخراج منتجات سلة SHEIN</title>
  <style>
    @page {{
      size: A4 portrait;
      margin: 11mm 9mm 14mm;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: #172033;
      font-family: "Noto Sans Arabic", "Noto Sans", "DejaVu Sans", sans-serif;
      font-size: 8.4pt;
      direction: rtl;
    }}
    h1 {{
      margin: 0 0 5mm;
      text-align: center;
      font-size: 18pt;
      color: #111827;
    }}
    .cards-row {{
      display: flex;
      gap: 2mm;
      margin-bottom: 2mm;
      align-items: stretch;
    }}
    .cards-row.primary .info-card {{ width: 20%; }}
    .cards-row.secondary .data-file {{ width: 25%; }}
    .cards-row.secondary .cart-link {{ width: 45%; }}
    .cards-row.secondary .counts-card {{ width: 30%; }}
    .info-card {{
      min-height: 18mm;
      padding: 2.2mm;
      border: .25mm solid #cbd5e1;
      border-radius: 2mm;
      background: #f8fafc;
      text-align: center;
      overflow-wrap: anywhere;
    }}
    .card-label {{
      margin-bottom: 1.3mm;
      color: #475569;
      font-size: 7.4pt;
      font-weight: 700;
    }}
    .card-value {{ font-weight: 700; line-height: 1.55; }}
    .customer .card-value {{ color: #4338ca; }}
    .order .card-value {{ color: #c2410c; }}
    .group .card-value {{ color: #1d4ed8; }}
    .market .card-value {{ color: #0f766e; }}
    .time .card-value {{ color: #7e22ce; }}
    .data-file .card-value {{ color: #334155; font-size: 7.2pt; }}
    .cart-link .card-value {{ font-size: 6.3pt; font-weight: 600; direction: ltr; }}
    .cart-link a {{ color: #0369a1; text-decoration: underline; }}
    .counts-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1.2mm;
      font-size: 7.4pt;
    }}
    .counts-grid span {{ white-space: nowrap; }}
    .counts-grid b {{ margin-inline-start: 1mm; font-size: 9pt; }}
    .total {{ color: #2563eb; }}
    .available {{ color: #15803d; }}
    .out-of-stock {{ color: #b45309; }}
    .unavailable {{ color: #dc2626; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      direction: rtl;
      margin-top: 4mm;
    }}
    thead {{ display: table-header-group; }}
    tr {{ break-inside: avoid; page-break-inside: avoid; }}
    th {{
      padding: 2.2mm 1.2mm;
      border: .25mm solid #334155;
      background: #172033;
      color: #ffffff;
      font-size: 7.5pt;
      text-align: center;
    }}
    td {{
      min-height: 24mm;
      padding: 1.4mm;
      border: .25mm solid #cbd5e1;
      text-align: center;
      vertical-align: middle;
      line-height: 1.55;
      overflow-wrap: break-word;
    }}
    tbody tr:nth-child(even) {{ background: #f8fafc; }}
    th.status, td.status {{ width: 9%; }}
    th.image-cell, td.image-cell {{ width: 14%; }}
    th.product-name, td.product-name {{ width: 31%; }}
    th.sku, td.sku {{ width: 19%; }}
    th.attributes, td.attributes {{ width: 18%; }}
    th.price, td.price {{ width: 9%; }}
    .product-image {{
      width: 22mm;
      height: 22mm;
      object-fit: contain;
      display: block;
      margin: auto;
    }}
    .missing-image {{
      width: 22mm;
      height: 22mm;
      margin: auto;
      border: .25mm dashed #94a3b8;
      background: #f1f5f9;
      color: #64748b;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 7pt;
    }}
    td.product-name {{ color: #111827; font-weight: 600; }}
    td.sku {{
      color: #1e3a8a;
      font-family: "DejaVu Sans Mono", monospace;
      font-size: 6.8pt;
      white-space: nowrap;
    }}
    td.attributes {{ color: #475569; }}
    td.price {{ color: #166534; font-weight: 700; white-space: nowrap; }}
    td.status {{ font-weight: 700; }}
    td.status.available {{ color: #15803d; }}
    td.status.out-of-stock {{ color: #b45309; }}
    td.status.unavailable {{ color: #dc2626; }}
    td.status.unknown {{ color: #64748b; }}
    .notice {{
      margin-top: 3mm;
      color: #64748b;
      text-align: center;
      font-size: 7pt;
    }}
  </style>
</head>
<body>
  <h1>تقرير استخراج منتجات سلة SHEIN</h1>
  <div class="cards-row primary">{first_cards}</div>
  <div class="cards-row secondary">{second_cards}</div>
  <table>
    <thead>
      <tr>
        <th class="status">الحالة</th>
        <th class="image-cell">الصورة</th>
        <th class="product-name">اسم المنتج</th>
        <th class="sku">SKU</th>
        <th class="attributes">الخصائص / المقاس</th>
        <th class="price">السعر</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
  <div class="notice">التوفر والسعر يعكسان حالة المنتجات وقت التحليل.</div>
</body>
</html>
"""
    return document, unavailable_images


class PlaywrightPdfReportExporter:
    def export(
        self,
        extraction: CartExtraction,
        output_path: Path,
        images: Mapping[str, object],
        *,
        json_name: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ReportExportResult:
        if not extraction.products:
            raise RuntimeError("لا توجد منتجات لتصديرها.")
        from playwright.sync_api import sync_playwright

        document, unavailable_images = render_report_html(
            extraction,
            images,
            json_name=json_name,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_suffix(".tmp.pdf")
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.set_content(document, wait_until="load")
                    page.emulate_media(media="print")
                    page.pdf(
                        path=str(temporary_path),
                        format="A4",
                        print_background=True,
                        prefer_css_page_size=True,
                        display_header_footer=True,
                        header_template="<span></span>",
                        footer_template=(
                            '<div style="width:100%;font-size:8px;color:#64748b;'
                            'text-align:center;font-family:Arial,sans-serif;">'
                            'صفحة <span class="pageNumber"></span> من '
                            '<span class="totalPages"></span></div>'
                        ),
                        margin={
                            "top": "11mm",
                            "right": "9mm",
                            "bottom": "14mm",
                            "left": "9mm",
                        },
                    )
                finally:
                    browser.close()
            page_count = len(PdfReader(temporary_path).pages)
            temporary_path.replace(output_path)
        finally:
            temporary_path.unlink(missing_ok=True)

        if progress_callback is not None:
            for page_number in range(1, page_count + 1):
                progress_callback(page_number, page_count)

        return ReportExportResult(
            path=output_path,
            page_count=page_count,
            unavailable_image_count=unavailable_images,
        )
