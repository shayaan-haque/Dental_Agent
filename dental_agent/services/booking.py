"""Transactional booking, cancellation, and atomic rescheduling."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from dental_agent.database import SessionLocal
from dental_agent.models.database_models import Appointment, AppointmentSlot, Doctor, User


class AppointmentError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def positive_id(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AppointmentError("invalid_id", f"{name} must be a positive integer")


def _lock_patient(session, patient_id):
    # Serializes this patient's mutations, including requests from different logins.
    if session.scalar(select(User).where(User.id == patient_id).with_for_update()) is None:
        raise AppointmentError("patient_not_found", "Please log in again.")


def _available_doctor(session, slot):
    if slot is None or not slot.is_enabled:
        raise AppointmentError("slot_unavailable", "That slot is no longer available.")
    doctor = session.scalar(
        select(Doctor).where(Doctor.id == slot.doctor_id).with_for_update(read=True)
    )
    if doctor is None or not doctor.is_active:
        raise AppointmentError("slot_unavailable", "That doctor is not available for bookings.")
    if slot.start_time <= datetime.now(timezone.utc):
        raise AppointmentError("slot_started", "You cannot book a slot that has already started.")
    return doctor


def _booking_for_slot(session, slot_id):
    return session.scalar(select(Appointment).where(
        Appointment.slot_id == slot_id, Appointment.status == "booked",
    ))


def _patient_overlap(session, patient_id, slot, exclude_appointment_id=None):
    query = select(Appointment.id).join(
        AppointmentSlot, Appointment.slot_id == AppointmentSlot.id,
    ).where(
        Appointment.patient_id == patient_id,
        Appointment.status == "booked",
        AppointmentSlot.start_time < slot.end_time,
        AppointmentSlot.end_time > slot.start_time,
    )
    if exclude_appointment_id is not None:
        query = query.where(Appointment.id != exclude_appointment_id)
    return session.scalar(query.limit(1)) is not None


def appointment_details(appointment, slot, doctor):
    clinic = ZoneInfo("Asia/Kolkata")
    return {
        "appointment_id": appointment.id,
        "slot_id": slot.id,
        "status": appointment.status,
        "doctor_id": doctor.id,
        "doctor_name": doctor.name,
        "specialization": doctor.specialization,
        "starts_at": slot.start_time.astimezone(clinic).isoformat(),
        "ends_at": slot.end_time.astimezone(clinic).isoformat(),
    }


def book_appointment(patient_id: int, slot_id: int) -> dict:
    """Revalidate and book under row locks; repeated requests are idempotent.

    The existing PostgreSQL partial unique index is the final protection against
    double booking, even for writers outside this service. No slot flags change.
    """
    positive_id(patient_id, "patient_id")
    positive_id(slot_id, "slot_id")
    with SessionLocal.begin() as session:
        _lock_patient(session, patient_id)
        slot = session.scalar(select(AppointmentSlot).where(
            AppointmentSlot.id == slot_id,
        ).with_for_update())
        doctor = _available_doctor(session, slot)
        existing = _booking_for_slot(session, slot_id)
        if existing is not None:
            if existing.patient_id == patient_id:
                return {"ok": True, "code": "already_booked",
                        "appointment": appointment_details(existing, slot, doctor)}
            raise AppointmentError("slot_taken", "That slot was just booked. Please search again.")

        if _patient_overlap(session, patient_id, slot):
            raise AppointmentError("patient_overlap", "You already have a booking at that time.")

        appointment = Appointment(patient_id=patient_id, slot_id=slot_id, status="booked")
        session.add(appointment)
        session.flush()
        result = {"ok": True, "code": "booked",
                  "appointment": appointment_details(appointment, slot, doctor)}
    # Only report success after the transaction has committed.
    return result


def cancel_appointment(patient_id: int, appointment_id: int) -> dict:
    """Cancel an owned future booking. Use reschedule_appointment to move it."""
    positive_id(patient_id, "patient_id")
    positive_id(appointment_id, "appointment_id")
    with SessionLocal.begin() as session:
        _lock_patient(session, patient_id)
        appointment = session.scalar(select(Appointment).where(
            Appointment.id == appointment_id, Appointment.patient_id == patient_id,
        ).with_for_update())
        if appointment is None:
            raise AppointmentError("appointment_not_found", "No appointment with that ID was found in your account.")
        if appointment.status == "cancelled":
            return {"ok": True, "code": "already_cancelled", "appointment_id": appointment.id,
                    "status": "cancelled"}
        if appointment.status != "booked":
            raise AppointmentError("not_cancellable", "Only booked appointments can be cancelled.")

        old_slot = session.scalar(select(AppointmentSlot).where(
            AppointmentSlot.id == appointment.slot_id,
        ).with_for_update())
        if old_slot.start_time <= datetime.now(timezone.utc):
            raise AppointmentError("appointment_started", "An appointment that has already started cannot be cancelled.")

        appointment.status = "cancelled"
        result = {"ok": True, "code": "cancelled", "appointment_id": appointment.id,
                  "slot_id": appointment.slot_id, "status": "cancelled"}
    return result


def reschedule_appointment(patient_id: int, appointment_id: int, new_slot_id: int) -> dict:
    """Move an owned future booking in ONE transaction, preserving its history.

    Do not call the public cancel/book services here: each owns a separate
    transaction. This begin block commits both changes together, or rolls back
    both on any flush/commit exception. No transaction is held between LLM calls.
    """
    positive_id(patient_id, "patient_id")
    positive_id(appointment_id, "appointment_id")
    positive_id(new_slot_id, "new_slot_id")
    with SessionLocal.begin() as session:
        _lock_patient(session, patient_id)
        old = session.scalar(select(Appointment).where(
            Appointment.id == appointment_id, Appointment.patient_id == patient_id,
        ).with_for_update())
        if old is None:
            raise AppointmentError("appointment_not_found", "No appointment with that ID was found in your account.")
        if old.status == "rescheduled":
            raise AppointmentError("already_rescheduled", "This appointment was already moved. View your upcoming appointments before requesting another change.")
        if old.status != "booked":
            raise AppointmentError("not_reschedulable", "Only booked appointments can be rescheduled. Your appointment was not changed.")
        if old.slot_id == new_slot_id:
            raise AppointmentError("same_slot", "That is already your current slot; nothing was changed.")

        # All mutations lock the patient first. Slot IDs are locked in ascending
        # order so simultaneous reschedules cannot deadlock by swapping slots.
        slots = {slot.id: slot for slot in session.scalars(
            select(AppointmentSlot).where(AppointmentSlot.id.in_({old.slot_id, new_slot_id}))
            .order_by(AppointmentSlot.id).with_for_update()
        )}
        if slots[old.slot_id].start_time <= datetime.now(timezone.utc):
            raise AppointmentError("appointment_started", "An appointment that has already started cannot be rescheduled.")
        replacement = slots.get(new_slot_id)
        doctor = _available_doctor(session, replacement)
        if _booking_for_slot(session, new_slot_id) is not None:
            raise AppointmentError("slot_taken", "The new slot is unavailable. Your original appointment is unchanged.")
        if _patient_overlap(session, patient_id, replacement, exclude_appointment_id=old.id):
            raise AppointmentError("patient_overlap", "The new slot overlaps another booking. Your original appointment is unchanged.")

        old.status = "rescheduled"
        session.flush()  # UPDATE is sent, but it can still be rolled back.
        new = Appointment(patient_id=patient_id, slot_id=new_slot_id, status="booked")
        session.add(new)
        session.flush()  # INSERT/constraints checked; generates the new ID.
        result = {"ok": True, "code": "rescheduled", "previous_appointment_id": old.id,
                  "previous_status": "rescheduled", "appointment": appointment_details(new, replacement, doctor)}
    # A failed commit raises before this return; success is never reported early.
    return result
