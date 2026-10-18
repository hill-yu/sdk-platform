"""Read-only access to complete, job-pinned parse snapshots."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.log_analysis import LogReparseJob
from app.models.log_metrics import H1DeclarationStage, LogClickAttemptStage
from app.services.log_parse_job_service import serialize_parse_job


class HistoricalParseUnavailable(LookupError):
    """The requested job is not a complete, readable historical snapshot."""


async def list_parse_jobs(
    db: AsyncSession,
    *,
    package_name: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, object]:
    if page < 1 or page_size < 1 or page_size > 50:
        raise ValueError("分页参数无效")
    filters = [LogReparseJob.status == "success"]
    if package_name:
        filters.append(LogReparseJob.package_name == package_name)
    total = int((await db.execute(select(func.count(LogReparseJob.id)).where(*filters))).scalar_one() or 0)
    rows = (await db.execute(
        select(LogReparseJob)
        .where(*filters)
        .order_by(LogReparseJob.created_at.desc(), LogReparseJob.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )).scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": [serialize_parse_job(row) for row in rows]}


async def get_complete_job_context(db: AsyncSession, job_id: int) -> LogReparseJob:
    job = (await db.execute(select(LogReparseJob).where(LogReparseJob.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HistoricalParseUnavailable("解析任务不存在")
    if job.status != "success":
        raise HistoricalParseUnavailable("该解析任务尚未生成可读取的历史快照")
    if min(job.total_count, job.processed_count, job.h1_count, job.failed_h1_count, job.no_h1_count) < 0:
        raise HistoricalParseUnavailable("历史解析任务计数非法")
    if job.processed_count != job.total_count:
        raise HistoricalParseUnavailable("历史解析任务尚未完整处理")

    h1_rows = (await db.execute(
        select(H1DeclarationStage).where(H1DeclarationStage.job_id == job_id)
    )).scalars().all()
    click_rows = (await db.execute(
        select(LogClickAttemptStage).where(LogClickAttemptStage.job_id == job_id)
    )).scalars().all()
    h1_keys = {(row.event_id, row.event_server_ts, row.record_index) for row in h1_rows}
    click_keys = {(row.event_id, row.event_server_ts, row.record_index) for row in click_rows}
    if len(h1_rows) != job.h1_count or sum(row.status == "failed" for row in h1_rows) != job.failed_h1_count:
        raise HistoricalParseUnavailable("历史 H1 阶段数据不完整")
    if len(h1_keys) + job.no_h1_count != job.processed_count:
        raise HistoricalParseUnavailable("历史事件覆盖计数不完整")
    if any(row.status == "failed" for row in h1_rows if row.event_id is None):
        raise HistoricalParseUnavailable("历史失败 H1 记录缺少事件键")
    if any(key not in h1_keys for key in click_keys):
        raise HistoricalParseUnavailable("历史点击记录存在孤儿数据")
    if any(row.status == "failed" and (row.event_id, row.event_server_ts, row.record_index) in click_keys for row in h1_rows):
        raise HistoricalParseUnavailable("失败 H1 不应有点击记录")
    clicks_by_key: dict[tuple[object, object, object], int] = {}
    for row in click_rows:
        key = (row.event_id, row.event_server_ts, row.record_index)
        clicks_by_key[key] = clicks_by_key.get(key, 0) + 1
    for row in h1_rows:
        if row.status != "success":
            continue
        payload = row.decoded_payload
        planned = payload.get("planned_click_attempts") if isinstance(payload, dict) else None
        if not isinstance(planned, list) or clicks_by_key.get((row.event_id, row.event_server_ts, row.record_index), 0) != len(planned):
            raise HistoricalParseUnavailable("历史解码证据缺失，无法读取历史指标")
    if job.total_count == 0 and (job.processed_count or job.h1_count or job.failed_h1_count or job.no_h1_count or h1_rows or click_rows):
        raise HistoricalParseUnavailable("空历史任务包含非空阶段数据")
    if job.total_count > 0 and job.h1_count == 0 and (job.no_h1_count != job.processed_count or click_rows):
        raise HistoricalParseUnavailable("无 H1 历史任务覆盖计数不一致")
    return job
