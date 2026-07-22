from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


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

