"""Preview or insert development doctors and future appointment slots.

Run from the project root:
    python3 -m scripts.seed_database
    python3 -m scripts.seed_database --apply
"""

import argparse
import csv
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from dental_agent.database import SessionLocal
from dental_agent.models.database_models import AppointmentSlot, Doctor


CSV_PATH = Path(__file__).resolve().parent.parent / "doctor_availability.csv"


def load_doctors():
    with CSV_PATH.open(newline="", encoding="utf-8") as source:
        doctors = {
            (row["doctor_name"].strip().lower(), row["specialization"].strip().lower())
            for row in csv.DictReader(source)
        }
    if not doctors or any(not name or not specialty for name, specialty in doctors):
        raise ValueError("CSV must contain nonempty doctor names and specializations")
    return sorted(doctors)


def generate_slots(start_date, timezone):
    """Five weekdays, six half-hour slots per day, starting at 09:00."""
    slots = []
    day = start_date
    weekdays = 0
    while weekdays < 5:
        if day.weekday() < 5:
            start = datetime.combine(day, time(9), tzinfo=timezone)
            for _ in range(6):
                end = start + timedelta(minutes=30)
                slots.append((start, end))
                start = end
            weekdays += 1
        day += timedelta(days=1)
    return slots


def seed(apply, start_date, timezone):
    doctors = load_doctors()
    slots = generate_slots(start_date, timezone)
    print(f"Mode: {'APPLY' if apply else 'PREVIEW (no database writes)'}")
    print(f"Timezone: {timezone.key}")
    print(f"Dates: {slots[0][0].date()} through {slots[-1][0].date()}")
    print("Hours: 09:00–12:00, weekdays only, 30-minute slots")
    print(f"Source: {len(doctors)} doctors; {len(slots)} proposed slots per doctor")
    print("Users and appointments will not be modified.")

    new_doctors = new_slots = skipped_slots = 0
    # One transaction: any failure rolls back every insertion in this run.
    with SessionLocal.begin() as session:
        for name, specialization in doctors:
            matches = session.scalars(
                select(Doctor).where(
                    Doctor.name == name,
                    Doctor.specialization == specialization,
                )
            ).all()
            if len(matches) > 1:
                raise ValueError(f"Duplicate doctor records for {name}; resolve before seeding")
            doctor = matches[0] if matches else None
            if doctor is not None and not doctor.is_active:
                print(f"Skipping inactive doctor: {name}")
                continue
            if doctor is None:
                new_doctors += 1
                if apply:
                    doctor = Doctor(name=name, specialization=specialization, is_active=True)
                    session.add(doctor)
                    session.flush()
                print(f"{'Adding' if apply else 'Would add'} doctor: {name} | {specialization}")
            else:
                print(f"Keeping doctor: {name} | {specialization} | id={doctor.id}")

            existing = []
            if doctor is not None:
                existing = session.scalars(
                    select(AppointmentSlot).where(
                        AppointmentSlot.doctor_id == doctor.id,
                        AppointmentSlot.start_time < slots[-1][1],
                        AppointmentSlot.end_time > slots[0][0],
                    )
                ).all()
            added = skipped = 0
            for start, end in slots:
                if any(slot.start_time < end and slot.end_time > start for slot in existing):
                    skipped += 1
                    continue
                if apply:
                    session.add(AppointmentSlot(
                        doctor_id=doctor.id,
                        start_time=start,
                        end_time=end,
                        is_enabled=True,
                    ))
                added += 1
            new_slots += added
            skipped_slots += skipped
            print(f"  Slots: {added} {'added' if apply else 'would be added'}, {skipped} overlaps skipped")

    print(f"Summary: {new_doctors} new doctors, {new_slots} new slots, {skipped_slots} skipped slots")
    print("Committed successfully." if apply else "Preview complete. Run with --apply to insert.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Insert records; otherwise only preview")
    parser.add_argument("--timezone", default="Asia/Kolkata")
    parser.add_argument("--start-date", type=date.fromisoformat, help="First day (YYYY-MM-DD); default tomorrow")
    args = parser.parse_args()
    timezone = ZoneInfo(args.timezone)
    today = datetime.now(timezone).date()
    start_date = args.start_date or today + timedelta(days=1)
    if start_date <= today:
        parser.error("--start-date must be after today in the selected timezone")
    seed(args.apply, start_date, timezone)


if __name__ == "__main__":
    main()
