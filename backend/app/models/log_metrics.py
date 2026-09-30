"""Structured H1 declarations and click-attempt persistence models."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class _H1DeclarationColumns:
    event_id = Column(BigInteger, nullable=False)
    event_server_ts = Column(DateTime(timezone=True), nullable=False)
    record_index = Column(Integer, nullable=False)
    package_name = Column(String(255), nullable=False)
    device_id = Column(String(64))
    sdk_version = Column(String(20))
    config_id = Column(Integer)
    window = Column(String(32))
    declared_click_count = Column(Integer)
    interstitial_presentation_count = Column(Integer, nullable=False, default=0)
    interstitial_click_count = Column(Integer, nullable=False, default=0)
    interstitial_close_count = Column(Integer, nullable=False, default=0)
    flow_duration_ms = Column(BigInteger)
    final_reason = Column(String(128))
    status = Column(String(32), nullable=False, default="pending")
    parse_error = Column(String(512))
    decoder_version = Column(String(32), nullable=False)
    parsed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    decoded_payload = Column(JSONB)


class H1Declaration(Base, _H1DeclarationColumns):
    __tablename__ = "sdk_log_h1_declarations"

    __table_args__ = (
        Index("idx_log_h1_package_ts_config", "package_name", "event_server_ts", "config_id"),
    )

    event_id = Column(BigInteger, primary_key=True)
    event_server_ts = Column(DateTime(timezone=True), primary_key=True)
    record_index = Column(Integer, primary_key=True)


class H1DeclarationStage(Base, _H1DeclarationColumns):
    __tablename__ = "sdk_log_h1_declaration_stage"

    job_id = Column(BigInteger, primary_key=True)
    event_id = Column(BigInteger, primary_key=True)
    event_server_ts = Column(DateTime(timezone=True), primary_key=True)
    record_index = Column(Integer, primary_key=True)
    __table_args__ = (Index("idx_log_h1_stage_job", "job_id"),)


class _LogClickAttemptColumns:
    event_id = Column(BigInteger, nullable=False)
    event_server_ts = Column(DateTime(timezone=True), nullable=False)
    record_index = Column(Integer, nullable=False)
    package_name = Column(String(255), nullable=False)
    config_id = Column(Integer)
    target_kind = Column(String(64))
    did_click = Column(Boolean)
    navigation_code = Column(Integer)
    reason = Column(String(128))
    error_detail = Column(Text)
    navigation_result = Column(String(128))
    failure_category = Column(String(128))
    click_timestamp = Column(DateTime(timezone=True))
    page_context = Column(String(32))
    decoder_version = Column(String(32), nullable=False)


class LogClickAttempt(Base, _LogClickAttemptColumns):
    __tablename__ = "sdk_log_click_attempts"

    __table_args__ = (
        Index(
            "idx_log_click_package_ts_config_target",
            "package_name",
            "event_server_ts",
            "config_id",
            "target_kind",
        ),
    )

    event_id = Column(BigInteger, primary_key=True)
    event_server_ts = Column(DateTime(timezone=True), primary_key=True)
    record_index = Column(Integer, primary_key=True)
    attempt_index = Column(Integer, primary_key=True)


class LogClickAttemptStage(Base, _LogClickAttemptColumns):
    __tablename__ = "sdk_log_click_attempt_stage"

    job_id = Column(BigInteger, primary_key=True)
    event_id = Column(BigInteger, primary_key=True)
    event_server_ts = Column(DateTime(timezone=True), primary_key=True)
    record_index = Column(Integer, primary_key=True)
    attempt_index = Column(Integer, primary_key=True)
    __table_args__ = (Index("idx_log_click_stage_job", "job_id"),)
