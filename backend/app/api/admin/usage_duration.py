from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.database import get_db_no_commit
from app.services import usage_duration_service
from app.services.config_crypto import normalize_package_name


router = APIRouter(
    tags=["Admin - Usage Duration"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/usage-durations")
async def get_usage_durations(
    package_name: str | None = Query(None, max_length=255),
    device_id: str | None = Query(None, max_length=64),
    sdk_version: str | None = Query(None, max_length=20),
    ver: str | None = Query(None, max_length=50),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_no_commit),
):
    normalized_package = normalize_package_name(package_name) if package_name else None
    try:
        data = await usage_duration_service.get_usage_durations(
            db,
            package_name=normalized_package,
            device_id=device_id,
            sdk_version=sdk_version,
            ver=ver,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": data}
