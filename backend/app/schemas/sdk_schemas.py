"""
SDK 接口 Pydantic 请求/响应模型
"""
from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator


# ============================================================
# 点击事件
# ============================================================

class ClickEvent(BaseModel):
    """单条点击事件"""
    type: str = "click"
    page: Optional[str] = None
    element: Optional[str] = None
    position: Optional[dict] = None
    timestamp: Optional[int] = None
    extra: Optional[dict] = Field(default_factory=dict)


class ClickReportRequest(BaseModel):
    """点击上报请求"""
    app_id: str
    device_id: str
    sdk_version: Optional[str] = None
    session_id: Optional[str] = None
    events: list[ClickEvent] = Field(..., min_length=1, max_length=100)


class ClickReportResponse(BaseModel):
    """点击上报响应"""
    accepted: int = 0
    rejected: int = 0


# ============================================================
# 日志事件
# ============================================================

VALID_LOG_LEVELS = {"debug", "info", "warn", "error"}


class LogEntry(BaseModel):
    """单条日志"""
    level: str
    tag: Optional[str] = None
    message: str
    timestamp: Optional[int] = None
    extra: Optional[dict] = Field(default_factory=dict)

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in VALID_LOG_LEVELS:
            raise ValueError(f"level must be one of {VALID_LOG_LEVELS}")
        return v_lower


class LogReportRequest(BaseModel):
    """日志上报请求"""
    app_id: str
    device_id: str
    sdk_version: Optional[str] = None
    logs: list[LogEntry] = Field(..., min_length=1, max_length=100)


class LogReportResponse(BaseModel):
    """日志上报响应"""
    accepted: int = 0
    rejected: int = 0


# ============================================================
# 统一响应
# ============================================================

class ApiResponse(BaseModel):
    """统一 API 响应格式"""
    code: int = 0
    message: str = "ok"
    data: Optional[Any] = None
