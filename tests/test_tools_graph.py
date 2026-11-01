import importlib
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from dental_agent.services.booking import book_appointment as save_booking
from dental_agent.services.appointments import get_patient_appointments
from dental_agent.tools.booking import book_appointment
from dental_agent.tools.cancellation import cancel_appointment
from dental_agent.tools.appointments import view_my_appointments
from dental_agent.tools.rescheduling import reschedule_appointment

workflow = importlib.import_module("dental_agent.workflows.appointment_graph")


def call(name, args, index=1):
    return {"id": f"call-{index}", "name": name, "args": args, "type": "tool_call"}


def test_mutation_tools_hide_patient_identity_and_inject_trusted_state(database):
    for tool in (book_appointment, cancel_appointment, reschedule_appointment, view_my_appointments):
        assert "patient_id" not in tool.tool_call_schema.model_json_schema()["properties"]
    result = workflow.execute_tools({"patient_id": 1, "messages": [AIMessage(content="", tool_calls=[
        call("book_appointment", {"slot_id": 1, "patient_id": 2}),
    ])]})
    assert json.loads(result["messages"][0].content)["ok"]
    assert len(get_patient_appointments(1)["items"]) == 1
    assert get_patient_appointments(2)["items"] == []


@pytest.mark.parametrize("bad", [True, 0, -1, "1"])
def test_tool_rejects_nonpositive_and_coerced_slot_ids(bad):
    with pytest.raises(ValidationError):
        book_appointment.invoke({"patient_id": 1, "slot_id": bad})
    with pytest.raises(ValidationError):
        reschedule_appointment.invoke({"patient_id": 1, "appointment_id": 1, "new_slot_id": bad})


def test_parallel_cancel_and_book_batch_rejected_without_mutations(database):
    old_id = save_booking(1, 1)["appointment"]["appointment_id"]
    result = workflow.execute_tools({"patient_id": 1, "messages": [AIMessage(content="", tool_calls=[
        call("cancel_appointment", {"appointment_id": old_id}),
        call("book_appointment", {"slot_id": 2}, 2),
    ])]})
    assert all(json.loads(message.content)["code"] == "sequential_calls_required" for message in result["messages"])
    assert [item["slot_id"] for item in get_patient_appointments(1)["items"]] == [1]


def test_expected_tool_errors_are_structured(database):
    result = book_appointment.invoke({"patient_id": 1, "slot_id": 999})
    assert result["ok"] is False and result["code"] == "slot_unavailable"
    result = cancel_appointment.invoke({"patient_id": 1, "appointment_id": 999})
    assert result["ok"] is False and result["code"] == "appointment_not_found"


def test_failed_cancellation_blocks_booking_in_same_turn(database):
    from langchain_core.messages import HumanMessage

    result = workflow.execute_tools({"patient_id": 1, "messages": [
        HumanMessage(content="Move my visit"),
        AIMessage(content="", tool_calls=[call("cancel_appointment", {"appointment_id": 999})]),
        ToolMessage(content=json.dumps({"ok": False, "code": "appointment_not_found"}),
                    name="cancel_appointment", tool_call_id="call-1"),
        AIMessage(content="", tool_calls=[call("book_appointment", {"slot_id": 2}, 2)]),
    ]})
    assert json.loads(result["messages"][0].content)["code"] == "cancellation_failed"
    assert get_patient_appointments(1)["items"] == []


def test_rescheduling_requires_available_search_result(database):
    old_id = save_booking(1, 1)["appointment"]["appointment_id"]
    result = workflow.execute_tools({"patient_id": 1, "messages": [AIMessage(content="", tool_calls=[
        call("reschedule_appointment", {"appointment_id": old_id, "new_slot_id": 2}),
    ])]})
    assert json.loads(result["messages"][0].content)["code"] == "replacement_not_searched"
    assert [item["slot_id"] for item in get_patient_appointments(1)["items"]] == [1]


def test_legacy_replacement_argument_cannot_cancel_the_old_visit(database):
    old_id = save_booking(1, 1)["appointment"]["appointment_id"]
    result = workflow.execute_tools({"patient_id": 1, "messages": [AIMessage(content="", tool_calls=[
        call("cancel_appointment", {"appointment_id": old_id, "replacement_slot_id": 2}),
    ])]})
    assert json.loads(result["messages"][0].content)["code"] == "reschedule_tool_required"
    assert [item["slot_id"] for item in get_patient_appointments(1)["items"]] == [1]


def test_atomic_rescheduling_injects_patient_identity(database):
    old_id = save_booking(1, 1)["appointment"]["appointment_id"]
    result = workflow.execute_tools({"patient_id": 1, "messages": [
        ToolMessage(content=json.dumps([{"slot_id": 2}]), name="get_available_slots", tool_call_id="search"),
        AIMessage(content="", tool_calls=[call("reschedule_appointment", {"appointment_id": old_id, "new_slot_id": 2, "patient_id": 2})]),
    ]})
    assert json.loads(result["messages"][0].content)["ok"]
    assert [item["slot_id"] for item in get_patient_appointments(1)["items"]] == [2]
    assert get_patient_appointments(2)["items"] == []


@pytest.mark.parametrize("mutation", ["book_appointment", "cancel_appointment", "reschedule_appointment"])
@pytest.mark.parametrize("outcome", [{"ok": True, "code": "rescheduled"}, {"ok": False, "code": "slot_taken"}])
def test_no_automatic_followup_mutation_after_rescheduling(database, mutation, outcome):
    from langchain_core.messages import HumanMessage

    old_id = save_booking(1, 1)["appointment"]["appointment_id"]
    result = workflow.execute_tools({"patient_id": 1, "messages": [
        HumanMessage(content="Move my visit"),
        ToolMessage(content=json.dumps(outcome), name="reschedule_appointment", tool_call_id="move"),
        AIMessage(content="", tool_calls=[call(mutation, {"slot_id": 2, "appointment_id": old_id, "new_slot_id": 2})]),
    ]})
    assert json.loads(result["messages"][0].content)["code"] == "reschedule_finished"
    assert [item["slot_id"] for item in get_patient_appointments(1)["items"]] == [1]


def test_reschedule_in_parallel_batch_is_rejected_without_writes(database):
    old_id = save_booking(1, 1)["appointment"]["appointment_id"]
    result = workflow.execute_tools({"patient_id": 1, "messages": [AIMessage(content="", tool_calls=[
        call("reschedule_appointment", {"appointment_id": old_id, "new_slot_id": 2}),
        call("book_appointment", {"slot_id": 3}, 2),
    ])]})
    assert all(json.loads(message.content)["code"] == "sequential_calls_required" for message in result["messages"])
    assert [item["slot_id"] for item in get_patient_appointments(1)["items"]] == [1]


def test_legacy_cancel_then_book_flow_is_blocked(database):
    from langchain_core.messages import HumanMessage

    result = workflow.execute_tools({"patient_id": 1, "messages": [
        HumanMessage(content="Move to slot 2"),
        ToolMessage(content=json.dumps({"ok": True, "code": "cancelled"}),
                    name="cancel_appointment", tool_call_id="cancel-call"),
        AIMessage(content="", tool_calls=[call("book_appointment", {"slot_id": 3})]),
    ]})
    assert json.loads(result["messages"][0].content)["code"] == "reschedule_tool_required"
    assert get_patient_appointments(1)["items"] == []


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.inputs = []

    def invoke(self, messages):
        self.inputs.append(messages)
        return next(self.responses)


def test_graph_uses_dedicated_atomic_rescheduling_tool(database, monkeypatch):
    from zoneinfo import ZoneInfo
    from datetime import timedelta

    _, start = database
    old_id = save_booking(1, 1)["appointment"]["appointment_id"]
    requested = (start + timedelta(days=1)).astimezone(ZoneInfo("Asia/Kolkata"))
    steps = [
        call("view_my_appointments", {}, 1),
        call("get_available_slots", {"doctor_id": 1, "date_filter": requested.date().isoformat(),
                                     "time_filter": requested.strftime("%H:%M")}, 2),
        call("reschedule_appointment", {"appointment_id": old_id, "new_slot_id": 2}, 3),
    ]
    model = ScriptedModel([*[AIMessage(content="", tool_calls=[step]) for step in steps], AIMessage(content="Your replacement is booked.")])
    monkeypatch.setattr(workflow, "model_with_tools", model)
    result = workflow.graph.invoke({"patient_id": 1, "messages": [("user", "Move my appointment to the same time a day later.")]},
                                   config={"recursion_limit": 24})
    results = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert [message.name for message in results] == [step["name"] for step in steps]
    assert [item["slot_id"] for item in json.loads(results[1].content)] == [2]
    assert all(json.loads(message.content)["ok"] for message in (results[0], results[2]))
    assert [item["slot_id"] for item in get_patient_appointments(1)["items"]] == [2]
    assert "dedicated reschedule_appointment tool" in model.inputs[0][0].content


def test_no_available_replacement_does_not_cancel(database, monkeypatch):
    save_booking(1, 1)
    model = ScriptedModel([
        AIMessage(content="", tool_calls=[call("view_my_appointments", {}, 1)]),
        AIMessage(content="", tool_calls=[call("get_available_slots", {"doctor_id": 999}, 2)]),
        AIMessage(content="No matching slots. Your existing appointment is unchanged."),
    ])
    monkeypatch.setattr(workflow, "model_with_tools", model)
    result = workflow.graph.invoke({"patient_id": 1, "messages": [("user", "Change my visit only if the new slot is available.")]})
    assert [message.name for message in result["messages"] if isinstance(message, ToolMessage)] == ["view_my_appointments", "get_available_slots"]
    assert [item["slot_id"] for item in get_patient_appointments(1)["items"]] == [1]


def test_database_errors_do_not_leak_sql(monkeypatch):
    from sqlalchemy.exc import OperationalError
    module = importlib.import_module("dental_agent.tools.booking")

    def fail(**_):
        raise OperationalError("SECRET SQL", {}, Exception("password"))

    monkeypatch.setattr(module, "book", fail)
    result = book_appointment.invoke({"patient_id": 1, "slot_id": 1})
    assert not result["ok"] and result["code"] == "database_error"
    assert "SECRET" not in str(result) and "password" not in str(result)


def test_availability_failure_is_not_mistaken_for_no_slots(monkeypatch):
    from sqlalchemy.exc import OperationalError
    module = importlib.import_module("dental_agent.tools.availability")

    def fail(**_):
        raise OperationalError("SECRET SQL", {}, Exception("password"))

    monkeypatch.setattr(module, "fetch_slots", fail)
    result = module.get_available_slots.invoke({"doctor_id": 1})
    assert isinstance(result, dict) and not result["ok"]
    assert "SECRET" not in str(result)
