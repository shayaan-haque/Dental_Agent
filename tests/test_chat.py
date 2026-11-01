from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from time import time

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph.message import add_messages

import dental_agent.api as api
from dental_agent.dependencies import get_current_user
from dental_agent.models.database_models import User
from dental_agent.security import create_access_token
from dental_agent.services.chat_memory import ChatMemory, ClosedConversation, MemoryFull


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "chat_memory", ChatMemory())
    api.app.dependency_overrides[get_current_user] = lambda: User(id=1, name="Patient", email="patient@example.com")
    with TestClient(api.app) as client:
        client.cookies.set("access_token", create_access_token(1))
        yield client
    api.app.dependency_overrides.clear()


def test_chat_requires_authentication():
    with TestClient(api.app) as client:
        assert client.post("/api/chat", json={"message": "Book slot 1"}).status_code == 401


def test_chat_injects_identity_and_preserves_server_history(client, monkeypatch):
    inputs = []

    class FakeGraph:
        def invoke(self, state, config):
            inputs.append(state)
            return {"messages": add_messages(state["messages"], [AIMessage(content="reply")])}

    monkeypatch.setattr(api, "graph", FakeGraph())
    assert client.post("/api/chat", json={"message": "Find slots", "patient_id": 999}).status_code == 200
    assert client.post("/api/chat", json={"message": "Book that"}).status_code == 200
    assert inputs[0]["patient_id"] == 1
    assert len(inputs[1]["messages"]) == 3
    client.cookies.set("access_token", create_access_token(1))
    assert client.post("/api/chat", json={"message": "Fresh login"}).status_code == 200
    assert len(inputs[-1]["messages"]) == 1


def test_logout_clears_memory_and_blocks_replayed_chat_in_this_process(client, monkeypatch):
    class FakeGraph:
        def invoke(self, state, config):
            return {"messages": add_messages(state["messages"], [AIMessage(content="reply")])}

    monkeypatch.setattr(api, "graph", FakeGraph())
    token = client.cookies.get("access_token")
    assert client.post("/api/chat", json={"message": "hello"}).status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert all(not entry.turns for entry in api.chat_memory.entries.values())
    client.cookies.set("access_token", token)
    assert client.post("/api/chat", json={"message": "Book"}).status_code == 401


def test_provider_error_returns_uncertain_outcome_warning(client, monkeypatch):
    class FakeGraph:
        def invoke(self, *_args, **_kwargs):
            raise RuntimeError("private provider details")

    monkeypatch.setattr(api, "graph", FakeGraph())
    result = client.post("/api/chat", json={"message": "Book"})
    assert result.status_code == 503
    assert "may already have completed" in result.json()["detail"]
    assert "private" not in result.text


def test_blank_message_does_not_invoke_graph(client):
    assert client.post("/api/chat", json={"message": "  "}).status_code == 422


def test_provider_rate_limit_returns_retry_after_and_database_page_guidance(client, monkeypatch):
    import httpx
    from groq import RateLimitError

    class LimitedGraph:
        def invoke(self, *_args, **_kwargs):
            response = httpx.Response(429, headers={"retry-after": "8"},
                                      request=httpx.Request("POST", "https://example.com/chat"))
            raise RateLimitError("private organisation details", response=response, body={"error": "rate_limit_exceeded"})

    monkeypatch.setattr(api, "graph", LimitedGraph())
    response = client.post("/api/chat", json={"message": "Find appointments"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "8"
    assert "My appointments still works without AI tokens" in response.json()["detail"]
    assert "private" not in response.text


def test_tool_failure_overrides_false_success_and_corrects_saved_history(client, monkeypatch, database):
    from dental_agent.services.booking import book_appointment
    from dental_agent.tools.booking import book_appointment as book_tool

    book_appointment(2, 1)  # Another patient already owns the requested slot.
    inputs = []

    class FakeGraph:
        def invoke(self, state, config):
            inputs.append(state)
            if len(inputs) > 1:
                return {"messages": add_messages(state["messages"], [AIMessage(content="Which doctor would you prefer?")])}
            result = book_tool.invoke({"patient_id": state["patient_id"], "slot_id": 1})
            return {"messages": add_messages(state["messages"], [
                AIMessage(content="", tool_calls=[{"name": "book_appointment", "args": {"slot_id": 1}, "id": "book-1"}]),
                ToolMessage(content=json.dumps(result), tool_call_id="book-1", name="book_appointment"),
                AIMessage(content="Your appointment was successfully booked."),
            ])}

    monkeypatch.setattr(api, "graph", FakeGraph())
    response = client.post("/api/chat", json={"message": "Book slot 1"})
    assert response.status_code == 200
    assert response.json()["reply"] == "Booking: That slot was just booked. Please search again."
    assert len(inputs) == 1  # The API does not replay the graph or call another model.
    response = client.post("/api/chat", json={"message": "What other options do I have?"})
    assert response.json()["reply"] == "Which doctor would you prefer?"
    assert inputs[1]["messages"][-2].content == "Booking: That slot was just booked. Please search again."
    assert all(message.content != "Your appointment was successfully booked."
               for message in inputs[1]["messages"] if isinstance(message, AIMessage))


@pytest.mark.parametrize("action", ["book_appointment", "cancel_appointment", "reschedule_appointment"])
def test_action_confirmation_uses_backend_result_not_false_model_reply(client, monkeypatch, database, action):
    from dental_agent.services.booking import book_appointment
    from dental_agent.tools.booking import book_appointment as book_tool
    from dental_agent.tools.cancellation import cancel_appointment as cancel_tool
    from dental_agent.tools.rescheduling import reschedule_appointment as reschedule_tool

    if action == "book_appointment":
        operation, args = book_tool, {"slot_id": 1}
    else:
        old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
        operation = cancel_tool if action == "cancel_appointment" else reschedule_tool
        args = {"appointment_id": old_id}
        if action == "reschedule_appointment":
            args["new_slot_id"] = 2

    class FakeGraph:
        def invoke(self, state, config):
            result = operation.invoke({"patient_id": state["patient_id"], **args})
            return {"messages": add_messages(state["messages"], [
                AIMessage(content="", tool_calls=[{"name": action, "args": args, "id": "action-1"}]),
                ToolMessage(content=json.dumps(result), tool_call_id="action-1", name=action),
                AIMessage(content="The operation failed. No changes were made."),
            ])}

    monkeypatch.setattr(api, "graph", FakeGraph())
    response = client.post("/api/chat", json={"message": "Please change my appointment"})
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "No changes were made" not in reply
    assert {"book_appointment": "Booking confirmed", "cancel_appointment": "has been cancelled",
            "reschedule_appointment": "has been rescheduled"}[action] in reply
    entry = next(iter(api.chat_memory.entries.values()))
    assert entry.messages[-1].content == reply


def test_missing_action_result_cannot_use_model_success(client, monkeypatch):
    class FakeGraph:
        def invoke(self, state, config):
            return {"messages": add_messages(state["messages"], [
                AIMessage(content="", tool_calls=[{"name": "book_appointment", "args": {"slot_id": 1}, "id": "missing-result"}]),
                AIMessage(content="Your booking is confirmed."),
            ])}

    monkeypatch.setattr(api, "graph", FakeGraph())
    response = client.post("/api/chat", json={"message": "Book"})
    assert response.status_code == 200
    assert "couldn't confirm the outcome" in response.json()["reply"]
    assert "Your booking is confirmed" not in response.text


def test_memory_is_bounded_expiring_and_keeps_complete_turns():
    memory = ChatMemory(capacity=1)
    with memory.turn("first", time() + 60) as entry:
        for i in range(35):
            entry.turns.append([f"user {i}", f"assistant {i}"])
        assert len(entry.turns) == 30
        assert entry.messages[0] == "user 5"
    with pytest.raises(MemoryFull):
        with memory.turn("second", time() + 60):
            pass
    memory.entries[next(iter(memory.entries))].expires_at = time() - 1
    with memory.turn("second", time() + 60):
        pass
    with pytest.raises(ClosedConversation):
        with memory.turn("expired", time() - 1):
            pass


def test_logout_waits_for_inflight_turn_and_discards_history():
    memory = ChatMemory()
    entered, release = Event(), Event()
    expiry = time() + 60

    def turn():
        with memory.turn("token", expiry) as entry:
            entered.set()
            assert release.wait(timeout=5)
            entry.turns.append(["user", "assistant"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(turn)
        assert entered.wait(timeout=5)
        closing = pool.submit(memory.close, "token", expiry)
        release.set()
        running.result(timeout=5)
        closing.result(timeout=5)
    assert all(entry.closed and not entry.turns for entry in memory.entries.values())
