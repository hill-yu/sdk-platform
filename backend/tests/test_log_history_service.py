from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql


START = datetime(2026, 9, 29, tzinfo=timezone.utc)
END = datetime(2026, 9, 30, tzinfo=timezone.utc)


class Result:
    def __init__(self, *, scalar=None, rows=()):
        self.scalar = scalar
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows


class Db:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


def job(**overrides):
    values = dict(id=7, status="success", total_count=1, processed_count=1, h1_count=1, failed_h1_count=0, no_h1_count=0)
    values.update(overrides)
    return SimpleNamespace(**values)


def h1(*, status="success", payload=None):
    return SimpleNamespace(event_id=1, event_server_ts=START, record_index=0, status=status, decoded_payload=payload or {"planned_click_attempts": [{}]})


def click():
    return SimpleNamespace(event_id=1, event_server_ts=START, record_index=0, attempt_index=0)


def test_historical_metrics_compile_only_stage_tables_and_job_id():
    from app.models.log_metrics import H1DeclarationStage, LogClickAttemptStage
    from app.services.log_metrics_service import get_overview

    db = Db([
        type("MappingResult", (), {"mappings": lambda self: self, "one": lambda self: {
            "declaration_count": 1, "planned_click_count": 1, "actual_click_count": 0,
            "response_success_count": 0, "plan_mismatch_count": 0,
            "interstitial_presentation_count": 0, "interstitial_click_count": 0, "interstitial_close_count": 0,
        }})(),
        type("RowsResult", (), {"all": lambda self: []})(),
    ])
    asyncio.run(get_overview(db, package_name="com.example.app", range_start=START, range_end=END, h1_model=H1DeclarationStage, click_model=LogClickAttemptStage, job_id=7))
    sql = "\n".join(str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})) for statement in db.statements)
    assert "sdk_log_h1_declaration_stage" in sql
    assert "sdk_log_click_attempt_stage" in sql
    assert "sdk_log_h1_declarations" not in sql
    assert "sdk_log_click_attempts" not in sql
    assert "job_id = 7" in sql


def test_history_rejects_incomplete_stage_counts_and_orphan_clicks():
    from app.services.log_history_service import HistoricalParseUnavailable, get_complete_job_context

    incomplete = Db([Result(scalar=job(h1_count=2)), Result(rows=[h1()]), Result(rows=[click()])])
    try:
        asyncio.run(get_complete_job_context(incomplete, 7))
    except HistoricalParseUnavailable as exc:
        assert "H1" in str(exc)
    else:
        raise AssertionError("incomplete history must be unavailable")

    orphan = Db([Result(scalar=job()), Result(rows=[h1()]), Result(rows=[SimpleNamespace(event_id=9, event_server_ts=START, record_index=0, attempt_index=0)])])
    try:
        asyncio.run(get_complete_job_context(orphan, 7))
    except HistoricalParseUnavailable as exc:
        assert "孤儿" in str(exc)
    else:
        raise AssertionError("orphan click history must be unavailable")


def test_history_accepts_zero_h1_snapshot_without_decoder_fallback():
    from app.services.log_history_service import get_complete_job_context

    db = Db([Result(scalar=job(h1_count=0, no_h1_count=1)), Result(rows=[]), Result(rows=[])])
    result = asyncio.run(get_complete_job_context(db, 7))
    assert result.id == 7
