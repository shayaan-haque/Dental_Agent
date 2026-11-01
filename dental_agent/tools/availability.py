from langchain_core.tools import tool
from dental_agent.services.availability import (
    get_available_slots as fetch_slots
)
from dental_agent.tools.appointment_errors import appointment_result


@tool
def get_available_slots(
    doctor_id: int | None = None,
    doctor_name: str | None = None,
    specialization: str | None = None,
    date_filter: str | None = None,
    time_filter: str | None = None,
) -> list[dict] | dict:
    """
    Search for available dental appointment slots.

    Use this tool when a patient asks:
    - Which dentists are available?
    - Show appointments with a particular doctor.
    - Find dentists by specialization.
    - Find available appointments on a specific date.
    -date_filter must use YYYY-MM-DD.
    -time_filter uses HH:MM (24-hour Asia/Kolkata) and requires date_filter.
     Always use it when a patient requests an exact time, especially rescheduling.
    -specialization uses names such as general_dentist, oral_surgeon, orthodontist, cosmetic_dentist,prosthodontist, pediatric_dentist, emergency_dentist.
    -Returned times use Asia/Kolkata. Results are limited to the earliest 8 slots.
     Narrow the doctor/date/time filters if a requested slot is not in the result.

    All filters are optional and can be combined.
    This tool only reads availability; it does not book appointments.
    """

    return appointment_result(
        fetch_slots,
        doctor_name=doctor_name,
        specialization=specialization,
        date_filter=date_filter,
        doctor_id=doctor_id,
        time_filter=time_filter,
        limit=8,
    )
