"""Authoritative action replies at the API boundary, without another model call."""

import json
from collections import Counter
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, ToolMessage

from dental_agent.schemas.appointments import AppointmentResponse


UNKNOWN = (
    "I couldn't confirm the outcome. "
    "Please check My appointments before retrying."
)

ACTION_LABELS = {
    "book_appointment": "Booking",
    "cancel_appointment": "Cancellation",
    "reschedule_appointment": "Rescheduling",
}

SUCCESS_CODES = {
    "book_appointment": {"booked", "already_booked"},
    "cancel_appointment": {"cancelled", "already_cancelled"},
    "reschedule_appointment": {"rescheduled"},
}


def _positive_id(value):
    return type(value) is int and value > 0


def format_action_result(call, data):
    """Use safe service errors or validated, committed success details only."""
    if not isinstance(data, dict):
        return UNKNOWN
    if data.get("ok") is False:
        message = data.get("message")
        return message if isinstance(message, str) and message.strip() else UNKNOWN

    action = call["name"]
    code = data.get("code")
    if data.get("ok") is not True or not isinstance(code, str) or code not in SUCCESS_CODES[action]:
        return UNKNOWN

    if action == "cancel_appointment":
        appointment_id = data.get("appointment_id")
        requested_id = call["args"].get("appointment_id")
        if (not _positive_id(appointment_id) or not _positive_id(requested_id)
                or appointment_id != requested_id or data.get("status") != "cancelled"):
            return UNKNOWN
        if code == "already_cancelled":
            return f"Appointment #{appointment_id} was already cancelled."
        return f"Appointment #{appointment_id} has been cancelled."

    raw = data["appointment"]
    if not isinstance(raw, dict) or any(not _positive_id(raw.get(key))
                                        for key in ("appointment_id", "slot_id", "doctor_id")):
        return UNKNOWN
    appointment = AppointmentResponse.model_validate(raw)
    requested_slot = call["args"].get("new_slot_id" if action == "reschedule_appointment" else "slot_id")
    if (not _positive_id(requested_slot) or appointment.slot_id != requested_slot
            or appointment.status != "booked" or not appointment.doctor_name.strip()
            or appointment.starts_at.tzinfo is None or appointment.ends_at.tzinfo is None
            or appointment.ends_at <= appointment.starts_at):
        return UNKNOWN

    starts = appointment.starts_at.astimezone(ZoneInfo("Asia/Kolkata"))
    when = starts.strftime("%d %b %Y at %I:%M %p IST")
    details = f"Appointment #{appointment.appointment_id} with {appointment.doctor_name} for {when}."

    if action == "reschedule_appointment":
        old_id = data.get("previous_appointment_id")
        requested_id = call["args"].get("appointment_id")
        if (not _positive_id(old_id) or not _positive_id(requested_id) or old_id != requested_id
                or old_id == appointment.appointment_id or data.get("previous_status") != "rescheduled"):
            return UNKNOWN
        return f"Appointment #{old_id} has been rescheduled. {details}"
    if code == "already_booked":
        return f"Already booked: {details}"
    return f"Booking confirmed: {details}"


def build_action_reply(turn_messages):
    """Render this request's attempted mutations; None means ordinary chat.

    Match each result to its tool_call_id, not its position or a prior turn's
    success. Keep all attempts so a later rejection cannot hide a committed
    success. Missing, ambiguous, or malformed results are never confirmations.
    """
    calls = [call for message in turn_messages if isinstance(message, AIMessage)
             for call in message.tool_calls]
    call_counts = Counter(call["id"] for call in calls)
    action_calls = [call for call in calls if call["name"] in ACTION_LABELS]
    if not action_calls:
        if any(isinstance(message, ToolMessage) and message.name in ACTION_LABELS for message in turn_messages):
            return UNKNOWN  # An orphan result is not proof of a matched action.
        return None

    results = {}
    for message in turn_messages:
        if isinstance(message, ToolMessage):
            results.setdefault(message.tool_call_id, []).append(message)

    replies = []
    for index, call in enumerate(action_calls, start=1):
        try:
            matches = results.get(call["id"], [])
            if call_counts[call["id"]] != 1 or len(matches) != 1:
                raise ValueError("Missing or ambiguous action result")
            message = matches[0]
            if message.name is not None and message.name != call["name"]:
                raise ValueError("Tool result does not match the action")
            reply = format_action_result(call, json.loads(message.content))
        except (KeyError, TypeError, ValueError):
            reply = UNKNOWN
        label = ACTION_LABELS[call["name"]]
        if len(action_calls) > 1:
            label += f" attempt {index}"
        replies.append(f"{label}: {reply}")
    return "\n\n".join(replies)
