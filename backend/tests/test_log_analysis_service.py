from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
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
                current = self.profile or SimpleNamespace(alias=None, company=None, account=None)
                self.profile = SimpleNamespace(
                    package_name=params["package_name"],
                    alias=params.get("alias", current.alias),
                    company=params.get("company", current.company),
                    account=params.get("account", current.account),
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

    async def flush(self):
        pass


class Result:
    def __init__(self, *, rows=(), scalar=None, scalar_value=None):
        self.rows = list(rows)
        self.scalar = scalar
        self.scalar_value = scalar_value

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar

    def scalar_one_or_none(self):
        return self.scalar_value

    def scalars(self):
        return self


class AnalysisDb:
    def __init__(self, results=()):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.flushed = False

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        return self.results.pop(0)

    def add(self, record):
        record.id = 77
        self.added.append(record)

    async def flush(self):
        self.flushed = True


ANALYSIS_DATE = date(2026, 8, 17)
EVENT_TS = datetime(2026, 8, 17, 1, 2, 3, tzinfo=timezone.utc)


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
            updates={
                "alias": " Alias ",
                "company": " Example Company ",
                "account": " account-1 ",
            },
        )
    )
    second = asyncio.run(
        log_analysis_service.upsert_package_profile(
            db,
            "com.example.app",
            updates={"alias": "New Alias", "company": "", "account": ""},
        )
    )
    third = asyncio.run(
        log_analysis_service.upsert_package_profile(
            db,
            "com.example.app",
            updates={"alias": "", "company": "", "account": ""},
        )
    )

    assert first["package_name"] == second["package_name"] == third["package_name"] == "com.example.app"
    assert second["alias"] == "New Alias"
    assert second["company"] == ""
    assert third["alias"] == ""
    assert db.profile.alias is None
    assert db.profile.company is None
    assert db.profile.account is None
    profile_sql = str(next(statement for statement in reversed(db.statements) if isinstance(statement, Insert)).compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (package_name) DO UPDATE" in profile_sql
    assert len([statement for statement in db.statements if isinstance(statement, Insert)]) == 3


def test_partial_profile_update_does_not_overwrite_omitted_fields():
    from app.services import log_analysis_service

    existing = SimpleNamespace(
        package_name="com.example.app",
        alias="Old",
        company="Keep Co",
        account="keep-account",
    )
    db = FakeDb(profile=existing)
    result = asyncio.run(
        log_analysis_service.upsert_package_profile(
            db,
            "com.example.app",
            updates={"alias": "New"},
        )
    )

    statement = next(item for item in db.statements if isinstance(item, Insert))
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "alias = excluded.alias" in compiled.lower()
    assert "company = excluded.company" not in compiled.lower()
    assert "account = excluded.account" not in compiled.lower()
    assert result == {
        "package_name": "com.example.app",
        "alias": "New",
        "company": "Keep Co",
        "account": "keep-account",
    }


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


def test_summary_uses_database_aggregates_and_preserves_metric_sample_rules():
    from app.services import log_analysis_service

    row = {
        "date": ANALYSIS_DATE,
        "package_name": "com.example.app",
        "alias": None,
        "company": "Example",
        "account": None,
        "primary_url": "https://one.example",
        "url_count": 2,
        "user_count": 2,
        "flow_count": 3,
        "expected_click_count": 5,
        "actual_click_count": 4,
        "ad_click_count": 2,
        "interstitial_presentation_count": 3,
        "interstitial_click_count": 1,
        "average_duration_ms": 1500.0,
        "duration_sample_count": 2,
        "success_rate": 0.5,
        "success_count": 1,
        "success_sample_count": 2,
        "failed_count": 1,
        "unsupported_count": 1,
        "parse_failure_count": 2,
    }
    db = AnalysisDb([Result(scalar=1), Result(rows=[row])])

    result = asyncio.run(
        log_analysis_service.get_log_analysis_summary(
            db,
            date_from=ANALYSIS_DATE,
            date_to=ANALYSIS_DATE,
            page=1,
            page_size=20,
            sort_by="date",
            sort_order="desc",
        )
    )

    item = result["items"][0]
    assert result["total"] == 1
    assert item["user_count"] == 2
    assert item["duration_sample_count"] == 2
    assert item["success_sample_count"] == 2
    assert item["success_rate"] == 0.5
    assert item["failed_count"] == 1
    assert item["unsupported_count"] == 1
    assert item["parse_failure_count"] == 2
    assert item["alias"] == ""
    sql = "\n".join(str(statement.compile(dialect=postgresql.dialect())) for statement in db.statements)
    assert "AT TIME ZONE 'Asia/Shanghai'" in sql
    assert "GROUP BY" in sql
    assert "count(distinct" in sql.lower()
    assert "avg(" in sql.lower()
    assert "AS success_rate" in sql
    assert "decoded_payload" not in sql


def test_summary_rejects_unbounded_date_span_and_invalid_sort():
    from app.services import log_analysis_service

    for kwargs in (
        {"date_from": date(2026, 1, 1), "date_to": date(2026, 2, 15)},
        {"date_from": ANALYSIS_DATE, "date_to": ANALYSIS_DATE, "sort_by": "decoded_payload"},
        {"date_from": ANALYSIS_DATE, "date_to": ANALYSIS_DATE, "sort_order": "sideways"},
    ):
        with pytest.raises(ValueError):
            asyncio.run(log_analysis_service.get_log_analysis_summary(AnalysisDb(), **kwargs))


def test_details_use_same_business_day_boundary_and_never_return_raw_extra():
    from app.services import log_analysis_service

    row = {
        "event_id": 7,
        "event_server_ts": EVENT_TS,
        "record_index": 0,
        "package_name": "com.example.app",
        "device_id": None,
        "status": "unsupported",
        "decoder_version": "1.0.0",
        "url": None,
        "decoded_payload": {"final_reason": "unknown"},
        "parse_error": None,
        "parsed_at": EVENT_TS,
    }
    db = AnalysisDb([Result(scalar=1), Result(rows=[row])])
    result = asyncio.run(
        log_analysis_service.get_log_analysis_details(
            db,
            target_date=ANALYSIS_DATE,
            package_name="COM.EXAMPLE.APP",
            page=1,
            page_size=20,
        )
    )

    assert result["items"][0]["event_id"] == 7
    assert "extra" not in result["items"][0]
    sql = "\n".join(str(statement.compile(dialect=postgresql.dialect())) for statement in db.statements)
    assert "AT TIME ZONE 'Asia/Shanghai'" in sql
    assert "sdk_events.payload" not in sql


def test_single_detail_requires_composite_key_and_returns_raw_extra_only_here():
    from app.services import log_analysis_service

    decoded = SimpleNamespace(
        event_id=7,
        event_server_ts=EVENT_TS,
        record_index=0,
        package_name="com.example.app",
        device_id="device-1",
        status="success",
        decoder_version="1.0.0",
        decoded_payload={"final_reason": "done"},
        parsed_at=EVENT_TS,
    )
    original = SimpleNamespace(
        id=7,
        server_ts=EVENT_TS,
        payload={"extra": "H1|redacted-test"},
    )
    db = AnalysisDb([Result(scalar_value=decoded), Result(scalar_value=original)])
    result = asyncio.run(
        log_analysis_service.get_log_analysis_detail(
            db,
            event_id=7,
            event_server_ts=EVENT_TS,
            record_index=0,
        )
    )
    assert result["record_index"] == 0
    assert result["extra"] == "H1|redacted-test"


def test_reparse_requires_scope_and_only_creates_pending_job():
    from app.services import log_analysis_service

    with pytest.raises(ValueError):
        asyncio.run(
            log_analysis_service.create_reparse_job(
                AnalysisDb(),
                date_from=None,
                date_to=None,
                package_name=None,
                status=None,
                decoder_version_before=None,
                created_by="admin-hash",
            )
        )

    db = AnalysisDb()
    job = asyncio.run(
        log_analysis_service.create_reparse_job(
            db,
            date_from=ANALYSIS_DATE,
            date_to=ANALYSIS_DATE,
            package_name="COM.EXAMPLE.APP",
            status="failed",
            decoder_version_before=None,
            created_by="admin-hash",
        )
    )
    assert db.flushed is True
    assert db.added[0].status == "pending"
    assert db.added[0].package_name == "com.example.app"
    assert job["id"] == 77
    assert job["status"] == "pending"
