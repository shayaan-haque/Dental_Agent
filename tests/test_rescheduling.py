"""Atomicity tests, including failures after UPDATE/INSERT have been flushed."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from dental_agent.models.database_models import Appointment, AppointmentSlot
from dental_agent.services.booking import AppointmentError, book_appointment, reschedule_appointment
from dental_agent.tools.booking import book_appointment as book_tool
from dental_agent.tools.rescheduling import reschedule_appointment as reschedule_tool


def test_rescheduling_cannot_modify_another_patients_booking(database):
    factory, _ = database
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    with pytest.raises(AppointmentError) as error:
        reschedule_appointment(2, old_id, 2)
    assert error.value.code == "appointment_not_found"
    with factory() as session:
        assert session.get(Appointment, old_id).status == "booked"
        assert session.scalar(select(func.count()).select_from(Appointment)) == 1


@pytest.mark.parametrize("status", ["cancelled", "completed", "rescheduled"])
def test_nonbooked_appointment_cannot_be_rescheduled(database, status):
    factory, _ = database
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    with factory.begin() as session:
        session.get(Appointment, old_id).status = status
    with pytest.raises(AppointmentError):
        reschedule_appointment(1, old_id, 2)
    with factory() as session:
        assert session.get(Appointment, old_id).status == status
        assert session.scalar(select(func.count()).select_from(Appointment)) == 1


def test_started_booking_cannot_be_rescheduled(database):
    factory, _ = database
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    with factory.begin() as session:
        slot = session.get(AppointmentSlot, 1)
        slot.start_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        slot.end_time = slot.start_time + timedelta(minutes=30)
    with pytest.raises(AppointmentError) as error:
        reschedule_appointment(1, old_id, 2)
    assert error.value.code == "appointment_started"
    with factory() as session:
        assert session.get(Appointment, old_id).status == "booked"


def test_replacement_can_overlap_the_old_visit_but_not_other_bookings(database):
    # Same time, different doctor: the original visit must be excluded from the
    # overlap check because it is replaced in the SAME transaction.
    factory, _ = database
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    result = reschedule_appointment(1, old_id, 3)
    assert result["ok"] and result["appointment"]["doctor_id"] == 2
    with factory() as session:
        assert session.get(Appointment, old_id).status == "rescheduled"


def test_repeated_rescheduling_request_does_not_create_a_second_replacement(database):
    factory, _ = database
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    first = reschedule_appointment(1, old_id, 2)
    with pytest.raises(AppointmentError) as error:
        reschedule_appointment(1, old_id, 2)
    assert error.value.code == "already_rescheduled"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Appointment)) == 2
        assert session.get(Appointment, first["appointment"]["appointment_id"]).status == "booked"


@pytest.mark.parametrize("via_tool", [False, True])
def test_actual_integrity_error_after_old_update_rolls_back_everything(database, via_tool):
    factory, _ = database
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    failed_sessions = []

    def force_duplicate(session, _context, _instances):
        if any(isinstance(item, Appointment) and item.slot_id == 2 for item in session.new):
            # The UPDATE really reached the database before the INSERT failure.
            assert session.scalar(select(Appointment.status).where(Appointment.id == old_id)) == "rescheduled"
            failed_sessions.append(session)
            session.add(Appointment(patient_id=2, slot_id=2, status="booked"))

    event.listen(factory.class_, "before_flush", force_duplicate)
    try:
        if via_tool:
            result = reschedule_tool.invoke({"patient_id": 1, "appointment_id": old_id, "new_slot_id": 2})
            assert not result["ok"]
            assert result["code"] in {"slot_taken", "database_error"}
        else:
            with pytest.raises(IntegrityError):
                reschedule_appointment(1, old_id, 2)
    finally:
        event.remove(factory.class_, "before_flush", force_duplicate)

    assert len(failed_sessions) == 1
    assert failed_sessions[0].is_active
    assert not failed_sessions[0].in_transaction()
    with factory() as session:
        assert session.get(Appointment, old_id).status == "booked"
        assert session.scalar(select(func.count()).select_from(Appointment)) == 1
    # Subsequent operations work: no poisoned session/connection leaks out.
    assert book_appointment(2, 2)["ok"]


@pytest.mark.parametrize("operation", ["book", "reschedule"])
def test_known_commit_failure_never_reports_success_and_rolls_back(database, operation):
    factory, _ = database
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"] if operation == "reschedule" else None
    failed_sessions = []

    def fail_commit(session):
        assert session.scalar(select(Appointment.id).where(Appointment.slot_id == 2)) is not None
        if old_id is not None:
            assert session.get(Appointment, old_id).status == "rescheduled"
        failed_sessions.append(session)
        raise OperationalError("COMMIT", {}, Exception("injected commit failure"))

    event.listen(factory.class_, "before_commit", fail_commit)
    try:
        result = (reschedule_tool.invoke({"patient_id": 1, "appointment_id": old_id, "new_slot_id": 2})
                  if old_id is not None else book_tool.invoke({"patient_id": 1, "slot_id": 2}))
        assert not result["ok"] and result["code"] == "database_error"
    finally:
        event.remove(factory.class_, "before_commit", fail_commit)
    assert failed_sessions and not failed_sessions[0].in_transaction()
    with factory() as session:
        assert session.scalar(select(Appointment.id).where(Appointment.slot_id == 2)) is None
        if old_id is not None:
            assert session.get(Appointment, old_id).status == "booked"


def test_success_is_returned_only_after_commit(database):
    factory, _ = database
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    commits = []

    def committed(_session):
        commits.append(True)

    event.listen(factory.class_, "after_commit", committed)
    try:
        result = reschedule_tool.invoke({"patient_id": 1, "appointment_id": old_id, "new_slot_id": 2})
        assert commits == [True] and result["ok"]
    finally:
        event.remove(factory.class_, "after_commit", committed)
    with factory() as session:
        assert session.get(Appointment, old_id).status == "rescheduled"
        assert session.get(Appointment, result["appointment"]["appointment_id"]).status == "booked"


def test_postgres_two_reschedules_competing_for_one_slot_keep_losing_booking(postgres_database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    factory, _ = postgres_database
    old_ids = {1: book_appointment(1, 1)["appointment"]["appointment_id"],
               2: book_appointment(2, 3)["appointment"]["appointment_id"]}
    barrier = Barrier(2)

    def attempt(patient_id):
        barrier.wait(timeout=10)
        try:
            return patient_id, reschedule_appointment(patient_id, old_ids[patient_id], 2)["code"]
        except AppointmentError as error:
            return patient_id, error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(attempt, [1, 2]))
    assert sorted(results.values()) == ["rescheduled", "slot_taken"]
    with factory() as session:
        for patient_id, code in results.items():
            assert session.get(Appointment, old_ids[patient_id]).status == ("rescheduled" if code == "rescheduled" else "booked")
        assert session.scalar(select(func.count()).select_from(Appointment).where(Appointment.status == "booked")) == 2
        assert session.scalar(select(func.count()).select_from(Appointment).where(Appointment.slot_id == 2)) == 1
