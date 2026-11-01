from datetime import datetime
from typing import Literal

from pydantic import BaseModel


AppointmentView = Literal["upcoming", "previous", "cancelled", "rescheduled", "all"]


class AppointmentResponse(BaseModel):
    appointment_id: int
    slot_id: int
    status: Literal["booked", "cancelled", "completed", "rescheduled"]
    doctor_id: int
    doctor_name: str
    specialization: str
    starts_at: datetime
    ends_at: datetime


class AppointmentListResponse(BaseModel):
    items: list[AppointmentResponse]
    has_more: bool
    limit: int
    offset: int
