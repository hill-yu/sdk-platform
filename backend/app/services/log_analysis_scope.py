"""Canonical validation and UTC resolution for explicit log analysis scopes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.core.timezone import business_hour_utc_range
from app.services.config_crypto import normalize_package_name


MAX_ANALYSIS_CALENDAR_DAYS = 7


@dataclass(frozen=True)
class AnalysisScope:
    package_name: str
    range_start: datetime
    range_end: datetime


def resolve_analysis_scope(
    *,
    package_name: str,
    date_from: date,
    hour_from: int,
    date_to: date,
    hour_to: int,
) -> AnalysisScope:
    """Normalize a Beijing date/hour scope into a UTC half-open range."""
    normalized_package = normalize_package_name(package_name)
    if (date_to - date_from).days + 1 > MAX_ANALYSIS_CALENDAR_DAYS:
        raise ValueError("解析范围不能超过 7 个北京时间日")
    range_start, range_end = business_hour_utc_range(
        date_from,
        hour_from,
        date_to,
        hour_to,
    )
    return AnalysisScope(
        package_name=normalized_package,
        range_start=range_start,
        range_end=range_end,
    )
