"""
SDK 数据中台 + 配置管理系统 — 数据库连接池
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.resolved_database_url,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_timeout=5,
    pool_recycle=1800,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类"""
    pass


async def get_db():
    """FastAPI 依赖：获取数据库会话（自动 commit/rollback）"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_no_commit():
    """FastAPI 依赖：只读查询（不自动 commit）"""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
