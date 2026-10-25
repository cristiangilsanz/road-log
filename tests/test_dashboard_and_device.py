import json

import httpx
import pytest
from fastapi.testclient import TestClient

from roadlog.dashboard.app import Hub, create_app
from roadlog.settings import Broker
from roadlog.twin.device import Device

from conftest import assignment


def fake_services(request: httpx.Request) -> httpx.Response:
    routes = {
        ("GET", "/vehicles"): [
            {"vehicle_id": "TRK-01", "online": True},
            {"vehicle_id": "TRK-02", "online": False},
        ],
        ("GET", "/telemetry/latest"): [{"vehicle_id": "TRK-01", "gnss_speed": 80.0}],
        ("GET", "/events"): [{"vehicle_id": "TRK-01", "kind": "speeding"}],
        ("POST", "/vehicles/TRK-01/config"): {"vehicle_id": "TRK-01"},
    }
    key = (request.method, request.url.path)
    if key == ("POST", "/vehicles/TRK-02/config"):
        return httpx.Response(409, json={"detail": "TRK-02 is offline"})
    return httpx.Response(200, json=routes[key])


@pytest.fixture
def dashboard():
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake_services))
    with TestClient(create_app(http=http, listen=False)) as client:
        yield client


def test_the_fleet_merges_vehicles_and_latest_telemetry(dashboard):
    body = dashboard.get("/api/fleet").json()
    assert body["vehicles"][0]["telemetry"]["gnss_speed"] == 80.0
    assert body["vehicles"][1]["telemetry"] is None
    assert body["sim_speed"] == 60


def test_routes_are_served_for_the_map(dashboard):
    routes = dashboard.get("/api/routes").json()
    assert len(routes) == 8 and len(routes[0]["points"]) > 50


def test_errors_from_services_reach_the_browser(dashboard):
    ok = dashboard.post(
        "/api/vehicles/TRK-01/config", json={"telemetry_interval": 1, "sampling_interval": 1}
    )
    refused = dashboard.post(
        "/api/vehicles/TRK-02/config", json={"telemetry_interval": 1, "sampling_interval": 1}
    )
    assert ok.status_code == 200
    assert refused.status_code == 409 and refused.json()["detail"] == "TRK-02 is offline"


def test_the_page_and_assets_are_served(dashboard):
    assert "road-log" in dashboard.get("/").text
    assert dashboard.get("/static/app.js").status_code == 200


def test_live_messages_reach_websocket_clients(dashboard):
    hub: Hub = dashboard.app.state.hub
    with dashboard.websocket_connect("/ws") as socket:
        while not hub.sockets:
            pass
        hub.push({"type": "telemetry", "data": {"vehicle_id": "TRK-01"}})
        assert socket.receive_json() == {"type": "telemetry", "data": {"vehicle_id": "TRK-01"}}


@pytest.fixture
def device():
    return Device(Broker("localhost", 1883, "device", "secret"), "box-1", speed=60)


class Message:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()


def test_the_device_starts_driving_when_granted(device):
    device.on_message(
        None,
        None,
        Message("fleet/hello/box-1", {"granted": True, "assignment": assignment().to_dict()}),
    )
    assert device.assigned.is_set()
    assert device.tachograph.assignment.vehicle_id == "TRK-99"


def test_the_device_waits_when_refused(device):
    device.on_message(
        None, None, Message("fleet/hello/box-1", {"granted": False, "reason": "full"})
    )
    assert not device.assigned.is_set()


def test_the_device_applies_valid_configuration_only(device):
    device.on_message(
        None,
        None,
        Message("fleet/hello/box-1", {"granted": True, "assignment": assignment().to_dict()}),
    )
    device.on_message(
        None,
        None,
        Message(
            "fleet/vehicles/TRK-99/config", {"telemetry_interval": 5, "sampling_interval": 0.5}
        ),
    )
    assert (device.tachograph.telemetry_interval, device.tachograph.sampling_interval) == (5.0, 0.5)
    device.on_message(
        None,
        None,
        Message("fleet/vehicles/TRK-99/config", {"telemetry_interval": 0, "sampling_interval": 1}),
    )
    device.on_message(None, None, Message("fleet/vehicles/TRK-99/config", b"not json"))
    assert device.tachograph.telemetry_interval == 5.0
