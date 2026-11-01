from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from dental_agent.models.database_models import Appointment, AppointmentSlot, Doctor
from scripts.refresh_availability import refresh_availability as refresh


def refresh_availability(session, *args, **kwargs):
    # Fixtures insert explicit slot IDs, unlike the real application's serial
    # inserts. Align the isolated PostgreSQL sequence before testing insertion.
    if kwargs.get("apply") and session.bind.dialect.name == "postgresql":
        connection = session.connection()
        table = AppointmentSlot.__table__
        schema = connection.schema_for_object(table)
        preparer = connection.dialect.identifier_preparer
        name = preparer.quote(table.name)
        qualified = f"{preparer.quote_schema(schema)}.{name}" if schema else name
        next_id = (session.scalar(select(func.max(AppointmentSlot.id))) or 0) + 1
        session.execute(select(func.setval(func.pg_get_serial_sequence(qualified, "id"), next_id, False)))
    return refresh(session, *args, **kwargs)


def test_preview_does_not_modify_database(database):
    factory, start = database
    before = start - timedelta(days=1)
    with factory.begin() as session:
        summary = refresh_availability(session, start.date(), 1, now=before)
        assert summary["new_slots"] == 24  # two doctors, two days, six slots
        assert summary["future_unlinked_slots_to_replace"] == 3
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AppointmentSlot)) == 3


def test_apply_preserves_every_appointment_status_and_profiles(database):
    factory, start = database
    clinic = ZoneInfo("Asia/Kolkata")
    day = start.astimezone(clinic).date()
    now = datetime.combine(day, time(8), tzinfo=clinic)
    nine = datetime.combine(day, time(9), tzinfo=clinic)
    with factory.begin() as session:
        session.add_all([
            AppointmentSlot(id=10, doctor_id=1, start_time=nine, end_time=nine + timedelta(minutes=30), is_enabled=True),
            AppointmentSlot(id=11, doctor_id=1, start_time=nine + timedelta(minutes=30), end_time=nine + timedelta(hours=1), is_enabled=True),
        ])
        session.flush()
        session.add_all([
            Appointment(patient_id=1, slot_id=10, status="booked"),
            Appointment(patient_id=1, slot_id=11, status="cancelled"),
        ])
    with factory.begin() as session:
        summary = refresh_availability(session, day, 0, apply=True, now=now)
        assert summary["new_slots"] == 10
        assert summary["history_overlaps_skipped"] == 2
        assert summary["appointments_preserved"] == 2
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Doctor)) == 2
        assert session.scalar(select(func.count()).select_from(Appointment)) == 2
        assert session.get(AppointmentSlot, 10) is not None
        assert session.get(AppointmentSlot, 11) is not None
        # Existing unlinked future slots (outside the new window too) are replaced.
        assert session.get(AppointmentSlot, 1) is None
        assert session.get(AppointmentSlot, 2) is None
        assert session.get(AppointmentSlot, 3) is None
        assert session.scalar(select(func.count()).select_from(AppointmentSlot)) == 12


def test_elapsed_and_inactive_slots_are_not_deleted_or_regenerated(database):
    factory, start = database
    clinic = ZoneInfo("Asia/Kolkata")
    day = start.astimezone(clinic).date()
    now = datetime.combine(day, time(10, 15), tzinfo=clinic)
    with factory.begin() as session:
        session.get(Doctor, 2).is_active = False
        slot = session.get(AppointmentSlot, 1)
        slot.start_time = now - timedelta(days=1)
        slot.end_time = slot.start_time + timedelta(minutes=30)
    with factory.begin() as session:
        summary = refresh_availability(session, day, 0, apply=True, now=now)
        assert summary["new_slots"] == 3
        assert summary["elapsed_slots_skipped"] == 3
        assert summary["active_doctors"] == 1
    with factory() as session:
        assert session.get(AppointmentSlot, 1) is not None
        assert session.get(AppointmentSlot, 3) is not None
        assert session.get(Doctor, 2).is_active is False


def test_today_plus_ten_days_includes_weekends_and_repeat_is_safe(database):
    factory, start = database
    clinic = ZoneInfo("Asia/Kolkata")
    day = start.astimezone(clinic).date()
    now = datetime.combine(day, time(8), tzinfo=clinic)
    for _ in range(2):
        with factory.begin() as session:
            summary = refresh_availability(session, day, 10, apply=True, now=now)
            assert summary["new_slots"] == 132  # 2 doctors * 11 days * 6 slots
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(AppointmentSlot)) == 132
    assert summary["end_date"] == (day + timedelta(days=10)).isoformat()


@pytest.mark.parametrize("days", [-1, True, 366])
def test_invalid_day_range_is_rejected_without_writes(database, days):
    factory, start = database
    with factory.begin() as session:
        with pytest.raises(ValueError):
            refresh_availability(session, start.date(), days, now=start - timedelta(days=1))
