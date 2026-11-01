import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from dental_agent.workflows.message_budget import model_messages
from dental_agent.workflows.appointment_graph import model


def test_default_output_request_fits_current_provider_tier():
    assert model.max_tokens == 256
    assert model.max_retries == 0


def test_context_keeps_complete_recent_turns_not_orphan_tool_results():
    messages = []
    for number in range(8):
        messages.extend([
            HumanMessage(content=f"Question {number}"),
            AIMessage(content="", tool_calls=[{"name": "get_available_slots", "id": f"call-{number}", "args": {}}]),
            ToolMessage(content="[]", tool_call_id=f"call-{number}"),
            AIMessage(content="No matching slots."),
        ])
    messages.append(HumanMessage(content="And tomorrow?"))
    selected = model_messages(messages, previous_turns=2)
    assert isinstance(selected[0], HumanMessage)
    assert selected[0].content == "Question 6"
    assert len(selected) == 9
    assert len(messages) == 33  # Stored history is not modified.
    assert [item.tool_call_id for item in selected if isinstance(item, ToolMessage)] == ["call-6", "call-7"]


def test_character_budget_never_cuts_current_tool_chain():
    current = [HumanMessage(content="Book"), AIMessage(content="", tool_calls=[{"name": "book_appointment", "id": "b", "args": {"slot_id": 1}}]),
               ToolMessage(content=json.dumps({"ok": True, "appointment_id": 1}), tool_call_id="b")]
    selected = model_messages([HumanMessage(content="x" * 10000), AIMessage(content="old reply"), *current], max_chars=1)
    assert len(selected) == 3
    assert selected[0].content == "Book"
    assert selected[-1].tool_call_id == "b"
    assert json.loads(selected[-1].content)["ok"]


def test_tool_json_is_compacted_and_empty_list_stays_explicit():
    selected = model_messages([HumanMessage(content="Find"), ToolMessage(content=[], tool_call_id="a")])
    assert selected[-1].content == "[]"
    selected = model_messages([HumanMessage(content="Find"), ToolMessage(content='{"ok": true, "items": []}', tool_call_id="a")])
    assert selected[-1].content == '{"ok":true,"items":[]}'
