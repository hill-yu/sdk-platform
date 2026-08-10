"""sdk_configs ORM 模型"""
from sqlalchemy import Column, Integer, String, DateTime, Text, UniqueConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class SdkConfig(Base):
    __tablename__ = "sdk_configs"
    __table_args__ = (
        UniqueConstraint("package_name", "version", name="uq_configs_package_version"),
        Index(
            "uq_sdk_configs_published_package",
            "package_name",
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    package_name = Column(String(255), nullable=False, index=True)
    version = Column(String(64), nullable=False)
    encrypted_config = Column(JSONB, nullable=False)
    encryption_key_id = Column(String(32), nullable=False, default="v1")
    status = Column(String(20), nullable=False, default="draft")
    publish_at = Column(DateTime(timezone=True))
    published_by = Column(String(64))
    cos_key = Column(String(256))
    cdn_url = Column(String(512))
    cos_upload_status = Column(String(20), nullable=False, default="pending")
    change_log = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
