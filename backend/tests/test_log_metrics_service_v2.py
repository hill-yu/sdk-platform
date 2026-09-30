from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql


START = datetime(2026, 9, 29, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 30, 0, tzinfo=timezone.utc)


class Result:
    def __init__(self, *, mapping=None, rows=()):
        self.mapping = mapping
        self.rows = list(rows)

    def mappings(self):
        return self

    def one(self):
        return self.mapping

    def scalar_one(self):
        if self.mapping is None:
            return 0
        return next(iter(self.mapping.values()))

    def all(self):
        return self.rows

    def scalars(self):
        return self


class MetricsDb:
    def __init__(self, results=()):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if self.results:
            return self.results.pop(0)
        return Result(mapping={})


def test_metric_filters_use_one_package_and_half_open_utc_range():
    from app.services.log_metrics_service import build_metric_filters

    filters = build_metric_filters(
        package_name="com.example.app",
        range_start=START,
        range_end=END,
    )
    sql = " AND ".join(
        str(item.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for item in filters
    )
    assert "package_name = 'com.example.app'" in sql
    assert "event_server_ts >=" in sql
    assert "event_server_ts <" in sql


def test_overview_returns_distinct_click_metrics_and_null_interstitial_rates():
    from app.services.log_metrics_service import get_overview

    db = MetricsDb(
        [
            Result(
                mapping={
                    "declaration_count": 2,
                    "planned_click_count": 3,
                    "actual_click_count": 1,
                    "response_success_count": 1,
                    "plan_mismatch_count": 1,
                    "interstitial_presentation_count": 0,
                    "interstitial_click_count": 2,
                    "interstitial_close_count": 0,
                }
            ),
            Result(
                rows=[
                    SimpleNamespace(
                        target_kind="banner",
                        planned_count=2,
                        actual_count=1,
                        success_count=1,
                        failure_count=1,
                    ),
                    SimpleNamespace(
                        target_kind="web_element",
                        planned_count=1,
                        actual_count=0,
                        success_count=0,
                        failure_count=1,
                    ),
                ]
            ),
        ]
    )

    result = asyncio.run(
        get_overview(
            db,
            package_name="com.example.app",
            range_start=START,
            range_end=END,
        )
    )

    assert result["declaration_count"] == 2
    assert result["planned_click_count"] == 3
    assert result["actual_click_count"] == 1
    assert result["response_success_count"] == 1
    assert result["plan_mismatch_count"] == 1
    assert result["interstitial_close_rate"] is None
    assert result["interstitial_non_close_click_rate"] is None
    assert result["target_breakdown"]["banner"]["success_rate"] == 0.5


def test_config_and_failure_breakdowns_keep_unknown_and_failure_shares():
    from app.services.log_metrics_service import get_config_breakdown, get_failure_breakdown

    config_db = MetricsDb(
        [Result(mapping={"total_count": 4}), Result(rows=[
            SimpleNamespace(config_id=1004, declaration_count=3),
            SimpleNamespace(config_id=None, declaration_count=1),
        ])]
    )
    configs = asyncio.run(
        get_config_breakdown(
            config_db,
            package_name="com.example.app",
            range_start=START,
            range_end=END,
        )
    )
    assert configs["items"] == [
        {"config_id": 1004, "declaration_count": 3, "share": 0.75},
        {"config_id": "unknown", "declaration_count": 1, "share": 0.25},
    ]

    failure_db = MetricsDb(
        [Result(mapping={"total_failures": 4}), Result(rows=[
            SimpleNamespace(failure_category="timeout", failure_count=3),
            SimpleNamespace(failure_category="未知原因", failure_count=1),
        ])]
    )
    failures = asyncio.run(
        get_failure_breakdown(
            failure_db,
            package_name="com.example.app",
            range_start=START,
            range_end=END,
        )
    )
    assert failures == [
        {"failure_category": "timeout", "failure_count": 3, "share": 0.75},
        {"failure_category": "未知原因", "failure_count": 1, "share": 0.25},
    ]


def test_h1_details_are_paginated_and_include_click_attempts():
    from app.services.log_metrics_service import get_h1_details

    h1 = SimpleNamespace(
        event_id=7,
        event_server_ts=START,
        record_index=1,
        package_name="com.example.app",
        device_id="device-1",
        sdk_version="1.0.3",
        config_id=None,
        declared_click_count=1,
        status="success",
    )
    click = SimpleNamespace(
        event_id=7,
        event_server_ts=START,
        record_index=1,
        attempt_index=1,
        target_kind="banner",
        did_click=True,
        navigation_code=1,
        failure_category=None,
    )
    db = MetricsDb([Result(mapping={"total_count": 1}), Result(rows=[h1]), Result(rows=[click])])
    result = asyncio.run(
        get_h1_details(
            db,
            package_name="com.example.app",
            range_start=START,
            range_end=END,
            page=1,
            page_size=20,
        )
    )
    assert result["total"] == 1
    assert result["items"][0]["click_attempts"][0]["navigation_code"] == 1
