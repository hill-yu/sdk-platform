"""sdk_events ORM 模型"""
from sqlalchemy import Column, BigInteger, String, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.sql import func
from app.core.database import Base


class SdkEvent(Base):
    __tablename__ = "sdk_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False)
    package_name = Column(String(255), nullable=False)
    device_id = Column(String(64))
    sdk_version = Column(String(20))
    session_id = Column(String(64))
    payload = Column(JSONB, nullable=False)
    client_ts = Column(DateTime(timezone=True))
    server_ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ip = Column(INET)
    user_agent = Column(Text)
