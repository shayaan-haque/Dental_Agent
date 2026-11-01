from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import Field

from dental_agent.services.booking import reschedule_appointment as reschedule
from dental_agent.tools.appointment_errors import appointment_result


@tool
def reschedule_appointment(
    patient_id: Annotated[int, InjectedState("patient_id")],
    appointment_id: Annotated[int, Field(strict=True, gt=0)],
    new_slot_id: Annotated[int, Field(strict=True, gt=0)],
) -> dict:
    """Atomically move the patient's explicitly selected future appointment.

    First identify appointment_id with view_my_appointments and find new_slot_id
    with get_available_slots using the exact requested doctor/date/time. Ask if
    ambiguous. Never call cancel_appointment or book_appointment for this change.
    The backend rechecks availability under locks and commits both changes
    together. If validation/insertion fails, the original booking stays intact.
    Only ok=true confirms success: the old record is retained as 'rescheduled'
    and the response contains the new booked appointment ID, doctor and times.
    For an uncertain database/provider outcome, view saved appointments before
    retrying. An already-rescheduled ID is rejected rather than moved twice.
    """
    return appointment_result(reschedule, patient_id=patient_id,
                              appointment_id=appointment_id, new_slot_id=new_slot_id)
