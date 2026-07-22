from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from shein_extractor.application.history import HistoryEntry, list_history


class HistorySidebar(QFrame):
    file_selected = Signal(str)
    rename_requested = Signal(str)

    def __init__(self, output_directory: Path) -> None:
        super().__init__()
        self.output_directory = output_directory
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
        entries = list_history(self.output_directory)
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

    @staticmethod
    def _entry_text(entry: HistoryEntry) -> str:
        if entry.extraction is None:
            return f"{entry.path.name}\nملف غير قابل للقراءة"
        counts = entry.extraction.counts
        order_line = f"رقم الطلبية: {entry.order_number}\n" if entry.order_number else ""
        return (
            f"{entry.customer_name}\n{order_line}"
            f"{entry.analyzed_at.strftime('%Y-%m-%d  %H:%M:%S')}\n"
            f"{entry.path.name}\n"
            f"الإجمالي {len(entry.extraction.products)} | "
            f"متاح {counts.get('normalProducts', 0)} | "
            f"غير متوفر {counts.get('unavailable', 0)}"
        )

    def selected_path(self) -> Path | None:
        item = self.list_widget.currentItem()
        return Path(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

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

