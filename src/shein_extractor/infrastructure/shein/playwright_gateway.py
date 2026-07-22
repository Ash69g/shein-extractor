from __future__ import annotations

import json
from time import monotonic
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from shein_extractor.domain.errors import CartExtractionError, ExpiredShareLinkError
from shein_extractor.domain.models import CartExtraction
from shein_extractor.infrastructure.shein.payload_normalizer import normalize_payload


TARGET_ENDPOINT = "/bff-api/order/cart/share/landing"


def capture_failure_error(final_url: str) -> CartExtractionError:
    parsed = urlparse(final_url)
    if parsed.path.rstrip("/") == "/h5/sharejump/appjump":
        return ExpiredShareLinkError(
            "رابط مشاركة SHEIN منتهي الصلاحية أو لم يعد يحتوي سلة متاحة."
        )
    return CartExtractionError(
        "تعذر التقاط بيانات سلة SHEIN قبل انتهاء المهلة. "
        "تحقق من الرابط والاتصال ثم أعد المحاولة."
    )


class PlaywrightCartGateway:
    def extract(
        self,
        url: str,
        *,
        headless: bool,
        timeout_seconds: float,
    ) -> CartExtraction:
        captured_payload: dict[str, object] | None = None
        final_url = url
        with sync_playwright() as playwright:
            browser = None
            context = None
            try:
                browser = playwright.chromium.launch(headless=headless)
                context = browser.new_context(
                    **playwright.devices["iPhone 13"],
                    locale="ar-SA",
                    timezone_id="Asia/Riyadh",
                    extra_http_headers={"Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8"},
                )
                page = context.new_page()

                def capture_response(response: Response) -> None:
                    nonlocal captured_payload
                    if TARGET_ENDPOINT not in response.url:
                        return
                    try:
                        value = response.json()
                    except (
                        PlaywrightError,
                        json.JSONDecodeError,
                        UnicodeDecodeError,
                        ValueError,
                    ):
                        return
                    if isinstance(value, dict):
                        captured_payload = value

                page.on("response", capture_response)
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(timeout_seconds * 1000),
                )
                deadline = monotonic() + timeout_seconds
                while captured_payload is None and monotonic() < deadline:
                    page.wait_for_timeout(250)
                final_url = page.url
            except PlaywrightTimeoutError as error:
                raise CartExtractionError(
                    "انتهت مهلة فتح رابط SHEIN قبل اكتمال التحليل."
                ) from error
            except PlaywrightError as error:
                raise CartExtractionError(
                    "تعذر تشغيل Chromium أو الوصول إلى رابط SHEIN."
                ) from error
            finally:
                if context is not None:
                    try:
                        context.close()
                    except PlaywrightError:
                        pass
                if browser is not None:
                    try:
                        browser.close()
                    except PlaywrightError:
                        pass
        if captured_payload is None:
            raise capture_failure_error(final_url)
        return normalize_payload(url, final_url, captured_payload)
