from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import httpx
import paho.mqtt.client as mqtt

from roadlog import messages
from roadlog.routes import load_routes
from roadlog.settings import SERVICE_PORTS, Broker, service_url, sim_speed

log = logging.getLogger("roadlog.recorder")


class Recorder:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.timeline: list[dict] = []
        self.lock = threading.Lock()

    def capture(self, topic: str, payload: dict) -> None:
        kind = topic.rsplit("/", 1)[-1]
        if topic.startswith("fleet/presence/"):
            kind = "presence"
            payload = {**payload, "hostname": messages.host_of(topic)}
        with self.lock:
            moment = round(time.monotonic() - self.started, 2)
            self.timeline.append({"at": moment, "type": kind, "data": payload})

    def on_message(self, client, userdata, message) -> None:
        try:
            self.capture(message.topic, json.loads(message.payload))
        except json.JSONDecodeError:
            log.warning("skipped a malformed message on %s", message.topic)


def snapshot(http: httpx.Client) -> list[dict]:
    vehicles = http.get(service_url("devices", SERVICE_PORTS["devices"]) + "/vehicles").json()
    latest = http.get(service_url("telemetry", SERVICE_PORTS["telemetry"]) + "/telemetry/latest")
    by_vehicle = {row["vehicle_id"]: row for row in latest.json()}
    for vehicle in vehicles:
        vehicle["telemetry"] = by_vehicle.get(vehicle["vehicle_id"])
    return vehicles


def record(seconds: float, target: Path, http: httpx.Client | None = None) -> dict:
    broker = Broker.from_env("dashboard")
    recorder = Recorder()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="recorder")
    client.username_pw_set(broker.username, broker.password)
    client.on_message = recorder.on_message
    client.on_connect = lambda c, *_: [
        c.subscribe(topic) for topic in (messages.TELEMETRY, messages.EVENTS, messages.PRESENCE)
    ]
    vehicles = snapshot(http or httpx.Client(timeout=5))
    client.connect(broker.host, broker.port, keepalive=15)
    client.loop_start()
    time.sleep(seconds)
    client.loop_stop()
    client.disconnect()
    session = {
        "sim_speed": sim_speed(),
        "seconds": seconds,
        "vehicles": vehicles,
        "routes": [
            {"name": item.name, "points": item.points[::4]} for item in load_routes().values()
        ],
        "timeline": recorder.timeline,
    }
    target.write_text(json.dumps(session, separators=(",", ":")), encoding="utf-8")
    log.info("recorded %d messages to %s", len(recorder.timeline), target)
    return session
