from __future__ import annotations

from base64 import b64encode
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QBuffer, QIODevice, QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPixmap,
    QTextDocument,
)

from models import AvailabilityStatus, CartExtraction, ExtractedCartItem


PDF_ROWS_FIRST_PAGE = 4
PDF_ROWS_OTHER_PAGES = 5

STATUS_LABELS = {
    AvailabilityStatus.AVAILABLE: "متاح",
    AvailabilityStatus.OUT_OF_STOCK: "نافد",
    AvailabilityStatus.UNAVAILABLE: "غير متوفر",
    AvailabilityStatus.UNKNOWN: "غير معروف",
}

STATUS_COLORS = {
    AvailabilityStatus.AVAILABLE: "#15803d",
    AvailabilityStatus.OUT_OF_STOCK: "#b45309",
    AvailabilityStatus.UNAVAILABLE: "#dc2626",
    AvailabilityStatus.UNKNOWN: "#64748b",
}


def truncate_product_name(value: str | None, limit: int = 100) -> str:
    name = (value or "—").strip()
    if len(name) <= limit:
        return name
    return f"{name[:limit].rstrip()}…"


def default_pdf_path(json_path: Path, export_directory: Path) -> Path:
    return export_directory / f"{json_path.stem}.pdf"


def _pixmap_data_uri(pixmap: QPixmap) -> str:
    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("تعذر تجهيز صورة المنتج للتقرير.")
    if not pixmap.save(buffer, "PNG"):
        raise RuntimeError("تعذر تحويل صورة المنتج إلى صيغة PDF.")
    return f"data:image/png;base64,{b64encode(bytes(buffer.data())).decode('ascii')}"


def _product_row(product: ExtractedCartItem, image: QPixmap) -> str:
    status = STATUS_LABELS[product.availability]
    status_color = STATUS_COLORS[product.availability]
    name = truncate_product_name(product.goods_name)
    image_uri = _pixmap_data_uri(image)
    return f"""
      <tr>
        <td class="status" style="color:{status_color}">{escape(status)}</td>
        <td class="image"><img src="{image_uri}" width="76" height="76"></td>
        <td class="name">{escape(name)}</td>
        <td class="latin">{escape(product.sku_code or '—')}</td>
        <td>{escape(product.goods_attr or '—')}</td>
        <td class="latin price">{escape(product.amountWithSymbol or '—')}</td>
      </tr>
    """


def _summary_html(extraction: CartExtraction) -> str:
    return f"""
      <table class="summary">
        <tr>
          <td><span>إجمالي المنتجات</span><strong class="total">{len(extraction.products)}</strong></td>
          <td><span>المتاحة</span><strong class="available">{extraction.counts.get('normalProducts', 0)}</strong></td>
          <td><span>النافدة</span><strong class="out">{extraction.counts.get('outStock', 0)}</strong></td>
          <td><span>غير المتوفرة</span><strong class="unavailable">{extraction.counts.get('unavailable', 0)}</strong></td>
        </tr>
      </table>
    """


def _metadata_html(extraction: CartExtraction, json_name: str) -> str:
    analyzed_at = extraction.analyzed_at or datetime.now().astimezone()
    source_url = escape(extraction.source_url, quote=True)
    return f"""
      <div class="metadata">
        <div><b>اسم العميل:</b> {escape(extraction.customer_name or 'غير محدد')}</div>
        <div><b>رقم الطلبية:</b> {escape(extraction.order_number or 'غير محدد')}</div>
        <div><b>معرّف المجموعة:</b> {escape(extraction.group_id or 'غير محدد')}</div>
        <div><b>السوق:</b> {escape(extraction.local_country or 'غير محدد')}</div>
        <div><b>وقت التحليل:</b> <span class="latin">{analyzed_at.strftime('%Y-%m-%d %H:%M:%S')}</span></div>
        <div><b>ملف البيانات:</b> <span class="latin">{escape(json_name)}</span></div>
        <div class="url"><b>رابط السلة:</b> <a href="{source_url}">{source_url}</a></div>
      </div>
    """


def _table_html(
    products: list[ExtractedCartItem], image_pixmaps: dict[str, QPixmap]
) -> str:
    rows = []
    for product in products:
        image_url = product.goods_img or ""
        image = image_pixmaps.get(image_url)
        if image is None or image.isNull():
            raise RuntimeError("لا يمكن تصدير التقرير قبل اكتمال جميع صور المنتجات.")
        rows.append(_product_row(product, image))
    return f"""
      <table class="products">
        <thead>
          <tr>
            <th class="status">الحالة</th>
            <th class="image">الصورة</th>
            <th class="name">اسم المنتج</th>
            <th class="sku">SKU</th>
            <th class="attrs">الخصائص / المقاس</th>
            <th class="price">السعر</th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    """


def _page_html(
    extraction: CartExtraction,
    products: list[ExtractedCartItem],
    image_pixmaps: dict[str, QPixmap],
    json_name: str,
    *,
    first_page: bool,
) -> str:
    details = ""
    if first_page:
        details = _metadata_html(extraction, json_name) + _summary_html(extraction)
    else:
        details = '<div class="continued">متابعة جدول المنتجات</div>'
    return f"""
    <!doctype html>
    <html dir="rtl" lang="ar">
      <head>
        <meta charset="utf-8">
        <style>
          body {{ font-family: "Noto Sans Arabic", "Segoe UI", sans-serif; color:#172033; direction:rtl; }}
          h1 {{ margin:0 0 8px; font-size:21px; color:#0f172a; text-align:center; }}
          .metadata {{ border:1px solid #cbd5e1; background:#f8fafc; padding:8px 10px; font-size:9px; line-height:1.45; }}
          .metadata div {{ display:inline-block; width:31%; margin:1px 0; }}
          .metadata .url {{ display:block; width:100%; direction:rtl; }}
          .metadata a {{ color:#0369a1; text-decoration:none; }}
          .latin {{ direction:ltr; unicode-bidi:embed; }}
          .summary {{ width:100%; border-collapse:separate; border-spacing:6px; margin:7px 0; }}
          .summary td {{ border:1px solid #cbd5e1; background:#f8fafc; text-align:center; padding:4px; }}
          .summary span {{ display:block; color:#64748b; font-size:8px; }}
          .summary strong {{ display:block; font-size:15px; }}
          .total {{ color:#2563eb; }} .available {{ color:#15803d; }}
          .out {{ color:#b45309; }} .unavailable {{ color:#dc2626; }}
          .continued {{ text-align:center; color:#475569; font-size:10px; margin:0 0 7px; }}
          .products {{ width:125%; border-collapse:collapse; table-layout:fixed; font-size:8.5px; }}
          .products th {{ background:#172033; color:#fff; border:1px solid #334155; padding:6px 3px; text-align:center; }}
          .products td {{ border:1px solid #cbd5e1; padding:5px; text-align:center; vertical-align:middle; height:80px; }}
          .products tr:nth-child(even) td {{ background:#f8fafc; }}
          .products .status {{ width:8%; font-weight:700; }}
          .products .image {{ width:11%; }}
          .products .name {{ width:31%; }}
          .products .sku {{ width:18%; }}
          .products .attrs {{ width:22%; }}
          .products .price {{ width:10%; }}
          .products img {{ object-fit:contain; }}
        </style>
      </head>
      <body>
        <h1>تقرير استخراج منتجات سلة SHEIN</h1>
        {details}
        {_table_html(products, image_pixmaps)}
      </body>
    </html>
    """


def _product_pages(products: list[ExtractedCartItem]) -> list[list[ExtractedCartItem]]:
    pages = [products[:PDF_ROWS_FIRST_PAGE]]
    offset = PDF_ROWS_FIRST_PAGE
    while offset < len(products):
        pages.append(products[offset : offset + PDF_ROWS_OTHER_PAGES])
        offset += PDF_ROWS_OTHER_PAGES
    return pages


def export_cart_pdf(
    extraction: CartExtraction,
    output_path: Path,
    image_pixmaps: dict[str, QPixmap],
    *,
    json_name: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> int:
    if not extraction.products:
        raise RuntimeError("لا توجد منتجات لتصديرها.")

    missing_images = [
        product.goods_img
        for product in extraction.products
        if not product.goods_img
        or product.goods_img not in image_pixmaps
        or image_pixmaps[product.goods_img].isNull()
    ]
    if missing_images:
        raise RuntimeError("لا يمكن تصدير التقرير قبل اكتمال جميع صور المنتجات.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = QPdfWriter(str(output_path))
    writer.setTitle("تقرير استخراج منتجات سلة SHEIN")
    writer.setCreator("SHEIN Cart Products")
    writer.setResolution(96)
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Landscape,
            QMarginsF(10, 10, 10, 12),
            QPageLayout.Unit.Millimeter,
        )
    )

    painter = QPainter(writer)
    if not painter.isActive():
        raise RuntimeError("تعذر بدء إنشاء ملف PDF.")

    pages = _product_pages(extraction.products)
    page_width = float(writer.width())
    page_height = float(writer.height())
    footer_height = 22.0
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

    try:
        for index, products in enumerate(pages):
            if index:
                writer.newPage()
            document = QTextDocument()
            document.setDefaultFont(QFont("Noto Sans Arabic", 9))
            document.setPageSize(QSizeF(page_width, page_height - footer_height))
            document.setHtml(
                _page_html(
                    extraction,
                    products,
                    image_pixmaps,
                    json_name,
                    first_page=index == 0,
                )
            )
            document.drawContents(
                painter,
                QRectF(0, 0, page_width, page_height - footer_height),
            )

            painter.save()
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor("#64748b"))
            painter.drawText(
                QRectF(0, page_height - footer_height, page_width, footer_height),
                int(Qt.AlignmentFlag.AlignCenter),
                f"صفحة {index + 1} من {len(pages)}  |  تاريخ الإنشاء: {generated_at}",
            )
            painter.restore()
            if progress_callback is not None:
                progress_callback(index + 1, len(pages))
    finally:
        painter.end()

    return len(pages)
