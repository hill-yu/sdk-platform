from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace


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
    job = SimpleNamespace(id=91)
    calls = []

    async def fake_claim(_db, **kwargs):
        return job

    async def fake_process(_db, job_id, **kwargs):
        calls.append((job_id, kwargs))
        return SimpleNamespace(done=len(calls) == 2)

    monkeypatch.setattr(log_parse_worker, "claim_parse_job", fake_claim)
    monkeypatch.setattr(log_parse_worker, "process_parse_job_batch", fake_process)

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
