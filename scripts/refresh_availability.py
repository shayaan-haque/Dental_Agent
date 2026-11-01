"""Replace unused future availability without deleting doctors or booking history.

Preview: python -m scripts.refresh_availability
Apply:   python -m scripts.refresh_availability --apply
Dates include today through today + --days-ahead (10 means 11 calendar days).
"""

import argparse
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, text

from dental_agent.database import SessionLocal
from dental_agent.models.database_models import Appointment, AppointmentSlot, Doctor


def refresh_availability(session, start_date, days_ahead=10, *, apply=False, now=None):
    """Plan/apply inside the caller's transaction; never commit partial changes.

    Only active doctors are seeded. Future slots referenced by ANY appointment
    status are preserved. Unreferenced past/ongoing slots are also preserved.
    New half-hour slots run daily 09:00–12:00 IST, including weekends.
    """
    clinic = ZoneInfo("Asia/Kolkata")
    now = now or datetime.now(clinic)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(clinic)
    if not isinstance(start_date, date) or isinstance(start_date, datetime) or start_date < now.date():
        raise ValueError("start_date must be today or a future date")
    if isinstance(days_ahead, bool) or not isinstance(days_ahead, int) or not 0 <= days_ahead <= 365:
        raise ValueError("days_ahead must be between 0 and 365")

    if apply and session.bind.dialect.name == "postgresql":
        # Brief maintenance lock: fail rather than race a booking/cancellation.
        # Honor schema_translate_map so tests never lock application tables.
        connection = session.connection()
        preparer = connection.dialect.identifier_preparer
        names = []
        for table in (AppointmentSlot.__table__, Appointment.__table__):
            schema = connection.schema_for_object(table)
            name = preparer.quote(table.name)
            names.append(f"{preparer.quote_schema(schema)}.{name}" if schema else name)
        session.execute(text(f"LOCK TABLE {', '.join(names)} IN ACCESS EXCLUSIVE MODE NOWAIT"))

    query = select(Doctor).where(Doctor.is_active.is_(True)).order_by(Doctor.id)
    if apply:
        query = query.with_for_update(read=True, nowait=True)
    doctors = session.scalars(query).all()
    if not doctors:
        raise ValueError("No active doctor profiles found; nothing was changed")
    doctor_ids = [doctor.id for doctor in doctors]

    linked = select(Appointment.id).where(Appointment.slot_id == AppointmentSlot.id).exists()
    replaceable_ids = set(session.scalars(select(AppointmentSlot.id).where(
        AppointmentSlot.doctor_id.in_(doctor_ids),
        AppointmentSlot.start_time > now,
        ~linked,
    )).all())

    end_date = start_date + timedelta(days=days_ahead)
    window_start = datetime.combine(start_date, time.min, tzinfo=clinic)
    window_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=clinic)
    retained = session.scalars(select(AppointmentSlot).where(
        AppointmentSlot.doctor_id.in_(doctor_ids),
        AppointmentSlot.start_time < window_end,
        AppointmentSlot.end_time > window_start,
    )).all()
    retained_by_doctor = {doctor_id: [] for doctor_id in doctor_ids}
    for slot in retained:
        if slot.id not in replaceable_ids:
            retained_by_doctor[slot.doctor_id].append(slot)

    additions = []
    overlaps = elapsed = 0
    for doctor in doctors:
        for day in range(days_ahead + 1):
            start = datetime.combine(start_date + timedelta(days=day), time(9), tzinfo=clinic)
            for index in range(6):
                slot_start = start + timedelta(minutes=30 * index)
                slot_end = slot_start + timedelta(minutes=30)
                if slot_start <= now:
                    elapsed += 1
                    continue
                if any(slot.start_time < slot_end and slot.end_time > slot_start
                       for slot in retained_by_doctor[doctor.id]):
                    overlaps += 1
                    continue
                additions.append(AppointmentSlot(doctor_id=doctor.id, start_time=slot_start,
                                                 end_time=slot_end, is_enabled=True))

    summary = {
        "mode": "apply" if apply else "preview",
        "timezone": clinic.key,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hours": "09:00-12:00 daily; 30-minute slots",
        "active_doctors": len(doctors),
        "future_unlinked_slots_to_replace": len(replaceable_ids),
        "new_slots": len(additions),
        "history_overlaps_skipped": overlaps,
        "elapsed_slots_skipped": elapsed,
        "appointments_preserved": session.scalar(select(func.count()).select_from(Appointment)),
    }
    if apply:
        if replaceable_ids:
            session.execute(delete(AppointmentSlot).where(AppointmentSlot.id.in_(replaceable_ids)))
        session.add_all(additions)
        session.flush()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes; default is read-only preview")
    parser.add_argument("--start-date", type=date.fromisoformat, help="First clinic date; default today (IST)")
    parser.add_argument("--days-ahead", type=int, default=10, help="Days after the first date, inclusive (default 10)")
    args = parser.parse_args()
    clinic = ZoneInfo("Asia/Kolkata")
    with SessionLocal.begin() as session:
        summary = refresh_availability(session, args.start_date or datetime.now(clinic).date(),
                                       args.days_ahead, apply=args.apply)
    print(json.dumps(summary, indent=2))
    print("Committed successfully." if args.apply else "Preview only; run with --apply to make these changes.")


if __name__ == "__main__":
    main()
