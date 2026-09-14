from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.log_analysis import AdminPreference, PackageProfile
from app.services.config_crypto import normalize_package_name

LOG_ANALYSIS_PREFERENCE_KEY = "log_analysis_columns"
LOG_ANALYSIS_COLUMNS = (
    "date",
    "package_name",
    "alias",
    "url",
    "company",
    "account",
    "user_count",
    "flow_count",
    "expected_click_count",
    "actual_click_count",
    "ad_click_count",
    "interstitial_presentation_count",
    "interstitial_click_count",
    "average_duration_ms",
    "success_rate",
    "parse_failure_count",
)
DEFAULT_LOG_ANALYSIS_COLUMNS = LOG_ANALYSIS_COLUMNS


def _profile_value(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _serialize_profile(profile: PackageProfile | None, package_name: str) -> dict[str, str]:
    return {
        "package_name": package_name,
        "alias": profile.alias if profile and profile.alias is not None else "",
        "company": profile.company if profile and profile.company is not None else "",
        "account": profile.account if profile and profile.account is not None else "",
    }


async def get_package_profile(db: AsyncSession, package_name: str) -> dict[str, str]:
    normalized = normalize_package_name(package_name)
    result = await db.execute(
        select(PackageProfile).where(PackageProfile.package_name == normalized)
    )
    return _serialize_profile(result.scalar_one_or_none(), normalized)


async def upsert_package_profile(
    db: AsyncSession,
    package_name: str,
    *,
    alias: str | None,
    company: str | None,
    account: str | None,
) -> dict[str, str]:
    normalized = normalize_package_name(package_name)
    values = {
        "package_name": normalized,
        "alias": _profile_value(alias),
        "company": _profile_value(company),
        "account": _profile_value(account),
    }
    statement = pg_insert(PackageProfile).values(values)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[PackageProfile.package_name],
            set_={
                "alias": statement.excluded.alias,
                "company": statement.excluded.company,
                "account": statement.excluded.account,
            },
        )
    )
    return {
        "package_name": normalized,
        "alias": values["alias"] or "",
        "company": values["company"] or "",
        "account": values["account"] or "",
    }


def validate_column_selection(columns: Sequence[str]) -> list[str]:
    selected = list(columns)
    if not selected:
        raise ValueError("列配置不能为空")
    if len(selected) > len(LOG_ANALYSIS_COLUMNS):
        raise ValueError("列配置超过目录总数")
    if any(not isinstance(column, str) or len(column) > 64 for column in selected):
        raise ValueError("列 ID 长度无效")
    unknown = [column for column in selected if column not in LOG_ANALYSIS_COLUMNS]
    if unknown:
        raise ValueError("列配置包含未知列")
    if len(set(selected)) != len(selected):
        raise ValueError("列配置不能重复")
    if "date" not in selected or "package_name" not in selected:
        raise ValueError("列配置必须包含 date 和 package_name")
    return selected


def _columns_response(columns: Sequence[str]) -> dict[str, list[str]]:
    return {
        "available_columns": list(LOG_ANALYSIS_COLUMNS),
        "default_columns": list(DEFAULT_LOG_ANALYSIS_COLUMNS),
        "columns": list(columns),
    }


async def get_log_analysis_columns(db: AsyncSession) -> dict[str, list[str]]:
    result = await db.execute(
        select(AdminPreference).where(
            AdminPreference.preference_key == LOG_ANALYSIS_PREFERENCE_KEY
        )
    )
    preference = result.scalar_one_or_none()
    if preference is None:
        return _columns_response(DEFAULT_LOG_ANALYSIS_COLUMNS)
    return _columns_response(validate_column_selection(preference.value))


async def save_log_analysis_columns(
    db: AsyncSession,
    columns: Sequence[str],
) -> dict[str, list[str]]:
    selected = validate_column_selection(columns)
    values = {
        "preference_key": LOG_ANALYSIS_PREFERENCE_KEY,
        "value": selected,
    }
    statement = pg_insert(AdminPreference).values(values)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AdminPreference.preference_key],
            set_={"value": statement.excluded.value},
        )
    )
    return _columns_response(selected)
