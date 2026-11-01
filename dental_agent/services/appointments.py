"""Read appointment IDs/details for the authenticated patient's chat tools."""

from datetime import datetime, timezone

from sqlalchemy import or_, select

from dental_agent.database import SessionLocal
from dental_agent.models.database_models import Appointment, AppointmentSlot, Doctor
from dental_agent.services.booking import appointment_details, positive_id


def get_patient_appointments(patient_id: int, view: str = "upcoming", limit: int = 20, offset: int = 0) -> dict:
    positive_id(patient_id, "patient_id")
    if view not in {"upcoming", "previous", "cancelled", "rescheduled", "all"}:
        raise ValueError("Unsupported appointment view")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a nonnegative integer")
    query = select(Appointment, AppointmentSlot, Doctor).join(
        AppointmentSlot, Appointment.slot_id == AppointmentSlot.id,
    ).join(Doctor, AppointmentSlot.doctor_id == Doctor.id).where(Appointment.patient_id == patient_id)
    now = datetime.now(timezone.utc)
    if view == "upcoming":
        query = query.where(Appointment.status == "booked", AppointmentSlot.end_time > now)
    elif view == "previous":
        query = query.where(
            Appointment.status.in_(["booked", "completed"]),
            or_(AppointmentSlot.end_time <= now, Appointment.status == "completed"),
        )
    elif view in {"cancelled", "rescheduled"}:
        query = query.where(Appointment.status == view)
    ordering = AppointmentSlot.start_time.asc() if view == "upcoming" else AppointmentSlot.start_time.desc()
    with SessionLocal() as session:
        rows = session.execute(query.order_by(ordering, Appointment.id)
                               .limit(limit + 1).offset(offset)).all()
        return {"ok": True, "items": [appointment_details(*row) for row in rows[:limit]],
                "has_more": len(rows) > limit, "limit": limit, "offset": offset}
