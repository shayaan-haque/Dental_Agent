from sqlalchemy.orm import DeclarativeBase,sessionmaker
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine


load_dotenv()

class Base(DeclarativeBase):
    """Shared base for all SQLAlchemy database models."""

    pass


database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not configured")


engine = create_engine(database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)