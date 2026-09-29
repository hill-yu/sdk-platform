"""SDK 使用时长 ORM 模型。"""

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.sql import func

from app.core.database import Base


class SdkUsageDuration(Base):
    __tablename__ = "sdk_usage_durations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    package_name = Column(String(255), nullable=False)
    device_id = Column(String(64), nullable=False)
    device_model = Column(String(100), nullable=False)
    os = Column(String(50), nullable=False)
    app_version = Column(String(50), nullable=False)
    sdk_version = Column(String(20), nullable=False)
    duration_s = Column(Integer, nullable=False)
    server_ts = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ip = Column(INET)
    user_agent = Column(Text)

    __table_args__ = (
        CheckConstraint(
            "duration_s BETWEEN 1 AND 3600",
            name="chk_usage_durations_duration_s",
        ),
        Index("idx_usage_durations_server_ts", server_ts.desc()),
        Index("idx_usage_durations_package_ts", package_name, server_ts.desc()),
        Index(
            "idx_usage_durations_package_device_ts",
            package_name,
            device_id,
            server_ts.desc(),
        ),
    )
