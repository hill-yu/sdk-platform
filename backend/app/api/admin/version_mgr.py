from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.database import get_db, get_db_no_commit
from app.schemas.admin_schemas import VersionCreateRequest, VersionUpdateRequest
from app.services import version_service


router = APIRouter(tags=["Admin - Version"], dependencies=[Depends(require_admin_token)])


@router.get("/versions")
async def list_versions(
    platform: str | None = Query(None),
    db: AsyncSession = Depends(get_db_no_commit),
):
    return {"code": 0, "data": await version_service.list_versions(db, platform)}


@router.post("/versions")
async def create_version(payload: VersionCreateRequest, db: AsyncSession = Depends(get_db)):
    return {"code": 0, "data": await version_service.create_version(db, payload.model_dump())}


@router.put("/versions/{version_id}")
async def update_version(version_id: int, payload: VersionUpdateRequest, db: AsyncSession = Depends(get_db)):
    try:
        data = await version_service.update_version(db, version_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"code": 0, "data": data}
