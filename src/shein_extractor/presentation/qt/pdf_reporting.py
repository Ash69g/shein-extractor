from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from shein_extractor.application.naming import report_path_for
from shein_extractor.presentation.qt.constants import MAX_IMAGE_ATTEMPTS

EXPORT_DIRECTORY = Path("exports")


class PdfReportingMixin:
    def _current_pdf_path(self) -> Path | None:
        if self.current_output_path is None:
            return None
        return report_path_for(self.current_output_path, EXPORT_DIRECTORY).resolve()

    def _update_export_availability(self) -> None:
        total, loaded, failed = self._image_loading_counts()
        resolved = loaded + failed
        pdf_path = self._current_pdf_path()
        pdf_exists = bool(pdf_path and pdf_path.exists())
        ready = bool(total) and resolved == total
        self.export_button.setEnabled(
            (pdf_exists or ready)
            and self.worker_thread is None
            and not self.pdf_export_in_progress
        )
        if pdf_exists:
            self.export_button.setToolTip("فتح تقرير PDF المحفوظ مسبقًا")
        elif ready:
            self.export_button.setToolTip(
                "إنشاء تقرير PDF لجميع منتجات التحليل"
            )
        elif total:
            max_attempt = max(
                (
                    self.image_retry_attempts.get(product.goods_img or "", 0)
                    for product in self.current_extraction.products
                ),
                default=0,
            )
            self.export_button.setToolTip(
                f"جاري تجهيز الصور: {loaded} من {total} — المحاولة {max_attempt}/{MAX_IMAGE_ATTEMPTS}"
            )
        else:
            self.export_button.setToolTip("لا توجد منتجات لتصديرها")

        if (
            total
            and resolved < total
            and not self.pdf_export_in_progress
            and self.worker_thread is None
        ):
            active_attempt = max(
                (
                    self.image_retry_attempts.get(product.goods_img or "", 0)
                    for product in self.current_extraction.products
                    if product.goods_img not in self.image_cache
                ),
                default=0,
            )
            self.progress.setRange(0, total)
            self.progress.setValue(resolved)
            self.progress.show()
            self.status_label.setText(
                f"جاري تحميل صور المنتجات: {loaded} من {total}"
                + (
                    f" — المحاولة {active_attempt}/{MAX_IMAGE_ATTEMPTS}"
                    if active_attempt > 1
                    else ""
                )
                + (
                    f" — توجد {failed} صورة غير متوفرة"
                    if failed
                    else ""
                )
            )
        elif ready and not self.pdf_export_in_progress:
            self.progress.hide()
            self.progress.setRange(0, 0)
            if not self.auto_export_pending:
                self.status_label.setText(
                    "اكتمل تجهيز صور المنتجات. تقرير PDF جاهز."
                )

        if (
            self.auto_export_pending
            and self.worker_thread is None
            and (pdf_exists or ready)
            and not self.pdf_export_in_progress
        ):
            self.auto_export_pending = False
            QTimer.singleShot(0, self._auto_export_pdf)

    @Slot()
    def export_pdf(self) -> None:
        if self.current_extraction is None or self.current_output_path is None:
            return
        output_path = self._current_pdf_path()
        if output_path is None:
            return
        if output_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_path)))
            self.show_toast("تم فتح تقرير PDF المحفوظ مسبقًا.")
            return
        total, loaded, failed = self._image_loading_counts()
        if loaded + failed != total:
            self.show_toast("انتظر حتى تنتهي محاولات تحميل الصور.", error=True)
            return
        self._create_pdf(output_path, automatic=False)

    @Slot()
    def _auto_export_pdf(self) -> None:
        if self.is_closing:
            return
        output_path = self._current_pdf_path()
        if output_path is None:
            return
        if output_path.exists():
            self.status_label.setText("ملف PDF محفوظ مسبقًا لهذا التحليل.")
            self.show_toast("تقرير PDF موجود ومحفوظ مسبقًا.")
            self._update_export_availability()
            return
        self._create_pdf(output_path, automatic=True)

    def _create_pdf(self, output_path: Path, *, automatic: bool) -> None:
        if (
            self.is_closing
            or self.current_extraction is None
            or self.current_output_path is None
        ):
            return

        EXPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        self.pdf_export_in_progress = True
        self.export_button.setDisabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.show()
        self.status_label.setText("جاري إنشاء صفحات تقرير PDF...")

        def update_progress(current: int, maximum: int) -> None:
            self.progress.setRange(0, maximum)
            self.progress.setValue(current)
            self.status_label.setText(
                f"جاري إنشاء ملف PDF: الصفحة {current} من {maximum}"
            )
            QApplication.processEvents()

        try:
            result = self.export_report.execute(
                self.current_extraction,
                output_path,
                self.image_cache,
                json_name=self.current_output_path.name,
                progress_callback=update_progress,
            )
        except (OSError, RuntimeError) as error:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.status_label.setText("تعذر إنشاء تقرير PDF.")
            self.show_toast(f"تعذر إنشاء PDF: {error}", error=True, duration=4000)
            return
        finally:
            self.pdf_export_in_progress = False
            self.progress.hide()
            self.progress.setRange(0, 0)
            self._update_export_availability()

        save_mode = "تلقائيًا" if automatic else "بنجاح"
        self.status_label.setText(
            f"تم حفظ PDF {save_mode} في {result.page_count} صفحة."
            + (
                f" استُخدم بديل لـ {result.unavailable_image_count} صورة."
                if result.unavailable_image_count
                else " جميع الصور مكتملة."
            )
        )
        toast_text = (
            "تم حفظ ملف PDF تلقائيًا."
            if automatic
            else "تم حفظ ملف PDF بنجاح."
        )
        if result.unavailable_image_count:
            toast_text += f" صور غير متوفرة: {result.unavailable_image_count}."
        self.show_toast(toast_text)
