"""Decoded SDK log analysis persistence models."""
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class LogDecode(Base):
    __tablename__ = "sdk_log_decodes"
    event_id = Column(BigInteger, primary_key=True)
    event_server_ts = Column(DateTime(timezone=True), primary_key=True)
    record_index = Column(Integer, primary_key=True)
    package_name = Column(String(255), nullable=False)
    device_id = Column(String(64))
    status = Column(String(32), nullable=False, default="pending")
    decoder_version = Column(String(32), nullable=False)
    decoded_timestamp = Column(DateTime(timezone=True))
    url = Column(Text)
    config_id = Column(Integer)
    window = Column(String(32))
    expected_click_count = Column(Integer)
    actual_click_count = Column(Integer)
    ad_click_count = Column(Integer)
    interstitial_presentation_count = Column(Integer)
    interstitial_click_count = Column(Integer)
    interstitial_close_count = Column(Integer)
    duration_ms = Column(BigInteger)
    final_reason = Column(String(128))
    is_success = Column(Boolean)
    decoded_payload = Column(JSONB)
    parse_error = Column(String(512))
    parsed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'success', 'unsupported', 'failed')",
            name="chk_log_decodes_status",
        ),
        Index("idx_log_decodes_package_ts", package_name, event_server_ts.desc()),
        Index("idx_log_decodes_status_ts", status, event_server_ts.desc()),
        Index("idx_log_decodes_decoder_status", decoder_version, status),
        Index("idx_log_decodes_event_ts", event_id, event_server_ts),
    )


class PackageProfile(Base):
    __tablename__ = "sdk_package_profiles"
    __table_args__ = (Index("idx_package_profiles_updated", "updated_at"),)

    package_name = Column(String(255), primary_key=True)
    alias = Column(String(255))
    company = Column(String(255))
    account = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AdminPreference(Base):
    __tablename__ = "sdk_admin_preferences"
    __table_args__ = (Index("idx_admin_preferences_updated", "updated_at"),)

    preference_key = Column(String(128), primary_key=True)
    value = Column(JSONB, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class LogReparseJob(Base):
    __tablename__ = "sdk_log_reparse_jobs"
    __table_args__ = (
        Index("idx_log_reparse_jobs_status", "status", "created_at"),
        Index("idx_log_reparse_jobs_range", "range_start", "range_end"),
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed', 'cancelled')",
            name="chk_log_reparse_jobs_status",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    package_name = Column(String(255))
    range_start = Column(DateTime(timezone=True), nullable=False)
    range_end = Column(DateTime(timezone=True), nullable=False)
    snapshot_end = Column(DateTime(timezone=True), nullable=False)
    status_filter = Column(String(32))
    decoder_version_before = Column(String(32))
    lease_owner = Column(String(64))
    lease_expires_at = Column(DateTime(timezone=True))
    cursor_event_id = Column(BigInteger)
    cursor_server_ts = Column(DateTime(timezone=True))
    processed_count = Column(BigInteger, nullable=False, default=0)
    decoded_count = Column(BigInteger, nullable=False, default=0)
    failed_count = Column(BigInteger, nullable=False, default=0)
    total_count = Column(BigInteger, nullable=False, default=0)
    h1_count = Column(BigInteger, nullable=False, default=0)
    failed_h1_count = Column(BigInteger, nullable=False, default=0)
    no_h1_count = Column(BigInteger, nullable=False, default=0)
    consecutive_timeout_count = Column(Integer, nullable=False, default=0)
    batch_size = Column(Integer, nullable=False, default=200)
    concurrency = Column(Integer, nullable=False, default=3)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    last_heartbeat_at = Column(DateTime(timezone=True))
    cancel_requested_at = Column(DateTime(timezone=True))
    status = Column(String(20), nullable=False, default="pending")
    error_summary = Column(Text)
    created_by = Column(String(64))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
