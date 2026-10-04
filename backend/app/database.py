import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./family_health.db")

# ponytail: SQLite is plenty for a single-household app. check_same_thread=False
# lets FastAPI's threadpool share connections; single writer is the ceiling —
# move to Postgres only if real concurrent writers ever show up.
connect_args = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine)
