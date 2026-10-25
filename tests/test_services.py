import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from roadlog.services import devices, events, sessions, telemetry
from roadlog.services.db import vehicles


def now():
    return time.time() * 1000


@pytest.fixture
def fleet(engine):
    return TestClient(devices.create_app(engine))


def sample(vehicle_id="TRK-01", age=0.0, speed=80.0):
    return {
        "vehicle_id": vehicle_id,
        "timestamp": now() - age * 1000,
        "latitude": 40.0,
        "longitude": -3.0,
        "heading": 90.0,
        "gnss_speed": speed,
        "odometer_speed": speed,
        "driver_card": "ESD1001",
        "activity": "driving",
        "continuous_driving": 600,
        "daily_driving": 1200,
        "route": "Madrid - Seville",
        "telemetry_interval": 2.0,
    }


def test_the_fleet_is_seeded_once(engine, fleet):
    devices.seed(engine)
    listed = fleet.get("/vehicles").json()
    assert [v["vehicle_id"] for v in listed] == [f"TRK-0{i}" for i in range(1, 9)]
    assert not any(v["online"] for v in listed)


def test_claims_hand_out_vehicles_in_order(fleet):
    first = fleet.post("/vehicles/claim", json={"hostname": "a"}).json()
    second = fleet.post("/vehicles/claim", json={"hostname": "b"}).json()
    again = fleet.post("/vehicles/claim", json={"hostname": "a"}).json()
    assert (first["vehicle_id"], second["vehicle_id"], again["vehicle_id"]) == (
        "TRK-01",
        "TRK-02",
        "TRK-01",
    )
    assert first["online"]


def test_a_full_fleet_refuses_new_tachographs(fleet):
    for index in range(8):
        fleet.post("/vehicles/claim", json={"hostname": f"h{index}"})
    response = fleet.post("/vehicles/claim", json={"hostname": "extra"})
    assert response.status_code == 409


def test_silent_vehicles_can_be_claimed_again(engine, fleet):
    for index in range(8):
        fleet.post("/vehicles/claim", json={"hostname": f"h{index}"})
    with engine.begin() as connection:
        connection.execute(
            update(vehicles).where(vehicles.c.vehicle_id == "TRK-03").values(last_seen=0)
        )
    assert fleet.get("/vehicles/TRK-03").json()["online"] is False
    taken = fleet.post("/vehicles/claim", json={"hostname": "new"}).json()
    assert taken["vehicle_id"] == "TRK-03"


def test_heartbeats_keep_vehicles_online(engine, fleet):
    fleet.post("/vehicles/claim", json={"hostname": "a"})
    with engine.begin() as connection:
        connection.execute(update(vehicles).values(last_seen=0))
    assert fleet.post("/vehicles/heartbeat", json={"vehicle_ids": ["TRK-01", "TRK-02"]}).json() == {
        "seen": 1
    }
    assert fleet.get("/vehicles/TRK-01").json()["online"]


def test_releasing_frees_the_vehicle(fleet):
    fleet.post("/vehicles/claim", json={"hostname": "a"})
    released = fleet.post("/vehicles/release", json={"hostname": "a"}).json()
    assert released["vehicle_id"] == "TRK-01" and not released["online"]
    assert fleet.post("/vehicles/release", json={"hostname": "a"}).status_code == 404


def test_configuration_is_validated(fleet):
    good = fleet.put(
        "/vehicles/TRK-02/config", json={"telemetry_interval": 1, "sampling_interval": 0.5}
    )
    assert good.json()["telemetry_interval"] == 1
    too_fast = fleet.put(
        "/vehicles/TRK-02/config", json={"telemetry_interval": 0.01, "sampling_interval": 1}
    )
    assert too_fast.status_code == 422
    missing = fleet.put(
        "/vehicles/TRK-99/config", json={"telemetry_interval": 1, "sampling_interval": 1}
    )
    assert missing.status_code == 404


def test_sessions_open_and_close(engine):
    client = TestClient(sessions.create_app(engine))
    client.post("/sessions", json={"vehicle_id": "TRK-01", "hostname": "a"})
    client.post("/sessions", json={"vehicle_id": "TRK-01", "hostname": "b"})
    assert len(client.get("/sessions", params={"active": True}).json()) == 1
    history = client.get("/sessions", params={"vehicle_id": "TRK-01"}).json()
    assert {row["end_reason"] for row in history} == {None, "replaced by a new session"}
    assert (
        client.post("/sessions/TRK-01/close", json={"reason": "connection lost"}).status_code == 200
    )
    assert client.get("/sessions", params={"active": True}).json() == []
    assert client.post("/sessions/TRK-01/close", json={}).status_code == 404


def test_telemetry_returns_recent_samples(engine):
    client = TestClient(telemetry.create_app(engine))
    client.post("/telemetry", json=sample(age=120))
    client.post("/telemetry", json=sample(age=30, speed=81))
    client.post("/telemetry", json=sample(age=10, speed=82))
    client.post("/telemetry", json=sample("TRK-02", age=5, speed=60))
    recent = client.get("/telemetry/TRK-01", params={"seconds": 60}).json()
    assert [row["gnss_speed"] for row in recent] == [82, 81]
    latest = client.get("/telemetry/latest").json()
    assert [(row["vehicle_id"], row["gnss_speed"]) for row in latest] == [
        ("TRK-01", 82),
        ("TRK-02", 60),
    ]


def test_telemetry_rejects_impossible_values(engine):
    client = TestClient(telemetry.create_app(engine))
    assert client.post("/telemetry", json=sample() | {"latitude": 95}).status_code == 422
    assert client.post("/telemetry", json=sample() | {"gnss_speed": -1}).status_code == 422


def test_events_filter_by_time_and_vehicle(engine):
    client = TestClient(events.create_app(engine))
    base = {
        "kind": "speeding",
        "severity": "warning",
        "message": "Speeding",
        "latitude": 40.0,
        "longitude": -3.0,
    }
    client.post("/events", json=base | {"vehicle_id": "TRK-01", "timestamp": now() - 600_000})
    client.post("/events", json=base | {"vehicle_id": "TRK-01", "timestamp": now()})
    client.post("/events", json=base | {"vehicle_id": "TRK-02", "timestamp": now()})
    assert len(client.get("/events").json()) == 2
    assert len(client.get("/events", params={"vehicle_id": "TRK-01", "seconds": 3600}).json()) == 2
    bad = base | {"vehicle_id": "TRK-01", "timestamp": now(), "severity": "panic"}
    assert client.post("/events", json=bad).status_code == 422
