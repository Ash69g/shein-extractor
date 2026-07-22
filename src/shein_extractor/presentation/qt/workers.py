from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QObject, Signal, Slot

from shein_extractor.application.use_cases import AnalyzeCart, AnalyzeCartRequest
from shein_extractor.domain.errors import CartExtractionError


class ExtractionWorker(QObject):
    succeeded = Signal(object, str)
    failed = Signal(str)

    def __init__(
        self,
        use_case: AnalyzeCart,
        url: str,
        customer_name: str,
        order_number: str | None,
        analyzed_at: datetime,
    ) -> None:
        super().__init__()
        self.use_case = use_case
        self.request = AnalyzeCartRequest(
            url=url,
            customer_name=customer_name,
            order_number=order_number,
            analyzed_at=analyzed_at,
        )

    @Slot()
    def run(self) -> None:
        try:
            result = self.use_case.execute(self.request)
        except CartExtractionError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:
            self.failed.emit(f"حدث خطأ غير متوقع: {error}")
            return
        self.succeeded.emit(result.extraction, str(result.output_path.resolve()))

