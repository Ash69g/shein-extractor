from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import sys
import unicodedata
import weakref

from PySide6.QtCore import QObject, QSettings, QSize, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from diagnose_link import validate_shein_url
from extract_cart import (
    CartExtractionError,
    extract_cart,
    sanitize_filename_component,
    write_output,
)
from invoice_parser import InvoiceData, parse_invoice_text
from models import AvailabilityStatus, CartExtraction, ExtractedCartItem
from pdf_export import default_pdf_path, export_cart_pdf, truncate_product_name


OUTPUT_DIRECTORY = Path("outputs")
EXPORT_DIRECTORY = Path("exports")
ASSET_DIRECTORY = Path(__file__).resolve().parent / "assets"
TIMESTAMP_PATTERN = re.compile(r"(\d{8}-\d{6})(?:-\d+)?$")
THUMBNAIL_SIZE = 120
ROW_HEIGHT = 133

STATUS_LABELS = {
    AvailabilityStatus.AVAILABLE: "متاح",
    AvailabilityStatus.OUT_OF_STOCK: "نافد",
    AvailabilityStatus.UNAVAILABLE: "غير متوفر",
    AvailabilityStatus.UNKNOWN: "غير معروف",
}

STATUS_COLORS = {
    AvailabilityStatus.AVAILABLE: "#22c55e",
    AvailabilityStatus.OUT_OF_STOCK: "#f59e0b",
    AvailabilityStatus.UNAVAILABLE: "#ef4444",
    AvailabilityStatus.UNKNOWN: "#94a3b8",
}

ARABIC_DIACRITICS_PATTERN = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")


def normalize_product_search(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = ARABIC_DIACRITICS_PATTERN.sub("", normalized).replace("ـ", "")
    return " ".join(normalized.split())


def product_matches_query(product: ExtractedCartItem, query: str) -> bool:
    normalized_query = normalize_product_search(query)
    if not normalized_query:
        return True
    searchable_values = (
        product.goods_name,
        product.sku_code,
        product.goods_attr,
        STATUS_LABELS[product.availability],
        product.amountWithSymbol,
    )
    return any(
        normalized_query in normalize_product_search(value)
        for value in searchable_values
    )


@dataclass(frozen=True)
class HistoryEntry:
    path: Path
    extraction: CartExtraction | None
    customer_name: str
    analyzed_at: datetime
    order_number: str | None = None
    error: str | None = None

    @property
    def sort_key(self) -> float:
        return self.analyzed_at.timestamp()


def timestamp_from_filename(path: Path) -> datetime | None:
    match = TIMESTAMP_PATTERN.search(path.stem)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S").astimezone()
    except ValueError:
        return None


def customer_from_filename(path: Path) -> str | None:
    match = TIMESTAMP_PATTERN.search(path.stem)
    if not match:
        return None
    prefix = path.stem[: match.start()].rstrip("-")
    if not prefix or prefix.startswith("cart-"):
        return None
    return prefix


def history_entry_from_path(path: Path) -> HistoryEntry:
    fallback_time = (
        timestamp_from_filename(path)
        or datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    )
    try:
        extraction = CartExtraction.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except Exception as error:
        return HistoryEntry(
            path=path,
            extraction=None,
            customer_name="ملف غير صالح",
            analyzed_at=fallback_time,
            error=str(error),
        )
    analyzed_at = extraction.analyzed_at or fallback_time
    if analyzed_at.tzinfo is None:
        analyzed_at = analyzed_at.astimezone()
    customer_name = (
        extraction.customer_name or customer_from_filename(path) or "غير محدد"
    )
    return HistoryEntry(
        path,
        extraction,
        customer_name,
        analyzed_at,
        extraction.order_number,
    )


def rename_history_path(
    path: Path,
    customer_name: str,
    order_number: str | None = None,
) -> Path:
    timestamp = timestamp_from_filename(path)
    if timestamp is None:
        timestamp = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    safe_name = sanitize_filename_component(customer_name)
    safe_order_number = (
        sanitize_filename_component(order_number) if order_number else None
    )
    identity = f"{safe_order_number}-{safe_name}" if safe_order_number else safe_name
    target = path.with_name(f"{identity}-{timestamp.strftime('%Y%m%d-%H%M%S')}.json")
    if target == path:
        return path
    if target.exists():
        raise FileExistsError(f"يوجد ملف بالاسم نفسه: {target.name}")
    path.rename(target)
    return target


class ExtractionWorker(QObject):
    succeeded = Signal(object, str)
    failed = Signal(str)

    def __init__(
        self,
        url: str,
        customer_name: str,
        order_number: str | None,
        analyzed_at: datetime,
    ) -> None:
        super().__init__()
        self.url = url
        self.customer_name = customer_name
        self.order_number = order_number
        self.analyzed_at = analyzed_at

    @Slot()
    def run(self) -> None:
        try:
            extraction = extract_cart(self.url, headless=True, timeout_seconds=60)
            output_path = write_output(
                extraction,
                customer_name=self.customer_name,
                order_number=self.order_number,
                analyzed_at=self.analyzed_at,
            )
        except CartExtractionError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:
            self.failed.emit(f"حدث خطأ غير متوقع: {error}")
            return
        self.succeeded.emit(extraction, str(output_path.resolve()))


class SummaryCard(QFrame):
    def __init__(self, title: str, color: str, *, compact: bool = False) -> None:
        super().__init__()
        self.setObjectName("summaryCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(0)
        title_label = QLabel(title)
        title_label.setObjectName("summaryTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label = QLabel("0")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setStyleSheet(
            f"font-size: {'18px' if compact else '20px'}; "
            f"font-weight: 700; color: {color};"
        )
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: int) -> None:
        self.value_label.setText(str(value))


class RenameDialog(QDialog):
    def __init__(self, entry: HistoryEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("إعادة تسمية التحليل")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("اسم العميل الجديد:"))
        self.name_input = QLineEdit(entry.customer_name if entry.extraction else "")
        self.name_input.selectAll()
        layout.addWidget(self.name_input)
        timestamp = timestamp_from_filename(entry.path) or entry.analyzed_at
        fixed_time = QLabel(
            f"التاريخ والوقت الثابت: {timestamp.strftime('%Y%m%d-%H%M%S')}"
        )
        fixed_time.setObjectName("mutedLabel")
        layout.addWidget(fixed_time)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def customer_name(self) -> str:
        return self.name_input.text().strip()


class HistorySidebar(QFrame):
    file_selected = Signal(str)
    rename_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("historyPanel")
        self.entries: dict[str, HistoryEntry] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("سجل التحليلات")
        title.setObjectName("historyTitle")
        self.count_label = QLabel("0 ملف")
        self.count_label.setObjectName("mutedLabel")
        title_row.addWidget(self.count_label)
        title_row.addStretch()
        title_row.addWidget(title)
        layout.addLayout(title_row)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("بحث باسم العميل أو الملف")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedHeight(40)
        self.search_input.textChanged.connect(self.apply_filter)
        layout.addWidget(self.search_input)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("historyList")
        self.list_widget.setSpacing(4)
        self.list_widget.itemClicked.connect(self._emit_selection)
        self.list_widget.itemSelectionChanged.connect(self._update_rename_button)
        layout.addWidget(self.list_widget, 1)

        self.rename_button = QPushButton("إعادة تسمية الملف")
        self.rename_button.setObjectName("secondaryButton")
        self.rename_button.setDisabled(True)
        self.rename_button.clicked.connect(self._emit_rename)
        layout.addWidget(self.rename_button)

    def refresh(self, selected_path: Path | None = None) -> None:
        scroll_value = self.list_widget.verticalScrollBar().value()
        current_path = selected_path or self.selected_path()
        self.list_widget.clear()
        self.entries.clear()
        OUTPUT_DIRECTORY.mkdir(exist_ok=True)
        entries = [
            history_entry_from_path(path) for path in OUTPUT_DIRECTORY.glob("*.json")
        ]
        entries.sort(key=lambda entry: entry.sort_key, reverse=True)
        for entry in entries:
            self.entries[str(entry.path.resolve())] = entry
            item = QListWidgetItem(self._entry_text(entry))
            item.setData(Qt.ItemDataRole.UserRole, str(entry.path.resolve()))
            item.setToolTip(str(entry.path.resolve()))
            item.setSizeHint(QSize(270, 120 if entry.order_number else 104))
            if entry.error:
                item.setForeground(QColor("#ef4444"))
            self.list_widget.addItem(item)
            if current_path and entry.path.resolve() == current_path.resolve():
                item.setSelected(True)
                self.list_widget.setCurrentItem(item)
        self.count_label.setText(f"{len(entries)} ملف")
        self.apply_filter(self.search_input.text())
        self.list_widget.verticalScrollBar().setValue(scroll_value)
        self._update_rename_button()

    def _entry_text(self, entry: HistoryEntry) -> str:
        if entry.extraction is None:
            return f"{entry.path.name}\nملف غير قابل للقراءة"
        counts = entry.extraction.counts
        order_line = (
            f"رقم الطلبية: {entry.order_number}\n" if entry.order_number else ""
        )
        return (
            f"{entry.customer_name}\n"
            f"{order_line}"
            f"{entry.analyzed_at.strftime('%Y-%m-%d  %H:%M:%S')}\n"
            f"{entry.path.name}\n"
            f"الإجمالي {len(entry.extraction.products)} | "
            f"متاح {counts.get('normalProducts', 0)} | "
            f"غير متوفر {counts.get('unavailable', 0)}"
        )

    def selected_path(self) -> Path | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return Path(item.data(Qt.ItemDataRole.UserRole))

    def entry_for_path(self, path: Path) -> HistoryEntry | None:
        return self.entries.get(str(path.resolve()))

    @Slot(str)
    def apply_filter(self, query: str) -> None:
        normalized = query.strip().casefold()
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            item.setHidden(normalized not in item.text().casefold())

    @Slot(QListWidgetItem)
    def _emit_selection(self, item: QListWidgetItem) -> None:
        self.file_selected.emit(item.data(Qt.ItemDataRole.UserRole))

    @Slot()
    def _emit_rename(self) -> None:
        path = self.selected_path()
        if path:
            self.rename_requested.emit(str(path))

    @Slot()
    def _update_rename_button(self) -> None:
        path = self.selected_path()
        entry = self.entry_for_path(path) if path else None
        self.rename_button.setEnabled(entry is not None and entry.error is None)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.worker_thread: QThread | None = None
        self.worker: ExtractionWorker | None = None
        self.current_extraction: CartExtraction | None = None
        self.current_output_path: Path | None = None
        self.last_history_width = 320
        self.settings = QSettings("SHEINExtractor", "SHEINExtractor")
        self.image_manager = QNetworkAccessManager(self)
        self.image_cache: dict[str, QPixmap] = {}
        self.pending_image_urls: set[str] = set()
        self.failed_image_urls: set[str] = set()
        self.image_waiters: dict[
            str, list[weakref.ReferenceType[QLabel]]
        ] = {}
        self.setWindowTitle("SHEIN Cart Products")
        self.resize(1500, 900)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build_ui()
        self._apply_style()
        self.history_sidebar.refresh()
        self._restore_settings()

    def _build_ui(self) -> None:
        central_widget = QWidget()
        root = QVBoxLayout(central_widget)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.splitter.setChildrenCollapsible(True)
        self.history_sidebar = HistorySidebar()
        self.history_sidebar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.history_sidebar.file_selected.connect(self.load_history_file)
        self.history_sidebar.rename_requested.connect(self.rename_history_file)
        self.main_panel = self._build_main_panel()
        self.main_panel.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.splitter.addWidget(self.history_sidebar)
        self.splitter.addWidget(self.main_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([310, 1174])
        root.addWidget(self.splitter, 1)
        self.setCentralWidget(central_widget)

    def _build_action_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("toolbar")
        frame.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        frame.setFixedHeight(52)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(4, 4, 12, 4)
        layout.setSpacing(8)
        title = QLabel("استخراج منتجات سلة SHEIN")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.new_button = QPushButton("تحليل جديد")
        self.new_button.setObjectName("newAnalysisButton")
        self.new_button.setFixedSize(148, 44)
        self.new_button.clicked.connect(self.start_new_analysis)
        self.product_search_input = QLineEdit()
        self.product_search_input.setObjectName("productSearchInput")
        self.product_search_input.setPlaceholderText("بحث بالاسم، SKU، أو المقاس...")
        self.product_search_input.setClearButtonEnabled(True)
        self.product_search_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.product_search_input.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.product_search_input.setFixedSize(280, 44)
        self.product_search_input.textChanged.connect(self.apply_product_filter)
        self.product_search_result = QLabel("0 من 0")
        self.product_search_result.hide()
        self.history_toggle_button = QPushButton()
        self.history_toggle_button.setObjectName("historyButton")
        self.history_toggle_button.setFixedSize(44, 44)
        self.history_toggle_button.setIcon(
            QIcon(str(ASSET_DIRECTORY / "history-toggle.svg"))
        )
        self.history_toggle_button.setIconSize(QSize(20, 20))
        self.history_toggle_button.setToolTip("إخفاء السجل")
        self.history_toggle_button.clicked.connect(self.toggle_history)
        layout.addWidget(self.history_toggle_button)
        layout.addWidget(self.new_button)
        layout.addWidget(self.product_search_input)
        layout.addStretch()
        layout.addWidget(title)
        return frame

    def _build_main_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_action_bar())

        input_frame = QFrame()
        input_frame.setObjectName("panel")
        input_frame.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        input_frame.setFixedHeight(108)
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(14, 10, 14, 10)
        input_layout.setSpacing(10)

        self.extract_button = QPushButton("تحليل الرابط")
        self.extract_button.setObjectName("analyzeButton")
        self.extract_button.setFixedSize(110, 88)
        self.extract_button.clicked.connect(self.start_extraction)
        input_layout.addWidget(self.extract_button)

        content_rows = QVBoxLayout()
        content_rows.setContentsMargins(0, 0, 0, 0)
        content_rows.setSpacing(8)

        invoice_row = QHBoxLayout()
        invoice_row.setDirection(QHBoxLayout.Direction.LeftToRight)
        invoice_row.setSpacing(8)
        self.invoice_paste_button = QPushButton("لصق الفاتورة")
        self.invoice_paste_button.setObjectName("invoicePasteButton")
        self.invoice_paste_button.setFixedSize(90, 44)
        self.invoice_paste_button.clicked.connect(self.paste_invoice)
        self.invoice_input = QPlainTextEdit()
        self.invoice_input.setObjectName("invoiceInput")
        self.invoice_input.setPlaceholderText("ألصق فاتورة العميل أو رابط السلة هنا")
        self.invoice_input.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.invoice_input.setFixedHeight(44)
        invoice_text_option = self.invoice_input.document().defaultTextOption()
        invoice_text_option.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.invoice_input.document().setDefaultTextOption(invoice_text_option)
        self.invoice_input.textChanged.connect(self.parse_invoice_input)
        invoice_row.addWidget(self.invoice_paste_button)
        invoice_row.addWidget(self.invoice_input, 1)
        content_rows.addLayout(invoice_row)

        fields_row = QHBoxLayout()
        fields_row.setDirection(QHBoxLayout.Direction.LeftToRight)
        fields_row.setSpacing(8)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("ألصق رابط مشاركة SHEIN هنا")
        self.url_input.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.url_input.setClearButtonEnabled(True)
        self.url_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.url_input.setFixedHeight(44)
        self.url_input.setMinimumWidth(420)
        self.url_input.returnPressed.connect(self.start_extraction)
        self.link_paste_button = QPushButton("لصق الرابط")
        self.link_paste_button.setObjectName("secondaryButton")
        self.link_paste_button.setFixedSize(90, 44)
        self.link_paste_button.clicked.connect(self.paste_url)
        self.customer_input = QLineEdit()
        self.customer_input.setPlaceholderText("اسم العميل (اختياري)")
        self.customer_input.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.customer_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.customer_input.setFixedHeight(44)
        self.order_input = QLineEdit()
        self.order_input.setPlaceholderText("رقم الطلبية (اختياري)")
        self.order_input.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.order_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.order_input.setFixedHeight(44)
        fields_row.addWidget(self.link_paste_button)
        fields_row.addWidget(self.url_input, 3)
        fields_row.addWidget(self.customer_input, 2)
        fields_row.addWidget(self.order_input, 1)
        content_rows.addLayout(fields_row)
        input_layout.addLayout(content_rows, 1)
        layout.addWidget(input_frame)

        overview_container = QWidget()
        overview_container.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        overview_row = QHBoxLayout(overview_container)
        overview_row.setContentsMargins(0, 0, 0, 0)
        overview_row.setDirection(QHBoxLayout.Direction.LeftToRight)
        overview_row.setSpacing(8)

        actions_frame = QFrame()
        actions_frame.setObjectName("actionPanel")
        actions_frame.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        actions_frame.setFixedWidth(136)
        actions_layout = QVBoxLayout(actions_frame)
        actions_layout.setContentsMargins(10, 10, 10, 10)
        actions_layout.setSpacing(10)
        self.export_button = QPushButton("تصدير البيانات")
        self.export_button.setObjectName("exportButton")
        self.export_button.setDisabled(True)
        self.export_button.setToolTip("يتاح بعد اكتمال تحميل جميع صور المنتجات")
        self.export_button.clicked.connect(self.export_pdf)
        self.copy_button = QPushButton("نسخ البيانات")
        self.copy_button.setObjectName("copyButton")
        self.copy_button.setDisabled(True)
        self.copy_button.setToolTip("سيتم تفعيله بعد تحديد تنسيق النسخ")
        actions_layout.addWidget(self.export_button)
        actions_layout.addWidget(self.copy_button)
        overview_row.addWidget(actions_frame)

        details_frame = QFrame()
        details_frame.setObjectName("detailsPanel")
        details_frame.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(10, 8, 10, 8)
        details_layout.setSpacing(6)
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("جاهز لاستقبال الرابط.")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(180)
        self.progress.hide()
        status_title = QLabel("الحالة:")
        status_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(status_title)
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progress)
        details_layout.addLayout(status_layout)

        self.metadata_frame = QFrame()
        self.metadata_frame.setObjectName("metadataPanel")
        metadata_layout = QVBoxLayout(self.metadata_frame)
        metadata_layout.setContentsMargins(8, 5, 8, 5)
        metadata_layout.setSpacing(2)
        self.metadata_title = QLabel("لا توجد بيانات معروضة")
        self.metadata_title.setObjectName("sectionTitle")
        self.metadata_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.metadata_details = QLabel("")
        self.metadata_details.setObjectName("mutedLabel")
        self.metadata_details.setWordWrap(True)
        self.metadata_details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        metadata_layout.addWidget(self.metadata_title)
        metadata_layout.addWidget(self.metadata_details)
        details_layout.addWidget(self.metadata_frame, 1)
        overview_row.addWidget(details_frame, 1)

        metrics_frame = QFrame()
        metrics_frame.setObjectName("metricsPanel")
        metrics_frame.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        metrics_frame.setFixedWidth(300)
        metrics_layout = QGridLayout(metrics_frame)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setHorizontalSpacing(6)
        metrics_layout.setVerticalSpacing(6)
        self.total_card = SummaryCard("إجمالي المنتجات", "#60a5fa")
        self.available_card = SummaryCard("المتاحة", "#22c55e", compact=True)
        self.out_of_stock_card = SummaryCard("النافدة", "#f59e0b", compact=True)
        self.unavailable_card = SummaryCard("غير المتوفرة", "#ef4444", compact=True)
        metrics_layout.addWidget(self.total_card, 0, 0, 1, 3)
        metrics_layout.addWidget(self.available_card, 1, 0)
        metrics_layout.addWidget(self.out_of_stock_card, 1, 1)
        metrics_layout.addWidget(self.unavailable_card, 1, 2)
        overview_row.addWidget(metrics_frame)
        layout.addWidget(overview_container)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["الحالة", "الصورة", "اسم المنتج", "SKU", "الخصائص / المقاس", "السعر"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        header = self.table.horizontalHeader()
        header.setFixedHeight(44)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 110)
        header.resizeSection(1, 140)
        header.resizeSection(2, 362)
        header.resizeSection(3, 200)
        header.resizeSection(4, 210)
        header.resizeSection(5, 110)
        header.setStretchLastSection(False)
        self.product_table_stack = QStackedWidget()
        self.product_table_stack.addWidget(self.table)
        self.product_empty_label = QLabel("لا توجد منتجات مطابقة للبحث.")
        self.product_empty_label.setObjectName("productEmptyLabel")
        self.product_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.product_table_stack.addWidget(self.product_empty_label)
        layout.addWidget(self.product_table_stack, 1)
        return panel

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #070b17;
                color: #e5e7eb;
                font-family: "Noto Sans Arabic", "Segoe UI";
                font-size: 13px;
            }
            QLabel#pageTitle { font-size: 24px; font-weight: 700; color: #f8fafc; }
            QLabel#sectionTitle { font-size: 16px; font-weight: 700; color: #f8fafc; }
            QLabel#historyTitle { font-size: 22px; font-weight: 700; color: #f8fafc; }
            QLabel#mutedLabel { color: #94a3b8; }
            QLabel#summaryTitle { color: #94a3b8; font-size: 10px; }
            QLabel#productEmptyLabel {
                background: #0b1220;
                border: 1px solid #263244;
                border-radius: 8px;
                color: #94a3b8;
                font-size: 16px;
                font-weight: 600;
            }
            QFrame#toolbar, QFrame#panel, QFrame#summaryCard, QFrame#historyPanel,
            QFrame#detailsPanel, QFrame#actionPanel {
                background: #111827;
                border: 1px solid #263244;
                border-radius: 8px;
            }
            QFrame#metadataPanel {
                background: #0b1220;
                border: 1px solid #263244;
                border-radius: 6px;
            }
            QFrame#metricsPanel { background: transparent; border: 0; }
            QLineEdit, QPlainTextEdit {
                background: #0b1220;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 10px;
                selection-background-color: #2563eb;
            }
            QPlainTextEdit#invoiceInput { padding: 8px 10px; }
            QPushButton#analyzeButton, QPushButton#invoicePasteButton,
            QPushButton#secondaryButton { font-size: 11px; }
            QLineEdit#productSearchInput {
                background: rgba(31, 38, 56, 0.8);
                border-color: rgba(64, 71, 89, 0.5);
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QPushButton {
                border: 0;
                border-radius: 6px;
                padding: 9px 14px;
                font-weight: 600;
            }
            QPushButton#analyzeButton { background: #0ea5e9; color: white; }
            QPushButton#analyzeButton:hover { background: #0284c7; }
            QPushButton#invoicePasteButton { background: #0f766e; color: white; }
            QPushButton#invoicePasteButton:hover { background: #0d9488; }
            QPushButton#secondaryButton { background: #334155; color: #f8fafc; }
            QPushButton#secondaryButton:hover { background: #475569; }
            QPushButton#newAnalysisButton {
                background: #16a34a;
                color: white;
                font-size: 16px;
                font-weight: 700;
            }
            QPushButton#newAnalysisButton:hover { background: #15803d; }
            QPushButton#historyButton { background: #7c3aed; color: white; }
            QPushButton#historyButton:hover { background: #6d28d9; }
            QPushButton#copyButton { background: #2563eb; color: white; }
            QPushButton#copyButton:hover { background: #1d4ed8; }
            QPushButton#exportButton { background: #d97706; color: white; }
            QPushButton#exportButton:hover { background: #b45309; }
            QPushButton#copyButton:disabled { background: #1e3a5f; color: #93c5fd; }
            QPushButton#exportButton:disabled { background: #5f3a13; color: #fdba74; }
            QPushButton:disabled { background: #252d3a; color: #64748b; }
            QTableWidget, QListWidget#historyList {
                background: #0b1220;
                alternate-background-color: #0f172a;
                border: 1px solid #263244;
                border-radius: 8px;
                gridline-color: #263244;
            }
            QListWidget#historyList::item {
                background: #111827;
                border: 1px solid #263244;
                border-radius: 8px;
                padding: 12px;
            }
            QListWidget#historyList::item:selected {
                background: #172033;
                border-color: #3b82f6;
            }
            QHeaderView::section {
                background: #172033;
                color: #cbd5e1;
                padding: 9px;
                border: 0;
                border-left: 1px solid #263244;
                font-weight: 700;
            }
            QProgressBar {
                border: 1px solid #334155;
                border-radius: 5px;
                background: #0b1220;
            }
            QProgressBar::chunk { background: #2563eb; }
            QSplitter::handle { background: #263244; width: 4px; }
            """
        )

    def _restore_settings(self) -> None:
        self.last_history_width = self.settings.value("history/width", 320, type=int)
        collapsed = self.settings.value("history/collapsed", False, type=bool)
        if collapsed:
            self.splitter.setSizes([0, self.width()])
            self.history_toggle_button.setToolTip("إظهار السجل")
        else:
            self.splitter.setSizes([self.last_history_width, self.width()])
            self.history_toggle_button.setToolTip("إخفاء السجل")

    @Slot()
    def paste_invoice(self) -> None:
        self.invoice_input.setPlainText(QApplication.clipboard().text().strip())

    @Slot()
    def parse_invoice_input(self) -> None:
        invoice_data = parse_invoice_text(self.invoice_input.toPlainText())
        self._apply_invoice_data(invoice_data)

    def _apply_invoice_data(self, invoice_data: InvoiceData) -> None:
        if invoice_data.has_multiple_cart_urls:
            self.url_input.clear()
            self.customer_input.clear()
            self.order_input.clear()
            self.status_label.setText(
                "تم اكتشاف أكثر من رابط. ألصق فاتورة واحدة فقط قبل التحليل."
            )
            return
        self.url_input.setText(invoice_data.cart_url or "")
        self.customer_input.setText(invoice_data.customer_name or "")
        self.order_input.setText(invoice_data.order_number or "")
        if invoice_data.cart_url:
            extracted_fields = ["رابط السلة"]
            if invoice_data.customer_name:
                extracted_fields.append("اسم العميل")
            if invoice_data.order_number:
                extracted_fields.append("رقم الطلبية")
            self.status_label.setText(
                f"تمت تعبئة: {'، '.join(extracted_fields)}. راجعها ثم ابدأ التحليل."
            )

    @Slot()
    def paste_url(self) -> None:
        self.url_input.setText(QApplication.clipboard().text().strip())

    @Slot()
    def start_extraction(self) -> None:
        if self.worker_thread is not None:
            return
        invoice_data = parse_invoice_text(self.invoice_input.toPlainText())
        if invoice_data.has_multiple_cart_urls:
            QMessageBox.warning(
                self,
                "أكثر من فاتورة",
                "تم اكتشاف أكثر من رابط SHEIN. ألصق فاتورة واحدة فقط.",
            )
            return
        try:
            url = validate_shein_url(self.url_input.text())
        except argparse.ArgumentTypeError as error:
            QMessageBox.warning(self, "رابط غير صالح", str(error))
            return

        customer_name = self.customer_input.text().strip() or "shein-cart"
        order_number = self.order_input.text().strip() or None
        analyzed_at = datetime.now().astimezone()
        self._set_busy(True)
        self.status_label.setText("جاري فتح الرابط والتقاط بيانات السلة...")
        self._clear_display()

        self.worker_thread = QThread(self)
        self.worker = ExtractionWorker(
            url,
            customer_name,
            order_number,
            analyzed_at,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(self.on_extraction_succeeded)
        self.worker.failed.connect(self.on_extraction_failed)
        self.worker.succeeded.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    @Slot(object, str)
    def on_extraction_succeeded(
        self, extraction: CartExtraction, output_path: str
    ) -> None:
        path = Path(output_path)
        self._show_extraction(extraction, path, from_history=False)
        self.status_label.setText(
            f"اكتمل استخراج {len(extraction.products)} منتج وحُفظ الملف تلقائيًا."
        )
        self._set_busy(False)
        self.history_sidebar.refresh(path)

    @Slot(str)
    def on_extraction_failed(self, message: str) -> None:
        self.status_label.setText(message)
        self._set_busy(False)
        QMessageBox.warning(self, "تعذر الاستخراج", message)

    @Slot()
    def _cleanup_worker(self) -> None:
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
        self.worker_thread = None
        self.worker = None
        self._update_export_availability()

    @Slot(str)
    def load_history_file(self, path_value: str) -> None:
        if self.worker_thread is not None:
            QMessageBox.information(
                self, "التحليل قيد التنفيذ", "انتظر حتى تنتهي عملية التحليل الحالية."
            )
            return
        path = Path(path_value)
        entry = self.history_sidebar.entry_for_path(path)
        if entry is None:
            return
        if entry.extraction is None:
            QMessageBox.warning(
                self, "ملف غير صالح", entry.error or "تعذر قراءة الملف."
            )
            return
        self.invoice_input.clear()
        self.url_input.setText(entry.extraction.source_url)
        self.customer_input.setText(
            "" if entry.customer_name == "غير محدد" else entry.customer_name
        )
        self.order_input.setText(entry.extraction.order_number or "")
        self._show_extraction(entry.extraction, path, from_history=True)
        self.status_label.setText("تم تحميل التحليل من السجل المحلي.")

    @Slot(str)
    def rename_history_file(self, path_value: str) -> None:
        path = Path(path_value)
        entry = self.history_sidebar.entry_for_path(path)
        if entry is None or entry.error:
            return
        dialog = RenameDialog(entry, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        customer_name = dialog.customer_name()
        if not customer_name:
            QMessageBox.warning(self, "اسم غير صالح", "اكتب اسم العميل الجديد.")
            return
        try:
            new_path = rename_history_path(
                path,
                customer_name,
                entry.extraction.order_number,
            )
        except (OSError, FileExistsError) as error:
            QMessageBox.warning(self, "تعذر إعادة التسمية", str(error))
            return
        if (
            self.current_output_path
            and self.current_output_path.resolve() == path.resolve()
        ):
            self.current_output_path = new_path
            self._update_metadata(from_history=True)
        self.history_sidebar.refresh(new_path)

    @Slot()
    def start_new_analysis(self) -> None:
        if self.worker_thread is not None:
            QMessageBox.information(
                self, "التحليل قيد التنفيذ", "انتظر حتى تنتهي عملية التحليل الحالية."
            )
            return
        self.url_input.clear()
        self.customer_input.clear()
        self.order_input.clear()
        self.invoice_input.clear()
        self.status_label.setText("جاهز لاستقبال الرابط.")
        self.history_sidebar.list_widget.clearSelection()
        self._clear_display()
        self.url_input.setFocus()

    @Slot()
    def toggle_history(self) -> None:
        sizes = self.splitter.sizes()
        total = max(sum(sizes), self.width())
        if sizes[0] > 0:
            self.last_history_width = sizes[0]
            self.splitter.setSizes([0, total])
            self.history_toggle_button.setToolTip("إظهار السجل")
        else:
            width = max(self.last_history_width, 260)
            self.splitter.setSizes([width, max(total - width, 600)])
            self.history_toggle_button.setToolTip("إخفاء السجل")

    def _show_extraction(
        self, extraction: CartExtraction, path: Path, *, from_history: bool
    ) -> None:
        self.product_search_input.clear()
        self.current_extraction = extraction
        self.current_output_path = path
        self._populate_summary(extraction)
        self._populate_products(extraction.products)
        self._update_metadata(from_history=from_history)

    def _update_metadata(self, *, from_history: bool) -> None:
        if self.current_extraction is None or self.current_output_path is None:
            self.metadata_title.setText("لا توجد بيانات معروضة")
            self.metadata_details.clear()
            return
        extraction = self.current_extraction
        customer_name = extraction.customer_name or "غير محدد"
        order_number = extraction.order_number or "غير محدد"
        analyzed_at = extraction.analyzed_at
        if analyzed_at is None:
            analyzed_at = timestamp_from_filename(self.current_output_path)
        time_text = (
            analyzed_at.strftime("%Y-%m-%d %H:%M:%S") if analyzed_at else "غير محدد"
        )
        source = "السجل المحلي" if from_history else "تحليل جديد"
        self.metadata_title.setText(f"{customer_name} — {source}")
        self.metadata_details.setText(
            f"رقم الطلبية: {order_number}   |   الوقت: {time_text}   |   "
            f"الملف: {self.current_output_path.name}\n"
            f"المجموعة: {extraction.group_id or 'غير محدد'}   |   "
            f"السوق: {extraction.local_country}\n"
            f"الرابط: {extraction.source_url}"
        )

    def _set_busy(self, busy: bool) -> None:
        self.extract_button.setDisabled(busy)
        self.invoice_input.setDisabled(busy)
        self.invoice_paste_button.setDisabled(busy)
        self.link_paste_button.setDisabled(busy)
        self.url_input.setDisabled(busy)
        self.customer_input.setDisabled(busy)
        self.order_input.setDisabled(busy)
        self.new_button.setDisabled(busy)
        self.product_search_input.setDisabled(busy)
        self.history_sidebar.setDisabled(busy)
        self.progress.setVisible(busy)
        if busy:
            self.export_button.setDisabled(True)

    def _clear_display(self) -> None:
        self.current_extraction = None
        self.current_output_path = None
        self.product_search_input.clear()
        self.table.setRowCount(0)
        self.product_table_stack.setCurrentWidget(self.table)
        self.product_search_result.setText("0 من 0")
        for card in (
            self.total_card,
            self.available_card,
            self.out_of_stock_card,
            self.unavailable_card,
        ):
            card.set_value(0)
        self.metadata_title.setText("لا توجد بيانات معروضة")
        self.metadata_details.clear()
        self.copy_button.setDisabled(True)
        self.export_button.setDisabled(True)

    def _populate_summary(self, extraction: CartExtraction) -> None:
        self.total_card.set_value(len(extraction.products))
        self.available_card.set_value(extraction.counts.get("normalProducts", 0))
        self.out_of_stock_card.set_value(extraction.counts.get("outStock", 0))
        self.unavailable_card.set_value(extraction.counts.get("unavailable", 0))

    def _populate_products(self, products: list[ExtractedCartItem]) -> None:
        self.table.setRowCount(len(products))
        for row, product in enumerate(products):
            self.table.setRowHeight(row, ROW_HEIGHT)
            self._set_product_row(row, product)
        self.apply_product_filter(self.product_search_input.text())
        self._update_export_availability()

    @Slot(str)
    def apply_product_filter(self, query: str) -> None:
        products = self.current_extraction.products if self.current_extraction else []
        total = len(products)
        visible = 0
        for row, product in enumerate(products):
            matches = product_matches_query(product, query)
            self.table.setRowHidden(row, not matches)
            visible += int(matches)

        normalized_query = normalize_product_search(query)
        if normalized_query and total and visible == 0:
            self.product_table_stack.setCurrentWidget(self.product_empty_label)
            self.product_search_result.setText("لا توجد نتائج")
            return

        self.product_table_stack.setCurrentWidget(self.table)
        self.product_search_result.setText(f"{visible} من {total}")

    def _set_product_row(self, row: int, product: ExtractedCartItem) -> None:
        status_item = QTableWidgetItem(STATUS_LABELS[product.availability])
        status_item.setForeground(QColor(STATUS_COLORS[product.availability]))
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 0, status_item)

        image_label = QLabel("تحميل...")
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setFixedSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        image_label.setStyleSheet(
            "background: #111827; border: 1px solid #263244; border-radius: 6px; "
            "color: #64748b;"
        )
        image_container = QWidget()
        image_layout = QHBoxLayout(image_container)
        image_layout.setContentsMargins(6, 6, 6, 6)
        image_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_layout.addWidget(image_label)
        self.table.setCellWidget(row, 1, image_container)
        self._load_image(product.goods_img, image_label)

        full_name = product.goods_name or "—"
        visible_name = truncate_product_name(full_name)
        name_item = QTableWidgetItem(visible_name)
        name_item.setToolTip(full_name)
        name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 2, name_item)

        sku_item = QTableWidgetItem(product.sku_code or "—")
        sku_item.setToolTip(product.sku_code or "")
        sku_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 3, sku_item)

        attr_item = QTableWidgetItem(product.goods_attr or "—")
        attr_item.setToolTip(product.goods_attr or "")
        attr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 4, attr_item)
        price_item = QTableWidgetItem(product.amountWithSymbol or "—")
        price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 5, price_item)

    def _load_image(self, url: str | None, label: QLabel) -> None:
        if not url:
            label.setText("لا توجد صورة")
            self._update_export_availability()
            return
        cached = self.image_cache.get(url)
        if cached is not None:
            label.setPixmap(cached)
            label.setText("")
            self._update_export_availability()
            return
        label_reference = weakref.ref(label)
        if url in self.pending_image_urls:
            self.image_waiters.setdefault(url, []).append(label_reference)
            return

        self.failed_image_urls.discard(url)
        self.pending_image_urls.add(url)
        self.image_waiters[url] = [label_reference]
        reply = self.image_manager.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(
            lambda current_reply=reply, image_url=url: self._finish_image(
                current_reply, image_url
            )
        )
        self._update_export_availability()

    def _finish_image(
        self,
        reply: QNetworkReply,
        url: str,
    ) -> None:
        waiters = self.image_waiters.pop(url, [])
        self.pending_image_urls.discard(url)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.failed_image_urls.add(url)
                self._set_image_waiters_text(waiters, "تعذر التحميل")
                return
            pixmap = QPixmap()
            if not pixmap.loadFromData(reply.readAll()):
                self.failed_image_urls.add(url)
                self._set_image_waiters_text(waiters, "صورة غير صالحة")
                return
            scaled = pixmap.scaled(
                THUMBNAIL_SIZE,
                THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_cache[url] = scaled
            self.failed_image_urls.discard(url)
            for reference in waiters:
                label = reference()
                if label is not None:
                    label.setPixmap(scaled)
                    label.setText("")
        except RuntimeError:
            pass
        finally:
            reply.deleteLater()
            self._update_export_availability()

    @staticmethod
    def _set_image_waiters_text(
        waiters: list[weakref.ReferenceType[QLabel]], text: str
    ) -> None:
        for reference in waiters:
            label = reference()
            if label is not None:
                label.setText(text)

    def _image_loading_counts(self) -> tuple[int, int, int]:
        products = self.current_extraction.products if self.current_extraction else []
        total = len(products)
        loaded = sum(
            bool(product.goods_img and product.goods_img in self.image_cache)
            for product in products
        )
        failed = sum(
            not product.goods_img or product.goods_img in self.failed_image_urls
            for product in products
        )
        return total, loaded, failed

    def _update_export_availability(self) -> None:
        total, loaded, failed = self._image_loading_counts()
        ready = bool(total) and loaded == total and failed == 0
        self.export_button.setEnabled(ready and self.worker_thread is None)
        if ready:
            self.export_button.setToolTip(
                "تصدير جميع المنتجات المعروضة في التحليل إلى ملف PDF"
            )
        elif failed:
            self.export_button.setToolTip(
                f"تعذر تجهيز {failed} صورة. أعد فتح التحليل بعد التحقق من الاتصال."
            )
        elif total:
            self.export_button.setToolTip(
                f"جاري تحميل صور المنتجات: {loaded} من {total}"
            )
        else:
            self.export_button.setToolTip("لا توجد منتجات لتصديرها")

    @Slot()
    def export_pdf(self) -> None:
        if self.current_extraction is None or self.current_output_path is None:
            return
        total, loaded, failed = self._image_loading_counts()
        if failed or loaded != total:
            QMessageBox.information(
                self,
                "الصور غير مكتملة",
                "انتظر حتى تظهر جميع صور المنتجات قبل تصدير ملف PDF.",
            )
            return

        EXPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        suggested_path = default_pdf_path(
            self.current_output_path,
            EXPORT_DIRECTORY,
        ).resolve()
        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "حفظ تقرير PDF",
            str(suggested_path),
            "PDF (*.pdf)",
        )
        if not selected_path:
            return
        output_path = Path(selected_path)
        if output_path.suffix.casefold() != ".pdf":
            output_path = output_path.with_suffix(".pdf")

        self.export_button.setDisabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.show()
        self.status_label.setText("جاري إنشاء تقرير PDF بجميع المنتجات...")

        def update_progress(current: int, maximum: int) -> None:
            self.progress.setRange(0, maximum)
            self.progress.setValue(current)
            QApplication.processEvents()

        try:
            page_count = export_cart_pdf(
                self.current_extraction,
                output_path,
                self.image_cache,
                json_name=self.current_output_path.name,
                progress_callback=update_progress,
            )
        except (OSError, RuntimeError) as error:
            QMessageBox.warning(self, "تعذر تصدير PDF", str(error))
            self.status_label.setText("تعذر إنشاء تقرير PDF.")
            return
        finally:
            self.progress.hide()
            self.progress.setRange(0, 0)
            self._update_export_availability()

        self.status_label.setText(
            f"تم تصدير جميع المنتجات إلى PDF في {page_count} صفحة."
        )
        QMessageBox.information(
            self,
            "اكتمل التصدير",
            f"تم حفظ التقرير بنجاح:\n{output_path}",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker_thread is not None:
            QMessageBox.information(
                self,
                "التحليل قيد التنفيذ",
                "انتظر حتى تنتهي عملية الاستخراج قبل إغلاق البرنامج.",
            )
            event.ignore()
            return
        sizes = self.splitter.sizes()
        collapsed = sizes[0] == 0
        if not collapsed:
            self.last_history_width = sizes[0]
        self.settings.setValue("history/width", self.last_history_width)
        self.settings.setValue("history/collapsed", collapsed)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SHEIN Extractor")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
