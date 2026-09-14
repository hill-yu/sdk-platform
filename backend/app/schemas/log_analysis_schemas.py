from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PackageProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str = Field(default="", max_length=255)
    company: str = Field(default="", max_length=255)
    account: str = Field(default="", max_length=255)


class PackageProfileResponse(BaseModel):
    package_name: str
    alias: str
    company: str
    account: str


class LogAnalysisColumnsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str] = Field(min_length=1, max_length=16)

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, value: list[str]) -> list[str]:
        from app.services.log_analysis_service import validate_column_selection

        return validate_column_selection(value)


class LogAnalysisColumnsResponse(BaseModel):
    available_columns: list[str]
    default_columns: list[str]
    columns: list[str]
