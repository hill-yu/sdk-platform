from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.exc import StatementError


async def _job_for_test(job):
    job.status = "running"
    job.cancel_requested_at = None
    return job


def test_worker_limits_are_bounded() -> None:
    from app.workers import log_parse_worker
    from app.services import log_parse_job_service

    assert log_parse_worker.BATCH_SIZE == log_parse_job_service.PARSE_BATCH_SIZE
    assert log_parse_worker.MAX_CONCURRENCY == log_parse_job_service.MAX_PARSE_CONCURRENCY
    assert 1 <= log_parse_worker.MAX_CONCURRENCY <= 3


def test_worker_can_be_scoped_to_the_benchmark_job(monkeypatch) -> None:
    from app.workers import log_parse_worker

    captured = {}

    class Session:
        async def rollback(self):
            pass

    async def fake_claim(_db, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(log_parse_worker, "claim_parse_job", fake_claim)

    handled = asyncio.run(log_parse_worker.run_worker_once(Session(), worker_id="benchmark", job_id=91))

    assert handled is False
    assert captured["job_id"] == 91


def test_worker_uses_claimed_id_after_batch_failure_and_rollback(monkeypatch) -> None:
    from app.workers import log_parse_worker

    class Job:
        def __init__(self):
            self.expired = False
            self.status = "running"
            self.cancel_requested_at = None

        @property
        def id(self):
            if self.expired:
                raise RuntimeError("expired ORM state")
            return 91

    class Session:
        def __init__(self):
            self.rollbacks = 0
            self.commits = 0

        async def rollback(self):
            self.rollbacks += 1

        async def commit(self):
            self.commits += 1

    job = Job()
    failures = []

    async def fake_claim(_db, **kwargs):
        return job

    async def fake_process(_db, _job_id, **kwargs):
        job.expired = True
        raise RuntimeError("batch failed")

    async def fake_mark_failed(_db, job_id, error, **kwargs):
        failures.append((job_id, error))

    monkeypatch.setattr(log_parse_worker, "claim_parse_job", fake_claim)
    monkeypatch.setattr(log_parse_worker, "process_parse_job_batch", fake_process)
    monkeypatch.setattr(log_parse_worker, "mark_parse_job_failed", fake_mark_failed)
    session = Session()

    assert asyncio.run(log_parse_worker.run_worker_once(session, worker_id="worker-1")) is True
    assert session.rollbacks == 1
    assert failures[0][0] == 91


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
    job = SimpleNamespace(id=91, status="running", cancel_requested_at=None, batch_size=17)
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
    assert calls[0][1]["batch_size"] == 17


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


def test_worker_logs_safe_failure_context_without_exception_message(monkeypatch, caplog) -> None:
    from app.workers import log_parse_worker

    class Session:
        async def rollback(self):
            pass

        async def commit(self):
            pass

    job = SimpleNamespace(id=91, status="running", cancel_requested_at=None)

    async def fake_claim(_db, **kwargs):
        return job

    async def fake_process(_db, _job_id, **kwargs):
        cause = RuntimeError("driver secret payload token=do-not-log")
        cause.sqlstate = "22001"
        raise StatementError(
            "statement failed with sensitive params",
            "INSERT ... VALUES (:token)",
            {"token": "secret-token-value"},
            cause,
        )

    async def fake_mark_failed(_db, _job_id, _error, **kwargs):
        pass

    monkeypatch.setattr(log_parse_worker, "claim_parse_job", fake_claim)
    monkeypatch.setattr(log_parse_worker, "process_parse_job_batch", fake_process)
    monkeypatch.setattr(log_parse_worker, "mark_parse_job_failed", fake_mark_failed)

    with caplog.at_level(logging.ERROR, logger=log_parse_worker.__name__):
        asyncio.run(log_parse_worker.run_worker_once(Session(), worker_id="worker-1"))

    assert "job_id=91" in caplog.text
    assert "StatementError <- RuntimeError[sqlstate=22001]" in caplog.text
    assert "secret payload" not in caplog.text
    assert "do-not-log" not in caplog.text
    assert "secret-token-value" not in caplog.text
    assert "INSERT" not in caplog.text


def test_worker_stop_finishes_and_commits_current_batch_then_releases_job(monkeypatch) -> None:
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
    stop_event = asyncio.Event()
    job = SimpleNamespace(id=91, status="running", cancel_requested_at=None)
    releases = []

    async def fake_claim(_db, **kwargs):
        return job

    async def fake_process(_db, job_id, **kwargs):
        stop_event.set()
        return SimpleNamespace(done=False)

    async def fake_release(_db, job_id, *, worker_id, now):
        releases.append((job_id, worker_id, now))

    monkeypatch.setattr(log_parse_worker, "claim_parse_job", fake_claim)
    monkeypatch.setattr(log_parse_worker, "process_parse_job_batch", fake_process)
    monkeypatch.setattr(log_parse_worker, "release_parse_job", fake_release)

    handled = asyncio.run(
        log_parse_worker.run_worker_once(
            session,
            worker_id="worker-1",
            stop_event=stop_event,
        )
    )

    assert handled is True
    assert session.commits == 3
    assert session.rollbacks == 0
    assert releases[0][0:2] == (91, "worker-1")


def test_worker_signal_handlers_only_request_stop(monkeypatch) -> None:
    from app.workers import log_parse_worker

    stop_event = asyncio.Event()
    registered = {}

    def fake_signal(signum, handler):
        registered[signum] = handler
        return signal.SIG_DFL

    monkeypatch.setattr(log_parse_worker.signal, "signal", fake_signal)
    previous = log_parse_worker.install_signal_handlers(stop_event)

    assert set(registered) == {signal.SIGTERM, signal.SIGINT}
    registered[signal.SIGTERM](signal.SIGTERM, None)
    assert stop_event.is_set()
    assert set(previous) == {signal.SIGTERM, signal.SIGINT}
