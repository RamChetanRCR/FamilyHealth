import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://health_app:change_this_later@postgres:5432/family_health",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
