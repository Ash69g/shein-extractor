from __future__ import annotations

from urllib.parse import urlparse


def validate_shein_url(value: str) -> str:
    url = value.strip()
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("يجب أن يبدأ الرابط بـ http أو https.")
    if hostname != "shein.com" and not hostname.endswith(".shein.com"):
        raise ValueError("الرابط لا ينتمي إلى نطاق SHEIN.")
    return url
