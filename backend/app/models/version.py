"""sdk_versions ORM 模型"""
from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class SdkVersion(Base):
    __tablename__ = "sdk_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(10), nullable=False)
    version_code = Column(Integer, nullable=False)
    version_name = Column(String(20), nullable=False)
    update_policy = Column(String(20), nullable=False, default="suggest")
    download_url = Column(String(512))
    release_notes = Column(Text)
    min_sdk_version = Column(Integer)
    file_size = Column(BigInteger)
    file_hash = Column(String(64))
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
