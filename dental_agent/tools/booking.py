from typing import Annotated
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import Field

from dental_agent.services.booking import book_appointment as book
from dental_agent.tools.appointment_errors import appointment_result

@tool
def book_appointment(
    patient_id: Annotated[int, InjectedState("patient_id")],
    slot_id: Annotated[int, Field(strict=True, gt=0)],
) -> dict:
    """
    Book the exact available slot the patient explicitly selected/requested.

    First search availability to identify slot_id. Never guess an ID or choose
    among ambiguous doctors/times without asking. Patient identity is injected
    by the backend. Only ok=true confirms a saved booking. Repeated calls for
    an existing owned booking return that booking instead of creating another.
    Use reschedule_appointment to change an existing visit; never cancel then book.
    """

    return appointment_result(book, patient_id=patient_id, slot_id=slot_id)
