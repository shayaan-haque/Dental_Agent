from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import dental_agent.api as api
from dental_agent.dependencies import get_current_user
from dental_agent.models.database_models import Appointment, AppointmentSlot, Doctor, User
from dental_agent.services.appointments import get_patient_appointments
from dental_agent.services.booking import book_appointment, cancel_appointment, reschedule_appointment


@pytest.fixture
def client(database, monkeypatch):
    api.app.dependency_overrides[get_current_user] = lambda: User(id=1, name="Patient", email="patient@example.com")

    class NoModel:
        def invoke(self, *_args, **_kwargs):
            pytest.fail("Appointments must not call the language model")

    monkeypatch.setattr(api, "graph", NoModel())
    with TestClient(api.app) as client:
        yield client
    api.app.dependency_overrides.clear()


def test_appointments_endpoint_requires_authentication():
    with TestClient(api.app) as client:
        assert client.get("/api/appointments").status_code == 401


def test_empty_bookings_are_empty_not_placeholder_data(client):
    for view in ("upcoming", "previous", "cancelled", "rescheduled", "all"):
        response = client.get("/api/appointments", params={"view": view})
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["has_more"] is False
        assert response.headers["cache-control"] == "no-store"


def test_endpoint_filters_are_validated(client):
    for params in ({"view": "invalid"}, {"limit": 0}, {"limit": 101}, {"offset": -1}):
        assert client.get("/api/appointments", params=params).status_code == 422


def test_identity_is_not_taken_from_query_string(client):
    book_appointment(2, 1)
    own = book_appointment(1, 2)["appointment"]
    response = client.get("/api/appointments?view=all&patient_id=2")
    assert [item["appointment_id"] for item in response.json()["items"]] == [own["appointment_id"]]
    assert response.json()["items"][0]["starts_at"].endswith("+05:30")


def test_previous_includes_past_booked_and_completed_but_not_cancelled(client, database):
    factory, _ = database
    old = book_appointment(1, 1)["appointment"]["appointment_id"]
    cancelled = book_appointment(1, 2)["appointment"]["appointment_id"]
    cancel_appointment(1, cancelled)
    with factory.begin() as session:
        slot = session.get(AppointmentSlot, 1)
        slot.start_time = datetime.now(timezone.utc) - timedelta(hours=2)
        slot.end_time = slot.start_time + timedelta(minutes=30)
        completed = Appointment(patient_id=1, slot_id=3, status="completed")
        session.add(completed)
        session.flush()
        completed_id = completed.id
        session.get(Doctor, 1).is_active = False
        slot.is_enabled = False
    previous = client.get("/api/appointments?view=previous").json()["items"]
    assert {item["appointment_id"] for item in previous} == {old, completed_id}
    assert {item["status"] for item in previous} == {"booked", "completed"}
    cancelled_items = client.get("/api/appointments?view=cancelled").json()["items"]
    assert [item["appointment_id"] for item in cancelled_items] == [cancelled]
    assert client.get("/api/appointments?view=upcoming").json()["items"] == []


def test_ongoing_booked_visit_remains_upcoming(client, database):
    factory, _ = database
    book_appointment(1, 1)
    with factory.begin() as session:
        slot = session.get(AppointmentSlot, 1)
        slot.start_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        slot.end_time = slot.start_time + timedelta(minutes=30)
    assert len(client.get("/api/appointments?view=upcoming").json()["items"]) == 1
    assert client.get("/api/appointments?view=previous").json()["items"] == []


def test_bookings_are_ordered_and_paginated(client):
    book_appointment(1, 1)
    book_appointment(1, 2)
    first = client.get("/api/appointments?view=upcoming&limit=1").json()
    second = client.get("/api/appointments?view=upcoming&limit=1&offset=1").json()
    assert [item["slot_id"] for item in first["items"]] == [1]
    assert first["has_more"] is True
    assert [item["slot_id"] for item in second["items"]] == [2]
    assert second["has_more"] is False
    assert [item["slot_id"] for item in client.get("/api/appointments?view=all").json()["items"]] == [2, 1]


def test_rescheduled_history_and_replacement_have_separate_views(client):
    old_id = book_appointment(1, 1)["appointment"]["appointment_id"]
    new_id = reschedule_appointment(1, old_id, 2)["appointment"]["appointment_id"]
    history = client.get("/api/appointments?view=rescheduled").json()["items"]
    upcoming = client.get("/api/appointments?view=upcoming").json()["items"]
    assert [(item["appointment_id"], item["status"]) for item in history] == [(old_id, "rescheduled")]
    assert [(item["appointment_id"], item["status"]) for item in upcoming] == [(new_id, "booked")]
    assert client.get("/api/appointments?view=cancelled").json()["items"] == []


def test_read_failure_is_not_reported_as_an_empty_history(client, monkeypatch):
    def fail(*_args, **_kwargs):
        raise OperationalError("private SQL", {}, Exception("password"))

    monkeypatch.setattr(api, "get_patient_appointments", fail)
    response = client.get("/api/appointments")
    assert response.status_code == 503
    assert "private" not in response.text and "password" not in response.text


@pytest.mark.parametrize("kwargs", [{"view": "bad"}, {"limit": True}, {"offset": -1}])
def test_service_validates_filters(database, kwargs):
    with pytest.raises(ValueError):
        get_patient_appointments(1, **kwargs)
