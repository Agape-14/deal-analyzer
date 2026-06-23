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

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+asyncpg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

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
    """Create tables and apply conservative add-only schema patches.

    Alembic remains the source of truth for normal migrations. The add-only
    patch pass is still useful on Railway's persistent SQLite volume because
    early prototype databases can predate a column that now exists in the
    mapped model. Without this, a harmless upload can fail with a 500 during
    INSERT even though the current code and migrations are valid.
    """
    # Make sure the mapped classes are registered on Base.metadata.
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        alembic_managed = await conn.run_sync(_is_alembic_managed)
        if not alembic_managed:
            await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_schema_patches)


def _is_alembic_managed(sync_conn) -> bool:
    from sqlalchemy import inspect

    return inspect(sync_conn).has_table("alembic_version")


def _apply_schema_patches(sync_conn) -> None:
    """Add columns declared on mapped classes but missing from live tables.

    This is intentionally conservative: add-only, no drops, no type changes,
    and no missing-table creation for Alembic-managed databases.
    """
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            col_sql = col.type.compile(dialect=sync_conn.dialect)
            null_sql = "" if col.nullable else " NOT NULL"
            default = ""
            if col.default is not None:
                # Only support scalar SQL defaults here. JSON/dict defaults are
                # populated by the model layer on insert.
                try:
                    arg = col.default.arg
                    if isinstance(arg, (int, float)):
                        default = f" DEFAULT {arg}"
                    elif isinstance(arg, str):
                        default = f" DEFAULT '{arg}'"
                except Exception:
                    pass
            sync_conn.execute(
                text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_sql}{null_sql}{default}')
            )
