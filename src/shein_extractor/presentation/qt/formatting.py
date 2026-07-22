from __future__ import annotations


def truncate_product_name(value: str | None, limit: int = 100) -> str:
    name = (value or "—").strip()
    if len(name) <= limit:
        return name
    return f"{name[:limit].rstrip()}…"

