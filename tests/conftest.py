"""Isolated service tests: SQLite for behavior, opt-in PostgreSQL for row locks."""

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-not-for-deployment")
os.environ.setdefault("GROQ_API_KEY", "test-only-no-network")

import pytest
from sqlalchemy import DateTime, MetaData, create_engine, event, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.dialects.sqlite import DATETIME
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dental_agent.database import Base
from dental_agent.models.database_models import AppointmentSlot, Doctor, User
from dental_agent.services import appointments, availability, booking


class SQLiteUTCDateTime(DATETIME):
    """Emulate PostgreSQL timestamptz for isolated SQLite behavior tests."""

    def bind_processor(self, dialect):
        parent = super().bind_processor(dialect)

        def process(value):
            if value is not None and value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            return parent(value)
        return process

    def result_processor(self, dialect, coltype):
        parent = super().result_processor(dialect, coltype)

        def process(value):
            value = parent(value)
            return value.replace(tzinfo=timezone.utc) if value is not None else None
        return process


def patch_sessions(monkeypatch, factory):
    for module in (booking, appointments, availability):
        monkeypatch.setattr(module, "SessionLocal", factory)


def seed(factory):
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    with factory.begin() as session:
        session.add_all([User(id=i, name=f"Patient {i}", email=f"patient{i}@example.com", password_hash="unused") for i in (1, 2)])
        session.add_all([Doctor(id=i, name=f"Doctor {i}", specialization="general_dentist", is_active=True) for i in (1, 2)])
        session.flush()
        session.add_all([
            AppointmentSlot(id=1, doctor_id=1, start_time=start, end_time=start + timedelta(minutes=30), is_enabled=True),
            AppointmentSlot(id=2, doctor_id=1, start_time=start + timedelta(days=1), end_time=start + timedelta(days=1, minutes=30), is_enabled=True),
            AppointmentSlot(id=3, doctor_id=2, start_time=start, end_time=start + timedelta(minutes=30), is_enabled=True),
        ])
    return start


@pytest.fixture
def database(monkeypatch, request):
    if os.getenv("BOOKING_TEST_BACKEND") == "postgres":
        yield request.getfixturevalue("postgres_database")
        return
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    engine.dialect.colspecs = {**engine.dialect.colspecs, DateTime: SQLiteUTCDateTime}

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    metadata = MetaData()
    for original in Base.metadata.sorted_tables:
        table = original.to_metadata(metadata)
        for constraint in list(table.constraints):
            if isinstance(constraint, ExcludeConstraint):
                table.constraints.remove(constraint)
        for index in table.indexes:
            if index.name == "uq_booked_appointment_per_slot":
                index.dialect_options["sqlite"]["where"] = text("status = 'booked'")
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    patch_sessions(monkeypatch, factory)
    start = seed(factory)
    yield factory, start
    engine.dispose()


@pytest.fixture
def postgres_database(monkeypatch):
    from uuid import uuid4

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for PostgreSQL locking tests")
    if not url.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL must use PostgreSQL")
    engine = create_engine(url)
    schema = f"test_booking_{uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(isolated)
        factory = sessionmaker(bind=isolated, expire_on_commit=False, autoflush=False)
        patch_sessions(monkeypatch, factory)
        yield factory, seed(factory)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
