from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.config_crypto import normalize_package_name
from app.services.log_analysis_scope import resolve_analysis_scope


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
        self.utc_range()
        return self

    def utc_range(self) -> tuple[datetime, datetime]:
        scope = resolve_analysis_scope(
            package_name=self.package_name,
            date_from=self.date_from,
            hour_from=self.hour_from,
            date_to=self.date_to,
            hour_to=self.hour_to,
        )
        return scope.range_start, scope.range_end
