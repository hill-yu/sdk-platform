from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.timezone import business_hour_utc_range


class LogExportCreateRequest(BaseModel):
    package_names: list[str] = Field(min_length=1, max_length=50)
    export_mode: Literal["raw", "h1"] = "raw"
    sdk_version: str | None = Field(default=None, max_length=20)
    device_id: str | None = Field(default=None, max_length=64)
    log_level: Literal["debug", "info", "warn", "error"] | None = None
    date_from: date | None = None
    hour_from: int | None = Field(default=None, ge=0, le=23)
    date_to: date | None = None
    hour_to: int | None = Field(default=None, ge=0, le=23)

    @field_validator("package_names")
    @classmethod
    def normalize_packages(cls, values: list[str]) -> list[str]:
        result = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not result:
            raise ValueError("至少选择一个包名")
        if any(len(value) > 255 for value in result):
            raise ValueError("包名长度不能超过 255")
        return result

    @field_validator("device_id")
    @classmethod
    def normalize_device(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("开始日期不能晚于结束日期")
        if (self.hour_from is None) != (self.hour_to is None):
            raise ValueError("hour_from 和 hour_to 必须成对提供")
        if self.hour_from is not None and (self.date_from is None or self.date_to is None):
            raise ValueError("使用小时筛选时必须同时提供开始日期和结束日期")
        if self.date_from and self.date_to:
            try:
                business_hour_utc_range(self.date_from, self.hour_from, self.date_to, self.hour_to)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
        return self
