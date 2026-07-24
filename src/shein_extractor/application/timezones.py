from __future__ import annotations

from datetime import datetime, timedelta, timezone


GMT_PLUS_3 = timezone(timedelta(hours=3), name="GMT+3")


def gmt_plus_3_time(value: datetime | None = None) -> datetime:
    """Return an aware datetime in the business timezone used for saved files."""
    if value is None:
        return datetime.now(GMT_PLUS_3)
    if value.tzinfo is None:
        return value.replace(tzinfo=GMT_PLUS_3)
    return value.astimezone(GMT_PLUS_3)
