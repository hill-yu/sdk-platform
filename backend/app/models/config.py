"""sdk_configs ORM 模型"""
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class SdkConfig(Base):
    __tablename__ = "sdk_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(32), unique=True, nullable=False)
    config_data = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default="draft")
    publish_at = Column(DateTime(timezone=True))
    published_by = Column(String(64))
    cos_key = Column(String(256))
    cdn_url = Column(String(512))
    cos_upload_status = Column(String(20), nullable=False, default="pending")
    change_log = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
