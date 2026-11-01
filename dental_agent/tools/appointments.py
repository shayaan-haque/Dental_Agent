from typing import Annotated, Literal

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from dental_agent.services.appointments import get_patient_appointments
from dental_agent.tools.appointment_errors import appointment_result


@tool
def view_my_appointments(
    patient_id: Annotated[int, InjectedState("patient_id")],
    view: Literal["upcoming", "previous", "cancelled", "rescheduled", "all"] = "upcoming",
    limit: int = 8,
    offset: int = 0,
) -> dict:
    """Read the logged-in patient's bookings with appointment IDs and exact times.

    Use upcoming before cancelling/rescheduling to identify the correct booking.
    Ask which appointment if multiple match. Use previous for past/completed
    visits, cancelled for cancelled bookings, or all for history. The default is
    8 results; paginate using offset when has_more=true. No other patient's
    ID is accepted from the user. Times are Asia/Kolkata.
    """
    return appointment_result(get_patient_appointments, patient_id=patient_id,
                              view=view, limit=limit, offset=offset)
