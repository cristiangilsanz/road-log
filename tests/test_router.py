import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from roadlog import messages
from roadlog.router import Config, Router, Services, create_app
from roadlog.services import devices, events, sessions, telemetry


class Wired:
    def __init__(self, engine):
        self.apps = {
            "devices": devices.create_app(engine),
            "sessions": sessions.create_app(engine),
            "telemetry": telemetry.create_app(engine),
            "events": events.create_app(engine),
        }
        self.clients = {name: TestClient(app) for name, app in self.apps.items()}
        self.published = []
        transport = httpx.MockTransport(self.forward)
        services = Services(httpx.Client(transport=transport))
        services.urls = {name: f"http://{name}" for name in self.apps}
        self.router = Router(
            services, lambda topic, payload: self.published.append((topic, payload))
        )

    def forward(self, request: httpx.Request) -> httpx.Response:
        client = self.clients[request.url.host]
        response = client.request(
            request.method,
            request.url.path,
            params=request.url.params,
            content=request.content,
            headers={"content-type": "application/json"},
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=response.headers
        )


@pytest.fixture
def wired(engine):
    return Wired(engine)


def telemetry_payload(vehicle_id="TRK-01"):
    return {
        "vehicle_id": vehicle_id,
        "timestamp": 1.0e12,
        "latitude": 40.0,
        "longitude": -3.0,
        "heading": 0.0,
        "gnss_speed": 70.0,
        "odometer_speed": 70.0,
        "driver_card": None,
        "activity": "driving",
        "continuous_driving": 0,
        "daily_driving": 0,
        "route": "Madrid - Seville",
    }


def test_hello_grants_a_vehicle_and_opens_a_session(wired):
    wired.router.handle(messages.HELLO, {"hostname": "box-1"})
    topic, reply = wired.published[-1]
    assert topic == "fleet/hello/box-1"
    assert reply["granted"] and reply["assignment"]["vehicle_id"] == "TRK-01"
    assert reply["assignment"]["route"] == "Madrid - Seville"
    active = wired.clients["sessions"].get("/sessions", params={"active": True}).json()
    assert [(s["vehicle_id"], s["hostname"]) for s in active] == [("TRK-01", "box-1")]


def test_a_full_fleet_gets_a_refusal(wired):
    for index in range(8):
        wired.router.handle(messages.HELLO, {"hostname": f"box-{index}"})
    wired.router.handle(messages.HELLO, {"hostname": "box-extra"})
    topic, reply = wired.published[-1]
    assert topic == "fleet/hello/box-extra" and reply["granted"] is False


def test_going_offline_closes_the_session(wired):
    wired.router.handle(messages.HELLO, {"hostname": "box-1"})
    wired.router.handle("fleet/presence/box-1", {"status": "offline", "reason": "connection lost"})
    history = wired.clients["sessions"].get("/sessions").json()
    assert history[0]["end_reason"] == "connection lost"
    assert not wired.clients["devices"].get("/vehicles/TRK-01").json()["online"]


def test_telemetry_and_events_are_stored(wired):
    wired.router.handle(messages.telemetry("TRK-01"), telemetry_payload())
    event = {
        "vehicle_id": "TRK-01",
        "timestamp": 1.0e12,
        "kind": "speeding",
        "severity": "warning",
        "message": "fast",
        "latitude": 40.0,
        "longitude": -3.0,
    }
    wired.router.handle(messages.events("TRK-01"), event)
    assert wired.clients["telemetry"].get("/telemetry/latest").json()[0]["gnss_speed"] == 70.0
    assert (
        wired.clients["events"].get("/events", params={"seconds": 7 * 86400 - 1}).status_code == 200
    )


def test_heartbeats_report_vehicles_that_spoke(wired):
    wired.router.handle(messages.HELLO, {"hostname": "box-1"})
    wired.router.handle(messages.telemetry("TRK-01"), telemetry_payload())
    assert wired.router.seen == {"TRK-01"}
    wired.router.beat()
    assert wired.router.seen == set()


def test_configuration_reaches_online_vehicles(wired):
    wired.router.handle(messages.HELLO, {"hostname": "box-1"})
    wired.router.configure("TRK-01", Config(telemetry_interval=1, sampling_interval=0.5))
    assert wired.published[-1] == (
        "fleet/vehicles/TRK-01/config",
        {"telemetry_interval": 1.0, "sampling_interval": 0.5},
    )


def test_configuration_of_offline_or_unknown_vehicles_fails(wired):
    with pytest.raises(HTTPException) as offline:
        wired.router.configure("TRK-02", Config(telemetry_interval=1, sampling_interval=1))
    assert offline.value.status_code == 409
    with pytest.raises(HTTPException) as unknown:
        wired.router.configure("TRK-42", Config(telemetry_interval=1, sampling_interval=1))
    assert unknown.value.status_code == 404


def test_the_http_api_validates_configuration(wired):
    class Bridge:
        router = wired.router

    client = TestClient(create_app(Bridge(), connect=False))
    response = client.post(
        "/vehicles/TRK-01/config", json={"telemetry_interval": 100, "sampling_interval": 1}
    )
    assert response.status_code == 422
