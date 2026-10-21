"""Package source directory used by admin package selectors."""

from sqlalchemy import Boolean, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PackageCatalog(Base):
    __tablename__ = "sdk_package_catalog"

    package_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    has_log: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    has_usage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_package_catalog_log_name", "package_name", postgresql_where=has_log.is_(True)),
        Index("idx_package_catalog_usage_name", "package_name", postgresql_where=has_usage.is_(True)),
    )
