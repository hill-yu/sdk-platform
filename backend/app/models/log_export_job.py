from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, Column, Date, DateTime, String, Text
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
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    status = Column(String(20), nullable=False, default="pending")
    package_names = Column(JSONB, nullable=False)
    device_id = Column(String(64))
    log_level = Column(String(10))
    date_from = Column(Date)
    date_to = Column(Date)
    file_path = Column(Text)
    row_count = Column(BigInteger, nullable=False, default=0)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
