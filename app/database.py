import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# DATABASE_URL overrides the path entirely (Railway Postgres, for instance).
# Otherwise we default to the SQLite file. On Railway we mount a volume at
# /data and set DB_DIR=/data so the DB persists across deploys.
if os.getenv("DATABASE_URL"):
    DATABASE_URL = os.environ["DATABASE_URL"]
else:
    DB_DIR = os.getenv("DB_DIR", BASE_DIR)
    os.makedirs(DB_DIR, exist_ok=True)
    DATABASE_URL = f"sqlite+aiosqlite:///{os.path.join(DB_DIR, 'deal_analyzer.db')}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
