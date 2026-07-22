from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import ConsoleMessage, Frame, Request, Response
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DEFAULT_URL = "https://onelink.shein.com/43/5vz3b3lgwdi4"
REPORT_DIRECTORY = Path("diagnostics")


def validate_shein_url(value: str) -> str:
    parsed = urlparse(value.strip())
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        raise argparse.ArgumentTypeError("The URL must use http or https.")
    if hostname != "shein.com" and not hostname.endswith(".shein.com"):
        raise argparse.ArgumentTypeError("The URL must belong to shein.com.")
    return value.strip()


def resolve_with_http(url: str) -> dict[str, object]:
    result: dict[str, object] = {
        "final_url": None,
        "status_code": None,
        "redirects": [],
        "error": None,
    }
    headers = {
        "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
            "Mobile/15E148 Safari/604.1"
        ),
    }

    try:
        with httpx.Client(follow_redirects=True, headers=headers, timeout=30) as client:
            response = client.get(url)
        result["final_url"] = str(response.url)
        result["status_code"] = response.status_code
        result["redirects"] = [
            {
                "status_code": item.status_code,
                "url": str(item.url),
                "location": item.headers.get("location"),
            }
            for item in response.history
        ]
    except httpx.HTTPError as error:
        result["error"] = f"{type(error).__name__}: {error}"

    return result


def parse_bridge_url(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return {
        "url": url,
        "link": query.get("link", [None])[0],
        "localcountry": query.get("localcountry", [None])[0],
        "shc": query.get("shc", [None])[0],
        "url_from": query.get("url_from", [None])[0],
        "onelink": query.get("onelink", [None])[0],
        "request_id": query.get("requestId", [None])[0],
    }


def inspect_with_browser(url: str, *, headless: bool, wait_seconds: float) -> dict[str, object]:
    navigation_urls: list[str] = []
    shein_responses: list[dict[str, object]] = []
    document_snapshots: list[dict[str, object]] = []
    api_responses: list[dict[str, object]] = []
    console_messages: list[dict[str, str]] = []
    failed_requests: list[dict[str, object]] = []
    bridge_urls: list[str] = []
    result: dict[str, object] = {
        "final_url": None,
        "title": None,
        "navigation_urls": navigation_urls,
        "bridge": None,
        "document_snapshots": document_snapshots,
        "api_responses": api_responses,
        "shein_responses": shein_responses,
        "console_messages": console_messages,
        "failed_requests": failed_requests,
        "dom": None,
        "screenshot": None,
        "error": None,
    }

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            device = playwright.devices["iPhone 13"]
            context = browser.new_context(
                **device,
                locale="ar-SA",
                timezone_id="Asia/Riyadh",
                extra_http_headers={"Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8"},
            )
            page = context.new_page()

            def record_navigation(frame: Frame) -> None:
                frame_url = frame.url
                if frame_url and frame_url not in navigation_urls:
                    navigation_urls.append(frame_url)
                if "/h5/sharejump/appjump" in frame_url and frame_url not in bridge_urls:
                    bridge_urls.append(frame_url)

            def record_response(response: Response) -> None:
                response_url = response.url
                if "shein" not in response_url.lower():
                    return
                if len(shein_responses) >= 500:
                    return
                shein_responses.append(
                    {
                        "status": response.status,
                        "resource_type": response.request.resource_type,
                        "url": response_url,
                    }
                )

            def record_finished_document(request: Request) -> None:
                if "shein" not in request.url.lower():
                    return
                try:
                    response = request.response()
                    if response is None:
                        return
                    content_type = response.headers.get("content-type", "").lower()
                    is_text_response = any(
                        value in content_type
                        for value in ("json", "text", "javascript", "xml", "html")
                    )
                    if request.resource_type in {"xhr", "fetch"} and not is_text_response:
                        return
                    body = response.text()
                    if request.resource_type == "document" and len(document_snapshots) < 10:
                        document_snapshots.append(
                            {
                                "status": response.status,
                                "url": response.url,
                                "content_type": content_type,
                                "body": body[:2_000_000],
                                "body_truncated": len(body) > 2_000_000,
                            }
                        )
                    elif request.resource_type in {"xhr", "fetch"} and len(api_responses) < 100:
                        api_responses.append(
                            {
                                "status": response.status,
                                "method": request.method,
                                "url": response.url,
                                "content_type": content_type,
                                "body": body[:500_000],
                                "body_truncated": len(body) > 500_000,
                            }
                        )
                except PlaywrightError as error:
                    target = document_snapshots if request.resource_type == "document" else api_responses
                    target.append({"url": request.url, "error": f"{type(error).__name__}: {error}"})
                except UnicodeError:
                    return

            def record_console(message: ConsoleMessage) -> None:
                if len(console_messages) >= 200:
                    return
                console_messages.append({"type": message.type, "text": message.text})

            def record_failed_request(request: Request) -> None:
                if len(failed_requests) >= 200:
                    return
                failed_requests.append(
                    {
                        "method": request.method,
                        "resource_type": request.resource_type,
                        "url": request.url,
                        "failure": request.failure,
                    }
                )

            page.on("framenavigated", record_navigation)
            page.on("response", record_response)
            page.on("requestfinished", record_finished_document)
            page.on("console", record_console)
            page.on("requestfailed", record_failed_request)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            except PlaywrightTimeoutError as error:
                result["error"] = f"TimeoutError: {error}"

            page.wait_for_timeout(int(wait_seconds * 1000))
            result["final_url"] = page.url
            result["title"] = page.title()
            if bridge_urls:
                result["bridge"] = parse_bridge_url(bridge_urls[0])

            page_html = page.content()
            body_text = page.locator("body").inner_text(timeout=5_000)
            button_texts = [text.strip() for text in page.get_by_role("button").all_inner_texts()]
            result["dom"] = {
                "html": page_html[:2_000_000],
                "html_truncated": len(page_html) > 2_000_000,
                "body_text": body_text[:200_000],
                "body_text_truncated": len(body_text) > 200_000,
                "button_texts": [text for text in button_texts if text],
                "goods_id_candidates": sorted(set(re.findall(r"goods[_-]?id[=\"': ]+(\d+)", page_html, re.I))),
            }

            REPORT_DIRECTORY.mkdir(exist_ok=True)
            screenshot_name = f"final-page-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.png"
            screenshot_path = REPORT_DIRECTORY / screenshot_name
            page.screenshot(path=str(screenshot_path), full_page=True)
            result["screenshot"] = str(screenshot_path.resolve())
            context.close()
            browser.close()
    except PlaywrightError as error:
        result["error"] = f"{type(error).__name__}: {error}"

    return result


def write_report(report: dict[str, object]) -> Path:
    REPORT_DIRECTORY.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_path = REPORT_DIRECTORY / f"link-report-{timestamp}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose a SHEIN shared link.")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, type=validate_shein_url)
    parser.add_argument("--headless", action="store_true", help="Hide the browser window.")
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=15,
        help="Seconds to wait after the initial page load.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(f"Input URL: {args.url}")
    print("1/2 Resolving HTTP redirects...")
    http_result = resolve_with_http(args.url)
    print(f"HTTP final URL: {http_result['final_url']}")

    print("2/2 Inspecting the link with Chromium...")
    browser_result = inspect_with_browser(
        args.url,
        headless=args.headless,
        wait_seconds=args.wait_seconds,
    )
    print(f"Browser final URL: {browser_result['final_url']}")
    bridge = browser_result.get("bridge")
    if isinstance(bridge, dict):
        print(f"Bridge URL: {bridge.get('url')}")

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "input_url": args.url,
        "http": http_result,
        "browser": browser_result,
    }
    report_path = write_report(report)
    print(f"Report saved to: {report_path.resolve()}")


if __name__ == "__main__":
    main()
