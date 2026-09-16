from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class LogExportCreateRequest(BaseModel):
    package_names: list[str] = Field(min_length=1, max_length=50)
    device_id: str | None = Field(default=None, max_length=64)
    log_level: Literal["debug", "info", "warn", "error"] | None = None
    date_from: date | None = None
    date_to: date | None = None

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
        return self
