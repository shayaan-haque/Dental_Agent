from copy import deepcopy
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from dental_agent.response_formatter import UNKNOWN, build_action_reply


APPOINTMENT = {
    "appointment_id": 17, "slot_id": 7, "doctor_id": 2,
    "doctor_name": "Emily Johnson", "specialization": "general_dentist", "status": "booked",
    "starts_at": "2026-11-03T03:30:00+00:00", "ends_at": "2026-11-03T04:00:00+00:00",
}


def action_call(name="book_appointment", call_id="action-1", args=None):
    if args is None:
        args = {"appointment_id": 17} if name == "cancel_appointment" else (
            {"appointment_id": 10, "new_slot_id": 7} if name == "reschedule_appointment" else {"slot_id": 7})
    return {"id": call_id, "name": name, "args": args, "type": "tool_call"}


def turn(payload, name="book_appointment"):
    call = action_call(name)
    return [HumanMessage(content="Please update my appointment"), AIMessage(content="", tool_calls=[call]),
            ToolMessage(content=json.dumps(payload), tool_call_id=call["id"], name=name),
            AIMessage(content="An unverified model claim")]


@pytest.mark.parametrize("code", ["booked", "already_booked"])
def test_booking_uses_returned_id_doctor_and_clinic_time(code):
    reply = build_action_reply(turn({"ok": True, "code": code, "appointment": APPOINTMENT}))
    assert "#17" in reply and "Emily Johnson" in reply
    assert "03 Nov 2026 at 09:00 AM IST" in reply
    assert ("Already booked" if code == "already_booked" else "Booking confirmed") in reply
    assert "unverified" not in reply


@pytest.mark.parametrize("code", ["cancelled", "already_cancelled"])
def test_cancellation_distinguishes_already_cancelled(code):
    reply = build_action_reply(turn({"ok": True, "code": code, "appointment_id": 17, "status": "cancelled"}, "cancel_appointment"))
    assert "#17" in reply
    assert ("was already cancelled" if code == "already_cancelled" else "has been cancelled") in reply


def test_rescheduling_uses_original_and_replacement_ids():
    reply = build_action_reply(turn({"ok": True, "code": "rescheduled", "previous_appointment_id": 10,
                                    "previous_status": "rescheduled", "appointment": APPOINTMENT}, "reschedule_appointment"))
    assert "#10 has been rescheduled" in reply and "#17" in reply and "Emily Johnson" in reply


@pytest.mark.parametrize("name", ["book_appointment", "cancel_appointment", "reschedule_appointment"])
def test_backend_failure_is_not_replaced_by_a_model_success(name):
    reply = build_action_reply(turn({"ok": False, "code": "slot_taken", "message": "That slot was just booked."}, name))
    assert reply.endswith("That slot was just booked.")
    assert "unverified" not in reply and "confirmed" not in reply


def test_uncertain_database_message_is_kept_uncertain():
    message = "Could not confirm the result. Check your saved appointments before retrying."
    assert build_action_reply(turn({"ok": False, "code": "database_error", "message": message})).endswith(message)


@pytest.mark.parametrize("payload", [
    None, [], {}, {"ok": "true"}, {"ok": 1}, {"ok": False}, {"ok": False, "message": "  "},
    {"ok": True, "code": "cancelled"}, {"ok": True, "code": []}, {"ok": True, "code": "booked"},
    {"ok": True, "code": "booked", "appointment": []},
])
def test_invalid_or_incomplete_results_never_confirm_success(payload):
    assert UNKNOWN in build_action_reply(turn(payload))


@pytest.mark.parametrize("updates", [
    {"appointment_id": True}, {"appointment_id": 0}, {"slot_id": 8}, {"doctor_id": -1},
    {"status": "cancelled"}, {"doctor_name": " "}, {"starts_at": "invalid"},
    {"starts_at": "2026-11-03T03:30:00"}, {"ends_at": "2026-11-03T03:00:00+00:00"},
])
def test_malformed_or_mismatched_booking_details_are_not_confirmed(updates):
    appointment = {**APPOINTMENT, **updates}
    assert UNKNOWN in build_action_reply(turn({"ok": True, "code": "booked", "appointment": appointment}))


@pytest.mark.parametrize("updates", [{"appointment_id": 18}, {"appointment_id": True}, {"status": "rescheduled"}])
def test_cancellation_must_match_the_requested_appointment(updates):
    payload = {"ok": True, "code": "cancelled", "appointment_id": 17, "status": "cancelled", **updates}
    assert UNKNOWN in build_action_reply(turn(payload, "cancel_appointment"))


@pytest.mark.parametrize("updates", [{"previous_appointment_id": 11}, {"previous_appointment_id": True}, {"previous_status": "cancelled"}])
def test_rescheduling_must_match_the_requested_original(updates):
    payload = {"ok": True, "code": "rescheduled", "previous_appointment_id": 10,
               "previous_status": "rescheduled", "appointment": APPOINTMENT, **updates}
    assert UNKNOWN in build_action_reply(turn(payload, "reschedule_appointment"))


def test_missing_malformed_or_wrongly_named_tool_messages_are_unverified():
    messages = turn({"ok": True, "code": "booked", "appointment": APPOINTMENT})
    for replacement in (None, messages[2].model_copy(update={"content": "not JSON"}),
                        messages[2].model_copy(update={"name": "get_available_slots"}),
                        messages[2].model_copy(update={"tool_call_id": "unrelated"})):
        copy = [*messages[:2], *([replacement] if replacement is not None else []), messages[-1]]
        assert UNKNOWN in build_action_reply(copy)


def test_call_id_is_sufficient_when_tool_message_name_is_omitted():
    messages = turn({"ok": True, "code": "booked", "appointment": APPOINTMENT})
    messages[2] = messages[2].model_copy(update={"name": None})
    assert "Booking confirmed" in build_action_reply(messages)


def test_duplicate_tool_results_or_call_ids_are_ambiguous():
    messages = turn({"ok": True, "code": "booked", "appointment": APPOINTMENT})
    assert UNKNOWN in build_action_reply([*messages, messages[2]])
    assert UNKNOWN in build_action_reply([*messages, messages[1]])


def test_successful_attempt_is_not_hidden_by_a_later_rejection():
    messages = turn({"ok": True, "code": "booked", "appointment": APPOINTMENT})[:-1]
    call = action_call(call_id="action-2", args={"slot_id": 8})
    messages.extend([AIMessage(content="", tool_calls=[call]),
                     ToolMessage(content=json.dumps({"ok": False, "code": "slot_taken", "message": "That slot was just booked."}),
                                 tool_call_id="action-2", name="book_appointment"),
                     AIMessage(content="Nothing was booked")])
    reply = build_action_reply(messages)
    assert "Booking attempt 1: Booking confirmed" in reply
    assert "Booking attempt 2: That slot was just booked." in reply


def test_out_of_order_results_are_matched_by_call_id():
    first = action_call()
    second = action_call("cancel_appointment", "action-2")
    messages = [AIMessage(content="", tool_calls=[first, second]),
                ToolMessage(content=json.dumps({"ok": True, "code": "cancelled", "appointment_id": 17, "status": "cancelled"}),
                            tool_call_id="action-2", name="cancel_appointment"),
                ToolMessage(content=json.dumps({"ok": True, "code": "booked", "appointment": APPOINTMENT}),
                            tool_call_id="action-1", name="book_appointment")]
    reply = build_action_reply(messages)
    assert reply.startswith("Booking attempt 1: Booking confirmed")
    assert "Cancellation attempt 2: Appointment #17 has been cancelled." in reply


def test_ordinary_chat_and_read_only_tools_do_not_get_action_replies():
    assert build_action_reply([HumanMessage(content="Hello"), AIMessage(content="Hi")]) is None
    assert build_action_reply([
        AIMessage(content="", tool_calls=[action_call("get_available_slots", args={})]),
        ToolMessage(content="[]", tool_call_id="action-1", name="get_available_slots"),
    ]) is None


def test_orphan_action_results_do_not_fall_back_to_the_model_claim():
    assert build_action_reply([ToolMessage(content='{"ok":true}', tool_call_id="missing", name="book_appointment")]) == UNKNOWN


def test_formatting_does_not_modify_tool_history():
    messages = turn({"ok": True, "code": "booked", "appointment": APPOINTMENT})
    before = deepcopy(messages)
    build_action_reply(messages)
    assert messages == before
