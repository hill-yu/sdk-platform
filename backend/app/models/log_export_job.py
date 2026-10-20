from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, SmallInteger, String, Text, false
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class LogExportJob(Base):
    __tablename__ = "sdk_log_export_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed')",
            name="chk_log_export_jobs_status",
        ),
        CheckConstraint(
            "export_mode IN ('raw', 'h1')",
            name="chk_log_export_jobs_export_mode",
        ),
        CheckConstraint(
            "(hour_from IS NULL AND hour_to IS NULL) OR (hour_from IS NOT NULL AND hour_to IS NOT NULL)",
            name="chk_log_export_jobs_hour_pair",
        ),
        CheckConstraint(
            "(hour_from IS NULL OR hour_from BETWEEN 0 AND 23) AND (hour_to IS NULL OR hour_to BETWEEN 0 AND 23)",
            name="chk_log_export_jobs_hour_bounds",
        ),
        CheckConstraint(
            "(all_packages = TRUE AND package_names = '[]'::jsonb) OR "
            "(all_packages = FALSE AND jsonb_array_length(package_names) BETWEEN 1 AND 50)",
            name="chk_log_export_jobs_package_scope",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    status = Column(String(20), nullable=False, default="pending")
    export_mode = Column(String(10), nullable=False, default="raw")
    package_names = Column(JSONB, nullable=False)
    all_packages = Column(Boolean, nullable=False, default=False, server_default=false())
    sdk_version = Column(String(20))
    device_id = Column(String(64))
    log_level = Column(String(10))
    date_from = Column(Date)
    hour_from = Column(SmallInteger)
    date_to = Column(Date)
    hour_to = Column(SmallInteger)
    file_path = Column(Text)
    row_count = Column(BigInteger, nullable=False, default=0)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
