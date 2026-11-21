"""Real PostgreSQL races, independent of the optional MCP proof of concept.

Set TEST_DATABASE_URL to an isolated test database with btree_gist enabled.
The API test uses real JWT authentication, graph tools, transactions, and reply
formatting; only the external LLM is scripted, so no AI quota is consumed.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event, local
from time import monotonic, sleep
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import event, func, select, text

import dental_agent.api as api
import dental_agent.dependencies as dependencies
import dental_agent.workflows.appointment_graph as workflow
from dental_agent.models.database_models import Appointment, AppointmentSlot
from dental_agent.security import create_access_token
from dental_agent.services.booking import AppointmentError, book_appointment
from dental_agent.services.chat_memory import ChatMemory


def add_race_slots(factory, start, count):
    slot_ids = list(range(1000, 1000 + count))
    with factory.begin() as session:
        for index, slot_id in enumerate(slot_ids):
            when = start + timedelta(days=10, hours=index)
            session.add(AppointmentSlot(id=slot_id, doctor_id=1, start_time=when,
                                        end_time=when + timedelta(minutes=30), is_enabled=True))
    return slot_ids


def test_fifty_races_between_two_users_have_exactly_one_winner_each(postgres_database):
    factory, start = postgres_database
    slot_ids = add_race_slots(factory, start, 50)
    winners = Counter()

    with ThreadPoolExecutor(max_workers=2) as pool:
        for slot_id in slot_ids:
            barrier = Barrier(2)

            def attempt(patient_id):
                barrier.wait(timeout=10)
                try:
                    return patient_id, book_appointment(patient_id, slot_id)["code"]
                except AppointmentError as error:
                    return patient_id, error.code

            outcomes = dict(pool.map(attempt, [1, 2]))
            assert sorted(outcomes.values()) == ["booked", "slot_taken"], outcomes
            winner = next(patient_id for patient_id, code in outcomes.items() if code == "booked")
            winners[winner] += 1
            with factory() as session:
                rows = session.scalars(select(Appointment).where(Appointment.slot_id == slot_id)).all()
                assert len(rows) == 1
                assert rows[0].patient_id == winner and rows[0].status == "booked"

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Appointment)) == 50
    print(f"\nService races: 50 slots, 100 attempts, 50 bookings, 50 slot_taken rejections; wins by user: {dict(winners)}")


def test_second_user_really_waits_for_first_users_uncommitted_slot_lock(postgres_database):
    factory, _ = postgres_database
    winner_flushed, loser_submitted, release_winner = Event(), Event(), Event()
    worker = local()
    blocked_pid = []
    engine = factory.kw["bind"]

    def hold_first_commit(session):
        if getattr(worker, "patient_id", None) == 1:
            # INSERT has been flushed but not committed; the slot lock is held.
            assert session.scalar(select(Appointment.patient_id).where(Appointment.slot_id == 1)) == 1
            winner_flushed.set()
            assert release_winner.wait(timeout=15)

    def observe_contender(connection, _cursor, statement, _parameters, _context, _many):
        if (getattr(worker, "patient_id", None) == 2
                and "appointment_slots" in statement and "FOR UPDATE" in statement):
            blocked_pid.append(connection.scalar(text("SELECT pg_backend_pid()")))
            loser_submitted.set()

    def attempt(patient_id):
        worker.patient_id = patient_id
        try:
            return book_appointment(patient_id, 1)["code"]
        except AppointmentError as error:
            return error.code

    event.listen(factory.class_, "before_commit", hold_first_commit)
    event.listen(engine, "before_cursor_execute", observe_contender)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            winner = pool.submit(attempt, 1)
            try:
                assert winner_flushed.wait(timeout=10)
                loser = pool.submit(attempt, 2)
                assert loser_submitted.wait(timeout=10)
                # Verify actual PostgreSQL lock contention, not merely overlapping
                # Python requests. AUTOCOMMIT avoids cached statistics snapshots.
                with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                    deadline = monotonic() + 5
                    while monotonic() < deadline:
                        wait_type = connection.scalar(text(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                        ), {"pid": blocked_pid[0]})
                        if wait_type == "Lock":
                            break
                        sleep(0.01)
                    else:
                        raise AssertionError("The second user's transaction was not observed waiting for a PostgreSQL lock")
                assert not loser.done()
            finally:
                release_winner.set()
            assert winner.result(timeout=10) == "booked"
            assert loser.result(timeout=10) == "slot_taken"
    finally:
        event.remove(factory.class_, "before_commit", hold_first_commit)
        event.remove(engine, "before_cursor_execute", observe_contender)

    with factory() as session:
        rows = session.scalars(select(Appointment).where(Appointment.slot_id == 1)).all()
        assert len(rows) == 1 and rows[0].patient_id == 1
    print("\nForced lock race: user 1 held an uncommitted booking; PostgreSQL blocked user 2; after commit user 2 received slot_taken.")


def test_ten_authenticated_chat_booking_races_show_only_one_confirmation(postgres_database, monkeypatch):
    factory, start = postgres_database
    slot_ids = add_race_slots(factory, start, 10)
    barriers = {slot_id: Barrier(2) for slot_id in slot_ids}
    monkeypatch.setattr(dependencies, "SessionLocal", factory)
    monkeypatch.setattr(api, "chat_memory", ChatMemory())
    assert dependencies.get_current_user not in api.app.dependency_overrides

    class ScriptedBookingModel:
        def invoke(self, messages):
            if isinstance(messages[-1], ToolMessage):
                # Deliberately wrong for the losing request: the real response
                # formatter must replace it with the backend's failure message.
                return AIMessage(content="Your appointment was successfully booked.")
            request = next(message for message in reversed(messages) if isinstance(message, HumanMessage))
            slot_id = int(request.content.rsplit(" ", 1)[1])
            barriers[slot_id].wait(timeout=10)
            return AIMessage(content="", tool_calls=[{
                "name": "book_appointment", "args": {"slot_id": slot_id}, "id": uuid4().hex,
            }])

    monkeypatch.setattr(workflow, "model_with_tools", ScriptedBookingModel())

    def attempt(patient_id, slot_id):
        # Distinct clients/cookies; actual JWT validation and user DB lookups.
        with TestClient(api.app) as client:
            client.cookies.set("access_token", create_access_token(patient_id))
            response = client.post("/api/chat", json={"message": f"Book test slot {slot_id}"})
            saved = client.get("/api/appointments?view=upcoming&limit=100")
            assert response.status_code == 200 and saved.status_code == 200
            owns_slot = any(item["slot_id"] == slot_id for item in saved.json()["items"])
            return patient_id, response.json()["reply"], owns_slot

    sample = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        for slot_id in slot_ids:
            futures = [pool.submit(attempt, patient_id, slot_id) for patient_id in (1, 2)]
            outcomes = [future.result(timeout=20) for future in futures]
            confirmed = [item for item in outcomes if "Booking confirmed:" in item[1]]
            rejected = [item for item in outcomes if "That slot was just booked." in item[1]]
            assert len(confirmed) == len(rejected) == 1, outcomes
            assert confirmed[0][2] is True and rejected[0][2] is False
            assert "successfully booked" not in rejected[0][1]
            with factory() as session:
                rows = session.scalars(select(Appointment).where(Appointment.slot_id == slot_id)).all()
                assert len(rows) == 1 and rows[0].patient_id == confirmed[0][0]
            sample = outcomes

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Appointment)) == 10
    print("\nAuthenticated API races: 10 slots, 20 chat requests, 10 confirmations, 10 rejections; no double bookings or false success messages.")
    for patient_id, reply, owns_slot in sample:
        print(f"  Example user {patient_id}: owns_slot={owns_slot}; {reply}")
