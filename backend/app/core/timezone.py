"""UTC+8 business-time helpers."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


def business_today(now: datetime | None = None) -> date:
    """Return the current calendar date in the UTC+8 business timezone."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(BUSINESS_TIMEZONE).date()


def business_day_utc_range(value: date) -> tuple[datetime, datetime]:
    """Return the UTC half-open interval for one UTC+8 business day."""
    start = datetime.combine(value, time.min, tzinfo=BUSINESS_TIMEZONE)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def serialize_business_time(value: datetime | None) -> str | None:
    """Serialize an aware datetime as an ISO 8601 UTC+8 business time."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("value must be timezone-aware")
    return value.astimezone(BUSINESS_TIMEZONE).isoformat()
