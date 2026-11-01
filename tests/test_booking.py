from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from dental_agent.models.database_models import Appointment, AppointmentSlot, Doctor
from dental_agent.services.appointments import get_patient_appointments
from dental_agent.services.availability import get_available_slots
from dental_agent.services.booking import AppointmentError, book_appointment, cancel_appointment, reschedule_appointment


def test_booking_saved_and_retries_are_idempotent(database):
    factory, _ = database
    result = book_appointment(1, 1)
    assert result["ok"] and result["appointment"]["status"] == "booked"
    assert result["appointment"]["starts_at"].endswith("+05:30")
    assert book_appointment(1, 1)["code"] == "already_booked"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Appointment)) == 1
        assert session.get(AppointmentSlot, 1).is_enabled
    assert 1 not in [slot["slot_id"] for slot in get_available_slots()]


def test_other_patient_cannot_book_taken_slot(database):
    book_appointment(1, 1)
    with pytest.raises(AppointmentError, match="just booked"):
        book_appointment(2, 1)


def test_patient_cannot_book_overlapping_doctors(database):
    book_appointment(1, 1)
    with pytest.raises(AppointmentError) as error:
        book_appointment(1, 3)
    assert error.value.code == "patient_overlap"


@pytest.mark.parametrize("field", ["disabled", "inactive", "past", "missing"])
def test_invalid_availability_cannot_be_booked(database, field):
    factory, _ = database
    with factory.begin() as session:
        slot = session.get(AppointmentSlot, 1)
        if field == "disabled":
            slot.is_enabled = False
        elif field == "inactive":
            session.get(Doctor, 1).is_active = False
        elif field == "past":
            slot.start_time = datetime.now(timezone.utc) - timedelta(hours=1)
            slot.end_time = slot.start_time + timedelta(minutes=30)
    with pytest.raises(AppointmentError):
        book_appointment(1, 999 if field == "missing" else 1)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Appointment)) == 0


@pytest.mark.parametrize("bad", [True, False, 0, -1, "1", None])
def test_service_rejects_invalid_ids(database, bad):
    for operation, args in [(book_appointment, (bad, 1)), (book_appointment, (1, bad)),
                            (cancel_appointment, (bad, 1)), (cancel_appointment, (1, bad)),
                            (reschedule_appointment, (bad, 1, 2)), (reschedule_appointment, (1, bad, 2)),
                            (reschedule_appointment, (1, 1, bad))]:
        with pytest.raises(AppointmentError):
            operation(*args)


def test_cancellation_owned_retained_idempotent_and_slot_reusable(database):
    factory, _ = database
    appointment_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    with pytest.raises(AppointmentError) as error:
        cancel_appointment(2, appointment_id)
    assert error.value.code == "appointment_not_found"
    assert cancel_appointment(1, appointment_id)["code"] == "cancelled"
    assert cancel_appointment(1, appointment_id)["code"] == "already_cancelled"
    assert get_patient_appointments(1)["items"] == []
    assert get_patient_appointments(1, view="all")["items"][0]["status"] == "cancelled"
    assert get_patient_appointments(2, view="all")["items"] == []
    assert 1 in [slot["slot_id"] for slot in get_available_slots()]
    new = book_appointment(2, 1)["appointment"]
    assert new["appointment_id"] != appointment_id
    with factory() as session:
        assert session.get(Appointment, appointment_id).status == "cancelled"


@pytest.mark.parametrize("status", ["completed", "rescheduled"])
def test_nonbooked_appointment_cannot_be_cancelled(database, status):
    factory, _ = database
    appointment_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    with factory.begin() as session:
        session.get(Appointment, appointment_id).status = status
    with pytest.raises(AppointmentError):
        cancel_appointment(1, appointment_id)


def test_started_appointment_cannot_be_cancelled(database):
    factory, _ = database
    appointment_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    with factory.begin() as session:
        slot = session.get(AppointmentSlot, 1)
        slot.start_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        slot.end_time = slot.start_time + timedelta(minutes=30)
    with pytest.raises(AppointmentError) as error:
        cancel_appointment(1, appointment_id)
    assert error.value.code == "appointment_started"


@pytest.mark.parametrize("reason", ["taken", "disabled", "inactive", "past", "missing", "same", "overlap"])
def test_unavailable_replacement_leaves_old_booking_unchanged(database, reason):
    factory, _ = database
    appointment_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    target = 2
    if reason == "taken":
        book_appointment(2, 2)
    elif reason == "overlap":
        book_appointment(1, 2)
        with factory.begin() as session:
            old = session.get(AppointmentSlot, 2)
            session.add(AppointmentSlot(id=4, doctor_id=2, start_time=old.start_time,
                                        end_time=old.end_time, is_enabled=True))
        target = 4
    else:
        with factory.begin() as session:
            if reason == "disabled":
                session.get(AppointmentSlot, 2).is_enabled = False
            elif reason == "inactive":
                session.get(Doctor, 1).is_active = False
            elif reason == "past":
                slot = session.get(AppointmentSlot, 2)
                slot.start_time = datetime.now(timezone.utc) - timedelta(hours=2)
                slot.end_time = slot.start_time + timedelta(minutes=30)
            elif reason == "missing":
                target = 999
            elif reason == "same":
                target = 1
    with pytest.raises(AppointmentError):
        reschedule_appointment(1, appointment_id, target)
    with factory() as session:
        assert session.get(Appointment, appointment_id).status == "booked"


def test_reschedule_moves_atomically_with_retained_history(database):
    factory, start = database
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    requested = (start + timedelta(days=1)).astimezone(ZoneInfo("Asia/Kolkata"))
    matches = get_available_slots(doctor_id=1, date_filter=requested.date(), time_filter=requested.strftime("%H:%M"))
    assert [slot["slot_id"] for slot in matches] == [2]
    result = reschedule_appointment(1, old_id, 2)
    assert result["ok"] and result["code"] == "rescheduled"
    assert result["previous_appointment_id"] == old_id
    assert result["appointment"]["appointment_id"] != old_id
    with factory() as session:
        assert session.get(Appointment, old_id).status == "rescheduled"
    assert [item["slot_id"] for item in get_patient_appointments(1)["items"]] == [2]
    assert [item["appointment_id"] for item in get_patient_appointments(1, view="rescheduled")["items"]] == [old_id]
    assert get_patient_appointments(1, view="cancelled")["items"] == []
    assert 1 in [slot["slot_id"] for slot in get_available_slots()]


def test_replacement_taken_after_search_preserves_original_booking(database):
    factory, _ = database
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    assert 2 in [slot["slot_id"] for slot in get_available_slots()]
    book_appointment(2, 2)
    with pytest.raises(AppointmentError):
        reschedule_appointment(1, old_id, 2)
    with factory() as session:
        assert session.get(Appointment, old_id).status == "booked"
    assert [item["slot_id"] for item in get_patient_appointments(1)["items"]] == [1]


def test_exact_time_is_filtered_before_result_limit(database):
    factory, start = database
    with factory.begin() as session:
        for index in range(25):
            when = start + timedelta(minutes=30 * (index + 1))
            session.add(AppointmentSlot(id=10 + index, doctor_id=1, start_time=when,
                                        end_time=when + timedelta(minutes=30), is_enabled=True))
    requested = (start + timedelta(minutes=30 * 25)).astimezone(ZoneInfo("Asia/Kolkata"))
    assert 34 not in [item["slot_id"] for item in get_available_slots(doctor_id=1)]
    exact = get_available_slots(doctor_id=1, date_filter=requested.date(), time_filter=requested.strftime("%H:%M"))
    assert [item["slot_id"] for item in exact] == [34]
    with pytest.raises(ValueError):
        get_available_slots(time_filter="19:00")


def test_database_unique_index_is_final_double_booking_guard(database):
    factory, _ = database
    book_appointment(1, 1)
    with pytest.raises(IntegrityError):
        with factory.begin() as session:
            session.add(Appointment(patient_id=2, slot_id=1, status="booked"))


def test_postgres_simultaneous_booking_has_one_winner(postgres_database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    factory, _ = postgres_database
    barrier = Barrier(2)

    def attempt(patient_id):
        barrier.wait(timeout=10)
        try:
            return book_appointment(patient_id, 1)["code"]
        except AppointmentError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert sorted(results) == ["booked", "slot_taken"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Appointment)) == 1


def test_postgres_same_patient_cannot_concurrently_book_overlapping_slots(postgres_database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    factory, _ = postgres_database
    barrier = Barrier(2)

    def attempt(slot_id):
        barrier.wait(timeout=10)
        try:
            return book_appointment(1, slot_id)["code"]
        except AppointmentError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 3]))
    assert sorted(results) == ["booked", "patient_overlap"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Appointment)) == 1


def test_postgres_concurrent_cancellation_is_idempotent(postgres_database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    factory, _ = postgres_database
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    barrier = Barrier(2)

    def attempt(_):
        barrier.wait(timeout=10)
        return cancel_appointment(1, old_id)["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert sorted(results) == ["already_cancelled", "cancelled"]
    with factory() as session:
        assert session.get(Appointment, old_id).status == "cancelled"
