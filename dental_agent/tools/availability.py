from langchain_core.tools import tool
from dental_agent.services.availability import (
    get_available_slots as fetch_slots
)


@tool
def get_available_slots(
    doctor_id: int | None = None,
    doctor_name: str | None = None,
    specialization: str | None = None,
    date_filter: str | None = None
) -> list[dict]:
    """
    Search for available dental appointment slots.

    Use this tool when a patient asks:
    - Which dentists are available?
    - Show appointments with a particular doctor.
    - Find dentists by specialization.
    - Find available appointments on a specific date.
    -date_filter must use YYYY-MM-DD.
    -specialization uses names such as general_dentist, oral_surgeon, orthodontist, cosmetic_dentist,prosthodontist, pediatric_dentist, emergency_dentist.
    -Returned times use Asia/Kolkata. Results are limited to 20 slots

    All filters are optional and can be combined.
    This tool only reads availability; it does not book appointments.
    """

    return fetch_slots(
        doctor_name=doctor_name,
        specialization=specialization,
        date_filter=date_filter,
        doctor_id=doctor_id,
    )