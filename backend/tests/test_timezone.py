from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.timezone import business_day_utc_range, business_hour_utc_range, business_today, serialize_business_time


def test_business_hour_range_uses_inclusive_end_hour() -> None:
    start, end = business_hour_utc_range(
        date(2026, 9, 20), 8,
        date(2026, 9, 22), 17,
    )

    assert start.isoformat() == "2026-09-20T00:00:00+00:00"
    assert end.isoformat() == "2026-09-22T10:00:00+00:00"


def test_business_hour_range_defaults_to_full_days() -> None:
    start, end = business_hour_utc_range(
        date(2026, 9, 20), None,
        date(2026, 9, 20), None,
    )

    assert end - start == timedelta(days=1)


@pytest.mark.parametrize("hours", [(8, None), (None, 17), (-1, 17), (8, 24)])
def test_business_hour_range_rejects_invalid_hours(hours: tuple[int | None, int | None]) -> None:
    with pytest.raises(ValueError):
        business_hour_utc_range(
            date(2026, 9, 20), hours[0],
            date(2026, 9, 20), hours[1],
        )


def test_business_day_utc_range_uses_utc_plus_8_boundaries() -> None:
    start, end = business_day_utc_range(date(2026, 8, 17))

    assert start == datetime(2026, 8, 16, 16, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 17, 16, 0, tzinfo=timezone.utc)


def test_serialize_business_time_converts_utc_to_utc_plus_8() -> None:
    value = datetime(2026, 8, 17, 1, 30, tzinfo=timezone.utc)

    assert serialize_business_time(value) == "2026-08-17T09:30:00+08:00"


def test_business_today_converts_aware_time_to_utc_plus_8_date() -> None:
    now = datetime(2026, 8, 16, 18, tzinfo=timezone.utc)

    assert business_today(now) == date(2026, 8, 17)


def test_business_today_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        business_today(datetime(2026, 8, 17, 1, 30))


def test_serialize_business_time_returns_none_for_missing_value() -> None:
    assert serialize_business_time(None) is None


def test_serialize_business_time_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        serialize_business_time(datetime(2026, 8, 17, 1, 30))
