from pydantic import BaseModel, Field, field_validator

from app.services.config_crypto import normalize_package_name


class ConfigMetaRequest(BaseModel):
    package_name: str = Field(..., min_length=1, max_length=255)

    @field_validator("package_name")
    @classmethod
    def validate_package_name(cls, value: str) -> str:
        return normalize_package_name(value)
