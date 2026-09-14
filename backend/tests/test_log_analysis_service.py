from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Insert, Select


class ScalarResult:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDb:
    def __init__(self, profile=None, preference=None, *, fail=False):
        self.profile = profile
        self.preference = preference
        self.fail = fail
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, *args, **kwargs):
        if self.fail:
            raise RuntimeError("secret SQL TOKEN")
        self.statements.append(statement)
        if isinstance(statement, Select):
            entity = statement.column_descriptions[0].get("entity")
            if entity is not None and entity.__name__ == "PackageProfile":
                return ScalarResult(self.profile)
            return ScalarResult(self.preference)
        if isinstance(statement, Insert):
            params = statement.compile(dialect=postgresql.dialect()).params
            table_name = statement.table.name
            if table_name == "sdk_package_profiles":
                self.profile = SimpleNamespace(
                    package_name=params["package_name"],
                    alias=params.get("alias"),
                    company=params.get("company"),
                    account=params.get("account"),
                )
            elif table_name == "sdk_admin_preferences":
                self.preference = SimpleNamespace(
                    preference_key=params["preference_key"],
                    value=params["value"],
                )
            return ScalarResult()
        raise AssertionError(f"unexpected statement: {statement}")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def test_log_analysis_column_catalog_is_exact_and_ordered():
    from app.services.log_analysis_service import LOG_ANALYSIS_COLUMNS

    assert LOG_ANALYSIS_COLUMNS == (
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


def test_package_profile_read_normalizes_and_serializes_null_as_empty():
    from app.services import log_analysis_service

    db = FakeDb(
        profile=SimpleNamespace(
            package_name="com.example.app",
            alias=None,
            company="Example",
            account=None,
        )
    )

    result = asyncio.run(log_analysis_service.get_package_profile(db, " COM.EXAMPLE.APP "))

    assert result == {
        "package_name": "com.example.app",
        "alias": "",
        "company": "Example",
        "account": "",
    }

    missing = asyncio.run(log_analysis_service.get_package_profile(FakeDb(), "com.example.app"))
    assert missing == {
        "package_name": "com.example.app",
        "alias": "",
        "company": "",
        "account": "",
    }


def test_package_profile_upsert_creates_updates_and_can_clear_values():
    from app.services import log_analysis_service

    db = FakeDb()
    first = asyncio.run(
        log_analysis_service.upsert_package_profile(
            db,
            "COM.Example.App",
            alias=" Alias ",
            company=" Example Company ",
            account=" account-1 ",
        )
    )
    second = asyncio.run(
        log_analysis_service.upsert_package_profile(
            db,
            "com.example.app",
            alias="New Alias",
            company="",
            account="",
        )
    )
    third = asyncio.run(
        log_analysis_service.upsert_package_profile(
            db,
            "com.example.app",
            alias="",
            company="",
            account="",
        )
    )

    assert first["package_name"] == second["package_name"] == third["package_name"] == "com.example.app"
    assert second["alias"] == "New Alias"
    assert second["company"] == ""
    assert third["alias"] == ""
    assert db.profile.alias is None
    assert db.profile.company is None
    assert db.profile.account is None
    profile_sql = str(db.statements[-1].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (package_name) DO UPDATE" in profile_sql
    assert len([statement for statement in db.statements if isinstance(statement, Insert)]) == 3


def test_package_profile_rejects_invalid_package_name():
    from app.services import log_analysis_service

    with pytest.raises(ValueError):
        asyncio.run(log_analysis_service.get_package_profile(FakeDb(), "not a package"))


def test_log_analysis_columns_use_defaults_without_writing_and_preserve_saved_order():
    from app.services import log_analysis_service

    db = FakeDb()
    defaults = asyncio.run(log_analysis_service.get_log_analysis_columns(db))
    assert defaults["available_columns"] == list(log_analysis_service.LOG_ANALYSIS_COLUMNS)
    assert defaults["default_columns"] == list(log_analysis_service.LOG_ANALYSIS_COLUMNS)
    assert defaults["columns"] == list(log_analysis_service.LOG_ANALYSIS_COLUMNS)
    assert not any(isinstance(statement, Insert) for statement in db.statements)

    selected = ["package_name", "date", "alias"]
    saved = asyncio.run(log_analysis_service.save_log_analysis_columns(db, selected))
    assert saved["columns"] == selected
    assert db.preference.value == selected
    assert "ON CONFLICT (preference_key) DO UPDATE" in str(
        db.statements[-1].compile(dialect=postgresql.dialect())
    )


@pytest.mark.parametrize(
    "columns",
    [
        [],
        ["date", "date", "package_name"],
        ["date", "unknown", "package_name"],
        ["date"],
    ],
)
def test_log_analysis_columns_reject_invalid_selection(columns):
    from app.services import log_analysis_service

    with pytest.raises(ValueError):
        asyncio.run(log_analysis_service.save_log_analysis_columns(FakeDb(), columns))


def test_log_analysis_database_error_is_not_surfaced_by_service_contract():
    from app.services import log_analysis_service

    with pytest.raises(RuntimeError, match="secret SQL TOKEN"):
        asyncio.run(log_analysis_service.get_log_analysis_columns(FakeDb(fail=True)))
