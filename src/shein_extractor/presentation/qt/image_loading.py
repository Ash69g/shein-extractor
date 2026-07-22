from __future__ import annotations

import weakref

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QLabel

from shein_extractor.presentation.qt.constants import MAX_IMAGE_ATTEMPTS, THUMBNAIL_SIZE


class ImageLoadingMixin:
    def _load_image(self, url: str | None, label: QLabel) -> None:
        if not url:
            label.setText("غير متوفر")
            self._update_export_availability()
            return
        cached = self.image_cache.get(url)
        if cached is not None:
            label.setPixmap(cached)
            label.setText("")
            self._update_export_availability()
            return
        label_reference = weakref.ref(label)
        self.image_waiters.setdefault(url, []).append(label_reference)
        if url in self.pending_image_urls or url in self.scheduled_image_urls:
            return

        self.failed_image_urls.discard(url)
        self.image_retry_attempts[url] = 0
        self._request_image(url)

    def _request_image(self, url: str) -> None:
        if url in self.image_cache or url in self.pending_image_urls:
            return
        self.scheduled_image_urls.discard(url)
        self.pending_image_urls.add(url)
        self.image_retry_attempts[url] = self.image_retry_attempts.get(url, 0) + 1
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
        waiters = self.image_waiters.get(url, [])
        self.pending_image_urls.discard(url)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._schedule_image_retry(url, waiters)
                return
            pixmap = QPixmap()
            if not pixmap.loadFromData(reply.readAll()):
                self._schedule_image_retry(url, waiters)
                return
            scaled = pixmap.scaled(
                THUMBNAIL_SIZE,
                THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_cache[url] = scaled
            self.failed_image_urls.discard(url)
            self.scheduled_image_urls.discard(url)
            self.image_waiters.pop(url, None)
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

    def _schedule_image_retry(
        self,
        url: str,
        waiters: list[weakref.ReferenceType[QLabel]],
    ) -> None:
        attempt = self.image_retry_attempts.get(url, 1)
        if attempt >= MAX_IMAGE_ATTEMPTS:
            self.failed_image_urls.add(url)
            self.scheduled_image_urls.discard(url)
            self.image_waiters.pop(url, None)
            self._set_image_waiters_text(waiters, "غير متوفر")
            return

        next_attempt = attempt + 1
        self.scheduled_image_urls.add(url)
        self._set_image_waiters_text(
            waiters,
            f"إعادة {next_attempt}/{MAX_IMAGE_ATTEMPTS}",
        )
        delay_ms = min(500 * attempt, 3000)
        QTimer.singleShot(delay_ms, lambda image_url=url: self._request_image(image_url))

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


