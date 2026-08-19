
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine

from models import (
    CachedSourceJob,
    JobSourceCacheState,
)


load_dotenv()

database_url = os.getenv(
    "DATABASE_URL"
)

if not database_url:
    raise RuntimeError(
        "DATABASE_URL is not set."
    )

engine = create_engine(
    database_url,
    pool_pre_ping=True,
)

CachedSourceJob.__table__.create(
    bind=engine,
    checkfirst=True,
)

JobSourceCacheState.__table__.create(
    bind=engine,
    checkfirst=True,
)

print(
    "Shared source-job cache schema "
    "migration complete."
)
