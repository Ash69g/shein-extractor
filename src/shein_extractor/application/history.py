from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from shein_extractor.application.naming import sanitize_filename_component
from shein_extractor.domain.models import CartExtraction


TIMESTAMP_PATTERN = re.compile(r"(\d{8}-\d{6})(?:-\d+)?$")


@dataclass(frozen=True)
class HistoryEntry:
    path: Path
    extraction: CartExtraction | None
    customer_name: str
    analyzed_at: datetime
    order_number: str | None = None
    error: str | None = None

    @property
    def sort_key(self) -> float:
        return self.analyzed_at.timestamp()


def timestamp_from_filename(path: Path) -> datetime | None:
    match = TIMESTAMP_PATTERN.search(path.stem)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S").astimezone()
    except ValueError:
        return None


def customer_from_filename(path: Path) -> str | None:
    match = TIMESTAMP_PATTERN.search(path.stem)
    if not match:
        return None
    prefix = path.stem[: match.start()].rstrip("-")
    if not prefix or prefix.startswith("cart-"):
        return None
    return prefix


def history_entry_from_path(path: Path) -> HistoryEntry:
    fallback_time = (
        timestamp_from_filename(path)
        or datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    )
    try:
        extraction = CartExtraction.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as error:
        return HistoryEntry(
            path=path,
            extraction=None,
            customer_name="ملف غير صالح",
            analyzed_at=fallback_time,
            error=str(error),
        )
    analyzed_at = extraction.analyzed_at or fallback_time
    if analyzed_at.tzinfo is None:
        analyzed_at = analyzed_at.astimezone()
    customer_name = extraction.customer_name or customer_from_filename(path) or "غير محدد"
    return HistoryEntry(
        path,
        extraction,
        customer_name,
        analyzed_at,
        extraction.order_number,
    )


def list_history(directory: Path) -> list[HistoryEntry]:
    directory.mkdir(parents=True, exist_ok=True)
    entries = [history_entry_from_path(path) for path in directory.glob("*.json")]
    return sorted(entries, key=lambda entry: entry.sort_key, reverse=True)


def renamed_history_target(
    path: Path,
    customer_name: str,
    order_number: str | None = None,
) -> Path:
    timestamp = timestamp_from_filename(path)
    if timestamp is None:
        timestamp = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    safe_name = sanitize_filename_component(customer_name)
    safe_order_number = sanitize_filename_component(order_number) if order_number else None
    identity = f"{safe_order_number}-{safe_name}" if safe_order_number else safe_name
    return path.with_name(f"{identity}-{timestamp.strftime('%Y%m%d-%H%M%S')}.json")


def rename_history_path(
    path: Path,
    customer_name: str,
    order_number: str | None = None,
) -> Path:
    target = renamed_history_target(path, customer_name, order_number)
    if target == path:
        return path
    if target.exists():
        raise FileExistsError(f"يوجد ملف بالاسم نفسه: {target.name}")
    path.rename(target)
    return target

