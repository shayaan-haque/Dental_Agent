"""Read-only appointment availability queries, independent of the agent."""

from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

from dental_agent.database import SessionLocal
from dental_agent.models.database_models import Appointment, AppointmentSlot, Doctor


def get_available_slots(
    doctor_id: int | None = None,
    doctor_name: str | None = None,
    specialization: str | None = None,
    date_filter: str | date | None = None,
    limit: int = 20,
    timezone: str = "Asia/Kolkata",
) -> list[dict]:
    """Return available slots, earliest first, without modifying the database.

    All filters are optional. Provided filters are combined with AND.
    Doctor names support case-insensitive partial matches; specializations
    match exactly after lowercasing and replacing spaces/hyphens with underscores.
    date_filter accepts YYYY-MM-DD or a date object and means a calendar day
    in the supplied IANA timezone. Returned timestamps use that timezone.

    Availability requires an active doctor, an enabled future slot, and no
    appointment with status 'booked'. This is a snapshot, not a reservation.
    Booking must revalidate availability in its own transaction.

    Returns an empty list when no slots match. Invalid arguments raise
    ValueError. Database errors propagate to the caller rather than being
    mistaken for an empty schedule. Results are capped at 100 per call.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    if doctor_id is not None and (
        isinstance(doctor_id, bool) or not isinstance(doctor_id, int) or doctor_id <= 0
    ):
        raise ValueError("doctor_id must be a positive integer")
    for name, value in (("doctor_name", doctor_name), ("specialization", specialization)):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
    try:
        local_timezone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("timezone must be a valid IANA timezone, e.g. Asia/Kolkata") from exc

    target_date = None
    if date_filter is not None:
        if isinstance(date_filter, str):
            try:
                target_date = datetime.strptime(date_filter.strip(), "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValueError("date_filter must use YYYY-MM-DD") from exc
        elif isinstance(date_filter, date) and not isinstance(date_filter, datetime):
            target_date = date_filter
        else:
            raise ValueError("date_filter must be a YYYY-MM-DD string or a date object")

    # NOT EXISTS excludes booked slots without duplicating rows from history.
    has_booking = select(Appointment.id).where(
        Appointment.slot_id == AppointmentSlot.id,
        Appointment.status == "booked",
    ).exists()

    query = (
        select(
            AppointmentSlot.id.label("slot_id"),
            Doctor.id.label("doctor_id"),
            Doctor.name.label("doctor_name"),
            Doctor.specialization,
            AppointmentSlot.start_time,
            AppointmentSlot.end_time,
        )
        .join(Doctor, AppointmentSlot.doctor_id == Doctor.id)
        .where(
            Doctor.is_active.is_(True),
            AppointmentSlot.is_enabled.is_(True),
            AppointmentSlot.start_time > datetime.now(dt_timezone.utc),
            ~has_booking,
        )
    )

    if doctor_id is not None:
        query = query.where(Doctor.id == doctor_id)
    if doctor_name and doctor_name.strip():
        # Escape SQL wildcard characters so user text is treated literally.
        query = query.where(
            func.lower(Doctor.name).contains(doctor_name.strip().lower(), autoescape=True)
        )
    if specialization and specialization.strip():
        normalized = specialization.strip().lower().replace("-", "_")
        normalized = "_".join(normalized.split())
        query = query.where(func.lower(Doctor.specialization) == normalized)
    if target_date is not None:
        day_start = datetime.combine(target_date, time.min, tzinfo=local_timezone)
        day_end = datetime.combine(
            target_date + timedelta(days=1), time.min, tzinfo=local_timezone
        )
        query = query.where(
            AppointmentSlot.start_time >= day_start,
            AppointmentSlot.start_time < day_end,
        )

    query = query.order_by(AppointmentSlot.start_time, Doctor.id, AppointmentSlot.id).limit(limit)
    with SessionLocal() as session:
        rows = session.execute(query).mappings().all()

    return [
        {
            "slot_id": row["slot_id"],
            "doctor_id": row["doctor_id"],
            "doctor_name": row["doctor_name"],
            "specialization": row["specialization"],
            "starts_at": row["start_time"].astimezone(local_timezone).isoformat(),
            "ends_at": row["end_time"].astimezone(local_timezone).isoformat(),
        }
        for row in rows
    ]
