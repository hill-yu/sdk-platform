from __future__ import annotations

from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import get_settings
from app.core.timezone import business_hour_utc_range
from app.services.config_crypto import normalize_package_name


class LogParseJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_name: str = Field(min_length=1, max_length=255)
    date_from: date
    hour_from: int = Field(ge=0, le=23)
    date_to: date
    hour_to: int = Field(ge=0, le=23)

    @field_validator("package_name")
    @classmethod
    def normalize_package(cls, value: str) -> str:
        return normalize_package_name(value)

    @model_validator(mode="after")
    def validate_range(self) -> "LogParseJobCreateRequest":
        start, end = self.utc_range()
        if end - start > timedelta(days=get_settings().LOG_PARSE_MAX_DAYS):
            raise ValueError("解析范围不能超过 7 天")
        return self

    def utc_range(self) -> tuple[datetime, datetime]:
        return business_hour_utc_range(
            self.date_from,
            self.hour_from,
            self.date_to,
            self.hour_to,
        )
