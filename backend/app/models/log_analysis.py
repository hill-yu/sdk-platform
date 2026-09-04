"""Decoded SDK log analysis persistence models."""
from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class LogDecode(Base):
    __tablename__ = "sdk_log_decodes"
    __table_args__ = (
        Index("idx_log_decodes_package_ts", "package_name", "event_server_ts"),
        Index("idx_log_decodes_trace_id", "trace_id"),
    )

    event_id = Column(BigInteger, primary_key=True)
    event_server_ts = Column(DateTime(timezone=True), primary_key=True)
    record_index = Column(Integer, primary_key=True)
    package_name = Column(String(255), nullable=False)
    decoder_name = Column(String(64), nullable=False)
    decoder_version = Column(String(32), nullable=False)
    trace_id = Column(String(128))
    decoded_payload = Column(JSONB, nullable=False)
    decode_status = Column(String(20), nullable=False, default="pending")
    error_summary = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PackageProfile(Base):
    __tablename__ = "sdk_package_profiles"
    __table_args__ = (Index("idx_package_profiles_updated", "updated_at"),)

    package_name = Column(String(255), primary_key=True)
    display_name = Column(String(255))
    owner = Column(String(128))
    profile = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AdminPreference(Base):
    __tablename__ = "sdk_admin_preferences"
    __table_args__ = (Index("idx_admin_preferences_updated", "updated_at"),)

    preference_key = Column(String(128), primary_key=True)
    preference_value = Column(JSONB, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LogReparseJob(Base):
    __tablename__ = "sdk_log_reparse_jobs"
    __table_args__ = (
        Index("idx_log_reparse_jobs_status", "status", "created_at"),
        Index("idx_log_reparse_jobs_range", "range_start", "range_end"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    package_name = Column(String(255))
    range_start = Column(DateTime(timezone=True), nullable=False)
    range_end = Column(DateTime(timezone=True), nullable=False)
    cursor_event_id = Column(BigInteger)
    cursor_server_ts = Column(DateTime(timezone=True))
    processed_count = Column(BigInteger, nullable=False, default=0)
    decoded_count = Column(BigInteger, nullable=False, default=0)
    failed_count = Column(BigInteger, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="pending")
    error_summary = Column(Text)
    created_by = Column(String(64))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
