from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace


async def _job_for_test(job):
    job.status = "running"
    job.cancel_requested_at = None
    return job


def test_worker_limits_are_bounded() -> None:
    from app.workers import log_parse_worker

    assert log_parse_worker.BATCH_SIZE == 200
    assert 1 <= log_parse_worker.MAX_CONCURRENCY <= 3


def test_worker_commits_each_batch_and_resumes_until_done(monkeypatch) -> None:
    from app.workers import log_parse_worker

    class Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    session = Session()
    job = SimpleNamespace(id=91, status="running", cancel_requested_at=None)
    calls = []

    async def fake_claim(_db, **kwargs):
        return job

    async def fake_process(_db, job_id, **kwargs):
        calls.append((job_id, kwargs))
        return SimpleNamespace(done=len(calls) == 2)

    async def fake_get(_db, _job_id):
        return await _job_for_test(job)

    monkeypatch.setattr(log_parse_worker, "claim_parse_job", fake_claim)
    monkeypatch.setattr(log_parse_worker, "process_parse_job_batch", fake_process)
    monkeypatch.setattr(log_parse_worker, "get_parse_job", fake_get)

    handled = asyncio.run(
        log_parse_worker.run_worker_once(
            session,
            worker_id="worker-1",
            now=datetime(2026, 9, 30, 1, tzinfo=timezone.utc),
        )
    )

    assert handled is True
    assert session.commits == 3
    assert session.rollbacks == 0
    assert calls[0][1]["batch_size"] == 200


def test_worker_refreshes_real_time_before_each_batch(monkeypatch) -> None:
    from app.workers import log_parse_worker

    class Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    session = Session()
    job = SimpleNamespace(id=91, status="running", cancel_requested_at=None)
    times = iter(
        [
            datetime(2026, 9, 30, 1, tzinfo=timezone.utc),
            datetime(2026, 9, 30, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 9, 30, 1, 2, tzinfo=timezone.utc),
        ]
    )
    calls = []

    async def fake_claim(_db, **kwargs):
        return job

    async def fake_process(_db, job_id, **kwargs):
        calls.append(kwargs["now"])
        return SimpleNamespace(done=len(calls) == 2)

    async def fake_get(_db, _job_id):
        return await _job_for_test(job)

    monkeypatch.setattr(log_parse_worker, "claim_parse_job", fake_claim)
    monkeypatch.setattr(log_parse_worker, "process_parse_job_batch", fake_process)
    monkeypatch.setattr(log_parse_worker, "get_parse_job", fake_get)
    monkeypatch.setattr(log_parse_worker, "utc_now", lambda: next(times))

    asyncio.run(log_parse_worker.run_worker_once(session, worker_id="worker-1"))

    assert calls == [
        datetime(2026, 9, 30, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 30, 1, 2, tzinfo=timezone.utc),
    ]


def test_worker_marks_unexpected_batch_failure_and_cleans_up(monkeypatch) -> None:
    from app.workers import log_parse_worker

    class Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    session = Session()
    job = SimpleNamespace(id=91, status="running", cancel_requested_at=None)
    failures = []

    async def fake_claim(_db, **kwargs):
        return job

    async def fake_process(_db, job_id, **kwargs):
        raise RuntimeError("secret payload")

    async def fake_mark_failed(_db, job_id, error, **kwargs):
        failures.append((job_id, error, kwargs["now"]))

    monkeypatch.setattr(log_parse_worker, "claim_parse_job", fake_claim)
    monkeypatch.setattr(log_parse_worker, "process_parse_job_batch", fake_process)
    monkeypatch.setattr(log_parse_worker, "mark_parse_job_failed", fake_mark_failed)

    handled = asyncio.run(log_parse_worker.run_worker_once(session, worker_id="worker-1"))

    assert handled is True
    assert session.commits == 2
    assert session.rollbacks == 1
    assert failures[0][0] == 91
    assert isinstance(failures[0][1], RuntimeError)
