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


def business_hour_utc_range(
    date_from: date,
    hour_from: int | None,
    date_to: date,
    hour_to: int | None,
) -> tuple[datetime, datetime]:
    """Return a continuous UTC half-open interval for a UTC+8 date/hour range."""
    if hour_from is None and hour_to is None:
        start, _ = business_day_utc_range(date_from)
        _, end = business_day_utc_range(date_to)
        if end <= start:
            raise ValueError("结束时间必须晚于开始时间")
        return start, end
    if hour_from is None or hour_to is None:
        raise ValueError("hour_from 和 hour_to 必须成对提供")
    if not 0 <= hour_from <= 23 or not 0 <= hour_to <= 23:
        raise ValueError("小时必须在 0 到 23 之间")

    start = datetime.combine(date_from, time(hour_from), BUSINESS_TIMEZONE)
    end = datetime.combine(date_to, time(hour_to), BUSINESS_TIMEZONE) + timedelta(hours=1)
    if end <= start:
        raise ValueError("结束时间必须晚于开始时间")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def serialize_business_time(value: datetime | None) -> str | None:
    """Serialize an aware datetime as an ISO 8601 UTC+8 business time."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("value must be timezone-aware")
    return value.astimezone(BUSINESS_TIMEZONE).isoformat()
