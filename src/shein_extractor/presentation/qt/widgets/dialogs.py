from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from shein_extractor.application.history import HistoryEntry, timestamp_from_filename


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

