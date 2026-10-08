from datetime import date

import pytest


def test_resolve_analysis_scope_normalizes_package_and_returns_utc_half_open_range():
    from app.services.log_analysis_scope import resolve_analysis_scope

    scope = resolve_analysis_scope(
        package_name=" COM.Example.App ",
        date_from=date(2026, 10, 1),
        hour_from=8,
        date_to=date(2026, 10, 7),
        hour_to=23,
    )

    assert scope.package_name == "com.example.app"
    assert scope.range_start.isoformat() == "2026-10-01T00:00:00+00:00"
    assert scope.range_end.isoformat() == "2026-10-07T16:00:00+00:00"


@pytest.mark.parametrize(
    ("date_from", "date_to"),
    [
        (date(2026, 10, 1), date(2026, 10, 8)),
        (date(2026, 10, 8), date(2026, 10, 1)),
    ],
)
def test_resolve_analysis_scope_rejects_ranges_outside_seven_calendar_days(date_from, date_to):
    from app.services.log_analysis_scope import resolve_analysis_scope

    with pytest.raises(ValueError):
        resolve_analysis_scope(
            package_name="com.example.app",
            date_from=date_from,
            hour_from=0,
            date_to=date_to,
            hour_to=23,
        )


def test_resolve_analysis_scope_rejects_missing_package():
    from app.services.log_analysis_scope import resolve_analysis_scope

    with pytest.raises(ValueError, match="包名"):
        resolve_analysis_scope(
            package_name=" ",
            date_from=date(2026, 10, 1),
            hour_from=0,
            date_to=date(2026, 10, 1),
            hour_to=23,
        )
