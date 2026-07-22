from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
    QPixmap,
)
from pypdf import PdfReader, PdfWriter

from models import AvailabilityStatus, CartExtraction, ExtractedCartItem


STATUS_LABELS = {
    AvailabilityStatus.AVAILABLE: "متاح",
    AvailabilityStatus.OUT_OF_STOCK: "نافد",
    AvailabilityStatus.UNAVAILABLE: "غير متوفر",
    AvailabilityStatus.UNKNOWN: "غير معروف",
}

STATUS_COLORS = {
    AvailabilityStatus.AVAILABLE: QColor("#15803d"),
    AvailabilityStatus.OUT_OF_STOCK: QColor("#b45309"),
    AvailabilityStatus.UNAVAILABLE: QColor("#dc2626"),
    AvailabilityStatus.UNKNOWN: QColor("#64748b"),
}

PAGE_BACKGROUND = QColor("#ffffff")
HEADER_BACKGROUND = QColor("#172033")
CARD_BACKGROUND = QColor("#f8fafc")
ALT_ROW_BACKGROUND = QColor("#f8fafc")
BORDER_COLOR = QColor("#cbd5e1")
TEXT_COLOR = QColor("#172033")
MUTED_COLOR = QColor("#64748b")
ACCENT_COLOR = QColor("#2563eb")
PRODUCT_NAME_COLOR = QColor("#111827")
SKU_COLOR = QColor("#1e3a8a")
PRICE_COLOR = QColor("#166534")
ATTRIBUTE_COLOR = QColor("#475569")
CUSTOMER_COLOR = QColor("#4338ca")
ORDER_COLOR = QColor("#c2410c")
GROUP_COLOR = QColor("#1d4ed8")
MARKET_COLOR = QColor("#0f766e")
TIME_COLOR = QColor("#7e22ce")


@dataclass(frozen=True)
class PdfExportResult:
    page_count: int
    unavailable_image_count: int


@dataclass(frozen=True)
class ProductRowLayout:
    product: ExtractedCartItem
    height: float


@dataclass(frozen=True)
class ReportHeaderLayout:
    bottom: float
    link_rect: QRectF


def truncate_product_name(value: str | None, limit: int = 100) -> str:
    name = (value or "—").strip()
    if len(name) <= limit:
        return name
    return f"{name[:limit].rstrip()}…"


def default_pdf_path(json_path: Path, export_directory: Path) -> Path:
    return export_directory / f"{json_path.stem}.pdf"


def _font(size: float, *, bold: bool = False) -> QFont:
    font = QFont("Noto Sans Arabic")
    if not QFontMetricsF(font).height():
        font = QFont("Segoe UI")
    font.setPointSizeF(size)
    font.setBold(bold)
    return font


def _wrapped_height(text: str, width: float, font: QFont) -> float:
    metrics = QFontMetricsF(font)
    bounds = metrics.boundingRect(
        QRectF(0, 0, max(width, 1), 10000),
        int(
            int(Qt.AlignmentFlag.AlignCenter)
            | int(Qt.TextFlag.TextWordWrap)
            | int(Qt.TextFlag.TextDontClip)
        ),
        text,
    )
    return max(bounds.height(), metrics.height())


def _fit_single_line_font(text: str, width: float, start: float = 9.0) -> QFont:
    size = start
    while size > 6.5:
        font = _font(size)
        if QFontMetricsF(font).horizontalAdvance(text) <= width:
            return font
        size -= 0.25
    return _font(6.5)


def _breakable_filename(value: str, chunk_size: int = 16) -> str:
    chunks = [value[index : index + chunk_size] for index in range(0, len(value), chunk_size)]
    return "\u200b".join(chunks)


def _breakable_url(value: str) -> str:
    break_after = "/?&=-_"
    return "".join(f"{character}\u200b" if character in break_after else character for character in value)


def _fit_wrapped_font(
    text: str,
    width: float,
    height: float,
    *,
    start: float,
    minimum: float,
) -> QFont:
    size = start
    while size > minimum:
        font = _font(size, bold=True)
        if _wrapped_height(text, width, font) <= height:
            return font
        size -= 0.25
    return _font(minimum, bold=True)


def _draw_wrapped_text(
    painter: QPainter,
    rect: QRectF,
    text: str,
    font: QFont,
    color: QColor = TEXT_COLOR,
    *,
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
    left_to_right: bool = False,
) -> None:
    painter.save()
    if left_to_right:
        painter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(
        rect,
        int(alignment) | int(Qt.TextFlag.TextWordWrap),
        text,
    )
    painter.restore()


def _draw_card(
    painter: QPainter,
    rect: QRectF,
    label: str,
    value: str,
    *,
    value_color: QColor = TEXT_COLOR,
    value_size: float = 8.5,
    left_to_right: bool = False,
    value_font: QFont | None = None,
) -> None:
    painter.save()
    painter.setPen(QPen(BORDER_COLOR, 1))
    painter.setBrush(CARD_BACKGROUND)
    painter.drawRoundedRect(rect, 8, 8)
    painter.restore()

    padding = 8.0
    label_height = 20.0
    _draw_wrapped_text(
        painter,
        QRectF(rect.x() + padding, rect.y() + 4, rect.width() - padding * 2, label_height),
        label,
        _font(7.5, bold=True),
        MUTED_COLOR,
    )
    _draw_wrapped_text(
        painter,
        QRectF(
            rect.x() + padding,
            rect.y() + label_height + 2,
            rect.width() - padding * 2,
            rect.height() - label_height - 8,
        ),
        value,
        value_font or _font(value_size, bold=True),
        value_color,
        left_to_right=left_to_right,
    )


def _rtl_card_rects(
    page_width: float,
    y: float,
    height: float,
    ratios: list[float],
    gap: float,
) -> list[QRectF]:
    usable_width = page_width - gap * (len(ratios) - 1)
    rects: list[QRectF] = []
    right = page_width
    for ratio in ratios:
        width = usable_width * ratio
        rect = QRectF(right - width, y, width, height)
        rects.append(rect)
        right = rect.x() - gap
    return rects


def _draw_count_item(
    painter: QPainter,
    rect: QRectF,
    label: str,
    value: int,
    color: QColor,
) -> None:
    _draw_wrapped_text(
        painter,
        rect,
        f"{label}  {value}",
        _font(8.2, bold=True),
        color,
    )


def _draw_counts_card(
    painter: QPainter,
    rect: QRectF,
    extraction: CartExtraction,
) -> None:
    painter.save()
    painter.setPen(QPen(BORDER_COLOR, 1))
    painter.setBrush(CARD_BACKGROUND)
    painter.drawRoundedRect(rect, 8, 8)
    painter.restore()

    padding = 8.0
    label_height = 20.0
    _draw_wrapped_text(
        painter,
        QRectF(rect.x() + padding, rect.y() + 4, rect.width() - padding * 2, label_height),
        "أعداد المنتجات",
        _font(7.5, bold=True),
        MUTED_COLOR,
    )

    content = QRectF(
        rect.x() + padding,
        rect.y() + label_height + 2,
        rect.width() - padding * 2,
        rect.height() - label_height - 8,
    )
    half_width = content.width() / 2
    half_height = content.height() / 2
    counts = extraction.counts
    items = [
        ("الإجمالي", len(extraction.products), ACCENT_COLOR),
        ("المتاح", counts.get("normalProducts", 0), STATUS_COLORS[AvailabilityStatus.AVAILABLE]),
        ("النافد", counts.get("outStock", 0), STATUS_COLORS[AvailabilityStatus.OUT_OF_STOCK]),
        ("غير المتوفر", counts.get("unavailable", 0), STATUS_COLORS[AvailabilityStatus.UNAVAILABLE]),
    ]
    item_rects = [
        QRectF(content.right() - half_width, content.y(), half_width, half_height),
        QRectF(content.x(), content.y(), half_width, half_height),
        QRectF(content.right() - half_width, content.y() + half_height, half_width, half_height),
        QRectF(content.x(), content.y() + half_height, half_width, half_height),
    ]
    for item_rect, (label, value, color) in zip(item_rects, items, strict=True):
        _draw_count_item(painter, item_rect, label, value, color)


def _draw_report_header(
    painter: QPainter,
    extraction: CartExtraction,
    json_name: str,
    page_width: float,
) -> ReportHeaderLayout:
    title_height = 55.0
    _draw_wrapped_text(
        painter,
        QRectF(0, 0, page_width, title_height),
        "تقرير استخراج منتجات سلة SHEIN",
        _font(18, bold=True),
    )

    gap = 7.0
    first_row_height = 68.0
    analyzed_at = extraction.analyzed_at or datetime.now().astimezone()
    first_row = [
        ("اسم العميل", extraction.customer_name or "غير محدد", CUSTOMER_COLOR, False),
        ("رقم الطلبية", extraction.order_number or "غير محدد", ORDER_COLOR, True),
        ("معرّف المجموعة", extraction.group_id or "غير محدد", GROUP_COLOR, True),
        ("السوق", extraction.local_country or "غير محدد", MARKET_COLOR, True),
        ("وقت التحليل", analyzed_at.strftime("%Y-%m-%d\n%H:%M:%S"), TIME_COLOR, True),
    ]
    y = title_height
    first_rects = _rtl_card_rects(
        page_width,
        y,
        first_row_height,
        [0.24, 0.18, 0.20, 0.12, 0.26],
        gap,
    )
    for rect, (label, value, color, left_to_right) in zip(first_rects, first_row, strict=True):
        _draw_card(
            painter,
            rect,
            label,
            value,
            value_color=color,
            left_to_right=left_to_right,
        )

    y += first_row_height + gap
    second_row_height = 94.0
    filename = _breakable_filename(json_name)
    url = _breakable_url(extraction.source_url)
    second_rects = _rtl_card_rects(
        page_width,
        y,
        second_row_height,
        [0.28, 0.47, 0.25],
        gap,
    )
    _draw_card(
        painter,
        second_rects[0],
        "ملف البيانات",
        filename,
        value_color=TEXT_COLOR,
        value_font=_fit_wrapped_font(
            filename,
            second_rects[0].width() - 16,
            second_row_height - 30,
            start=7.8,
            minimum=6.0,
        ),
        left_to_right=True,
    )
    _draw_card(
        painter,
        second_rects[1],
        "رابط السلة",
        url,
        value_color=ACCENT_COLOR,
        value_font=_fit_wrapped_font(
            url,
            second_rects[1].width() - 16,
            second_row_height - 30,
            start=7.0,
            minimum=5.25,
        ),
        left_to_right=True,
    )
    _draw_counts_card(painter, second_rects[2], extraction)

    return ReportHeaderLayout(y + second_row_height + 12, second_rects[1])


def _draw_compact_header(painter: QPainter, page_width: float) -> float:
    _draw_wrapped_text(
        painter,
        QRectF(0, 0, page_width, 48),
        "تقرير استخراج منتجات سلة SHEIN — متابعة المنتجات",
        _font(13, bold=True),
    )
    return 53.0


def _column_layout(page_width: float) -> list[tuple[str, float, float]]:
    columns = [
        ("السعر", 0.09),
        ("الخصائص / المقاس", 0.21),
        ("SKU", 0.18),
        ("اسم المنتج", 0.29),
        ("الصورة", 0.14),
        ("الحالة", 0.09),
    ]
    result: list[tuple[str, float, float]] = []
    x = 0.0
    for title, ratio in columns:
        width = page_width * ratio
        result.append((title, x, width))
        x += width
    return result


def _draw_table_header(painter: QPainter, y: float, page_width: float) -> float:
    height = 42.0
    painter.save()
    painter.setBrush(HEADER_BACKGROUND)
    painter.setPen(QPen(QColor("#334155"), 1))
    for title, x, width in _column_layout(page_width):
        rect = QRectF(x, y, width, height)
        painter.drawRect(rect)
        _draw_wrapped_text(
            painter,
            rect.adjusted(4, 3, -4, -3),
            title,
            _font(8.3, bold=True),
            QColor("#ffffff"),
        )
    painter.restore()
    return y + height


def _row_height(product: ExtractedCartItem, page_width: float) -> float:
    columns = _column_layout(page_width)
    widths = {title: width for title, _, width in columns}
    name_height = _wrapped_height(
        truncate_product_name(product.goods_name),
        widths["اسم المنتج"] - 14,
        _font(8.2),
    )
    attr_height = _wrapped_height(
        product.goods_attr or "—",
        widths["الخصائص / المقاس"] - 14,
        _font(8.0),
    )
    return max(122.0, name_height + 18, attr_height + 18)


def _paginate(
    products: list[ExtractedCartItem],
    page_width: float,
    page_height: float,
    first_table_y: float,
    continuation_table_y: float,
    footer_height: float,
) -> list[list[ProductRowLayout]]:
    pages: list[list[ProductRowLayout]] = [[]]
    y = first_table_y
    bottom = page_height - footer_height
    for product in products:
        layout = ProductRowLayout(product, _row_height(product, page_width))
        if pages[-1] and y + layout.height > bottom:
            pages.append([])
            y = continuation_table_y
        pages[-1].append(layout)
        y += layout.height
    if len(pages) > 1 and len(pages[-1]) < 3:
        previous_page = pages[-2]
        last_page = pages[-1]
        while len(last_page) < 3 and len(previous_page) > 3:
            last_page.insert(0, previous_page.pop())
    return pages


def _draw_product_image(
    painter: QPainter,
    rect: QRectF,
    product: ExtractedCartItem,
    image_pixmaps: dict[str, QPixmap],
) -> bool:
    image = image_pixmaps.get(product.goods_img or "")
    inner = rect.adjusted(8, 8, -8, -8)
    if image is None or image.isNull():
        painter.save()
        painter.setBrush(QColor("#f1f5f9"))
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.drawRoundedRect(inner, 5, 5)
        painter.restore()
        _draw_wrapped_text(
            painter,
            inner.adjusted(5, 5, -5, -5),
            "الصورة\nغير متوفرة",
            _font(7.2, bold=True),
            QColor("#dc2626"),
        )
        return False

    scaled = image.scaled(
        int(inner.width()),
        int(inner.height()),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = inner.x() + (inner.width() - scaled.width()) / 2
    y = inner.y() + (inner.height() - scaled.height()) / 2
    painter.drawPixmap(int(x), int(y), scaled)
    return True


def _draw_product_row(
    painter: QPainter,
    y: float,
    row: ProductRowLayout,
    page_width: float,
    image_pixmaps: dict[str, QPixmap],
    *,
    alternate: bool,
) -> bool:
    product = row.product
    columns = _column_layout(page_width)
    painter.save()
    painter.setPen(QPen(BORDER_COLOR, 1))
    painter.setBrush(ALT_ROW_BACKGROUND if alternate else PAGE_BACKGROUND)
    for _, x, width in columns:
        painter.drawRect(QRectF(x, y, width, row.height))
    painter.restore()

    rects = {
        title: QRectF(x, y, width, row.height) for title, x, width in columns
    }
    _draw_wrapped_text(
        painter,
        rects["السعر"].adjusted(5, 5, -5, -5),
        product.amountWithSymbol or "—",
        _fit_single_line_font(product.amountWithSymbol or "—", rects["السعر"].width() - 10),
        PRICE_COLOR,
    )
    _draw_wrapped_text(
        painter,
        rects["الخصائص / المقاس"].adjusted(7, 6, -7, -6),
        product.goods_attr or "—",
        _font(8.0),
        ATTRIBUTE_COLOR,
    )

    sku = product.sku_code or "—"
    painter.save()
    painter.setFont(_fit_single_line_font(sku, rects["SKU"].width() - 12))
    painter.setPen(SKU_COLOR)
    painter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    painter.drawText(
        rects["SKU"].adjusted(6, 5, -6, -5),
        int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextSingleLine),
        sku,
    )
    painter.restore()

    _draw_wrapped_text(
        painter,
        rects["اسم المنتج"].adjusted(7, 6, -7, -6),
        truncate_product_name(product.goods_name),
        _font(8.2),
        PRODUCT_NAME_COLOR,
    )
    image_available = _draw_product_image(
        painter,
        rects["الصورة"],
        product,
        image_pixmaps,
    )
    _draw_wrapped_text(
        painter,
        rects["الحالة"].adjusted(5, 5, -5, -5),
        STATUS_LABELS[product.availability],
        _font(8.0, bold=True),
        STATUS_COLORS[product.availability],
    )
    return image_available


def _draw_footer(
    painter: QPainter,
    page_width: float,
    page_height: float,
    page_number: int,
    page_count: int,
    generated_at: str,
) -> None:
    _draw_wrapped_text(
        painter,
        QRectF(0, page_height - 30, page_width, 24),
        f"صفحة {page_number} من {page_count}  |  تاريخ الإنشاء: {generated_at}",
        _font(7.3),
        MUTED_COLOR,
    )


def _add_clickable_url(
    output_path: Path,
    url: str,
    rect: QRectF,
    page_width: float,
    page_height: float,
) -> None:
    temporary_path = output_path.with_suffix(".linked.pdf")
    with output_path.open("rb") as source:
        reader = PdfReader(source)
        page = reader.pages[0]
        pdf_width = float(page.mediabox.width)
        pdf_height = float(page.mediabox.height)
        link_rect = [
            rect.left() / page_width * pdf_width,
            pdf_height - rect.bottom() / page_height * pdf_height,
            rect.right() / page_width * pdf_width,
            pdf_height - rect.top() / page_height * pdf_height,
        ]
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        writer.add_uri(0, url, link_rect, border=[0, 0, 0])
        with temporary_path.open("wb") as destination:
            writer.write(destination)
    temporary_path.replace(output_path)


def export_cart_pdf(
    extraction: CartExtraction,
    output_path: Path,
    image_pixmaps: dict[str, QPixmap],
    *,
    json_name: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> PdfExportResult:
    if not extraction.products:
        raise RuntimeError("لا توجد منتجات لتصديرها.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = QPdfWriter(str(output_path))
    writer.setTitle("تقرير استخراج منتجات سلة SHEIN")
    writer.setCreator("SHEIN Cart Products")
    writer.setResolution(150)
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(8, 8, 8, 10),
            QPageLayout.Unit.Millimeter,
        )
    )

    painter = QPainter(writer)
    if not painter.isActive():
        raise RuntimeError("تعذر بدء إنشاء ملف PDF.")

    page_width = float(writer.width())
    page_height = float(writer.height())
    footer_height = 38.0
    header_layout = _draw_report_header(
        painter,
        extraction,
        json_name,
        page_width,
    )
    first_header_bottom = header_layout.bottom
    first_table_y = first_header_bottom + 42.0
    continuation_table_y = 53.0 + 42.0
    pages = _paginate(
        extraction.products,
        page_width,
        page_height,
        first_table_y,
        continuation_table_y,
        footer_height,
    )
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    unavailable_images = 0

    try:
        for page_index, rows in enumerate(pages):
            if page_index:
                writer.newPage()
                painter.fillRect(QRectF(0, 0, page_width, page_height), PAGE_BACKGROUND)
                table_y = _draw_compact_header(painter, page_width)
            else:
                table_y = first_header_bottom
            y = _draw_table_header(painter, table_y, page_width)
            for row_index, row in enumerate(rows):
                image_available = _draw_product_row(
                    painter,
                    y,
                    row,
                    page_width,
                    image_pixmaps,
                    alternate=row_index % 2 == 1,
                )
                unavailable_images += int(not image_available)
                y += row.height
            _draw_footer(
                painter,
                page_width,
                page_height,
                page_index + 1,
                len(pages),
                generated_at,
            )
            if progress_callback is not None:
                progress_callback(page_index + 1, len(pages))
    finally:
        painter.end()

    _add_clickable_url(
        output_path,
        extraction.source_url,
        header_layout.link_rect,
        page_width,
        page_height,
    )

    return PdfExportResult(len(pages), unavailable_images)
