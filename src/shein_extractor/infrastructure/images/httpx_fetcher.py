from __future__ import annotations

from collections.abc import Callable, Iterable
import time

import httpx

from shein_extractor.application.ports import ImageFetchResult
from shein_extractor.infrastructure.images.optimizer import (
    DEFAULT_JPEG_QUALITY,
    DEFAULT_MAX_DIMENSION,
    optimize_product_image,
)


DEFAULT_HEADERS = {
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
}


class HttpxProductImageFetcher:
    def __init__(
        self,
        *,
        max_attempts: int = 10,
        timeout_seconds: float = 15,
        retry_delay_seconds: float = 0.5,
        max_image_dimension: int = DEFAULT_MAX_DIMENSION,
        jpeg_quality: int = DEFAULT_JPEG_QUALITY,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")
        if max_image_dimension < 1:
            raise ValueError("max_image_dimension must be at least 1")
        if not 1 <= jpeg_quality <= 95:
            raise ValueError("jpeg_quality must be between 1 and 95")
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self.max_image_dimension = max_image_dimension
        self.jpeg_quality = jpeg_quality
        self.transport = transport
        self.sleep = sleep

    def fetch(
        self,
        urls: Iterable[str],
        *,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ImageFetchResult:
        unique_urls = tuple(dict.fromkeys(url for url in urls if url))
        images: dict[str, bytes] = {}
        failed_urls: list[str] = []
        with httpx.Client(
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            for completed, url in enumerate(unique_urls, start=1):
                image = self._download(client, url)
                if image is None:
                    failed_urls.append(url)
                else:
                    images[url] = image
                if progress_callback is not None:
                    progress_callback(completed, len(unique_urls))
        return ImageFetchResult(images=images, failed_urls=tuple(failed_urls))

    def _download(self, client: httpx.Client, url: str) -> bytes | None:
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                content = response.content
                content_type = response.headers.get("content-type", "")
                if not content:
                    raise ValueError("empty image response")
                if content_type and not content_type.lower().startswith("image/"):
                    raise ValueError(f"unexpected content type: {content_type}")
                return optimize_product_image(
                    content,
                    max_dimension=self.max_image_dimension,
                    jpeg_quality=self.jpeg_quality,
                )
            except (httpx.HTTPError, ValueError):
                if attempt < self.max_attempts and self.retry_delay_seconds:
                    self.sleep(self.retry_delay_seconds)
        return None
