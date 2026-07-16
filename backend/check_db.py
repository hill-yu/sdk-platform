import sys, asyncio
sys.path.insert(0, '.')
from app.core.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def check():
    engine = create_async_engine(get_settings().resolved_database_url)
    async with engine.connect() as conn:
        r = await conn.execute(text("SELECT matviewname FROM pg_matviews WHERE schemaname='public'"))
        views = [row[0] for row in r]
        print('Materialized views:', views)
        r = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))
        tables = [row[0] for row in r]
        print('Tables:', tables)
    await engine.dispose()

asyncio.run(check())
