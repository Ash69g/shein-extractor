from __future__ import annotations

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from shein_extractor.domain.errors import CartExtractionError
from shein_extractor.infrastructure.shein import playwright_gateway as gateway_module


class FakeResponse:
    url = "https://m.shein.com/bff-api/order/cart/share/landing"

    def json(self) -> dict[str, object]:
        return {
            "info": {
                "allProductSize": 1,
                "normalProducts": [{"goods_id": "1", "goods_sn": "sr1", "sku_code": "i1"}],
                "outStock": [],
                "unavailable": [],
            }
        }


class FakePage:
    def __init__(self, *, timeout: bool = False) -> None:
        self.url = "https://m.shein.com/cart?group_id=10&local_country=SA"
        self.callback = None
        self.timeout = timeout

    def on(self, event: str, callback) -> None:
        assert event == "response"
        self.callback = callback

    def goto(self, *args, **kwargs) -> None:
        if self.timeout:
            raise PlaywrightTimeoutError("timeout")
        self.callback(FakeResponse())

    def wait_for_timeout(self, milliseconds: int) -> None:
        raise AssertionError("payload should already be captured")


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.closed = False

    def new_page(self) -> FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.closed = False

    def new_context(self, **kwargs) -> FakeContext:
        return self.context

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser

    def launch(self, *, headless: bool) -> FakeBrowser:
        return self.browser


class FakePlaywright:
    def __init__(self, browser: FakeBrowser) -> None:
        self.chromium = FakeChromium(browser)
        self.devices = {"iPhone 13": {}}


class FakePlaywrightManager:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    def __enter__(self) -> FakePlaywright:
        return self.playwright

    def __exit__(self, *args) -> None:
        return None


def install_fake_playwright(monkeypatch, *, timeout: bool = False):
    context = FakeContext(FakePage(timeout=timeout))
    browser = FakeBrowser(context)
    manager = FakePlaywrightManager(FakePlaywright(browser))
    monkeypatch.setattr(gateway_module, "sync_playwright", lambda: manager)
    return context, browser


def test_gateway_closes_browser_after_success(monkeypatch) -> None:
    context, browser = install_fake_playwright(monkeypatch)
    result = gateway_module.PlaywrightCartGateway().extract(
        "https://onelink.shein.com/43/value",
        headless=True,
        timeout_seconds=5,
    )
    assert len(result.products) == 1
    assert result.products[0].sku_code == "sr1"
    assert context.closed and browser.closed


def test_gateway_closes_browser_after_timeout(monkeypatch) -> None:
    context, browser = install_fake_playwright(monkeypatch, timeout=True)
    with pytest.raises(CartExtractionError, match="مهلة"):
        gateway_module.PlaywrightCartGateway().extract(
            "https://onelink.shein.com/43/value",
            headless=True,
            timeout_seconds=5,
        )
    assert context.closed and browser.closed
