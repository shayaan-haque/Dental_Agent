from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import Field

from dental_agent.services.booking import cancel_appointment as cancel
from dental_agent.tools.appointment_errors import appointment_result


@tool
def cancel_appointment(
    patient_id: Annotated[int, InjectedState("patient_id")],
    appointment_id: Annotated[int, Field(strict=True, gt=0)],
) -> dict:
    """Cancel the patient's explicitly requested future appointment, retaining history.

    Find appointment_id with view_my_appointments; never use slot_id in its place.
    This is only for an explicit cancellation, not for changing a visit's time.
    Use reschedule_appointment for changes; never cancel then book to reschedule.
    """
    return appointment_result(cancel, patient_id=patient_id, appointment_id=appointment_id)
