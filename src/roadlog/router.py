from __future__ import annotations

import json
import logging
import threading
from contextlib import asynccontextmanager

import httpx
import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from roadlog import messages
from roadlog.messages import Assignment
from roadlog.settings import SERVICE_PORTS, Broker, service_url

HEARTBEAT = 15.0

log = logging.getLogger("roadlog.router")


class Config(BaseModel):
    telemetry_interval: float = Field(ge=messages.MIN_INTERVAL, le=messages.MAX_INTERVAL)
    sampling_interval: float = Field(ge=messages.MIN_INTERVAL, le=messages.MAX_INTERVAL)


class Services:
    def __init__(self, http: httpx.Client | None = None) -> None:
        self.http = http or httpx.Client(timeout=5)
        self.urls = {name: service_url(name, port) for name, port in SERVICE_PORTS.items()}

    def call(self, method: str, service: str, path: str, **kwargs) -> httpx.Response:
        return self.http.request(method, self.urls[service] + path, **kwargs)


class Router:
    def __init__(self, services: Services, publish) -> None:
        self.services = services
        self.publish = publish
        self.seen: set[str] = set()
        self.lock = threading.Lock()

    def handle(self, topic: str, payload: dict) -> None:
        if topic == messages.HELLO:
            self.welcome(payload["hostname"])
        elif topic.startswith("fleet/presence/"):
            if payload.get("status") == "offline":
                self.farewell(messages.host_of(topic), payload.get("reason", "offline"))
        elif topic.endswith("/telemetry"):
            with self.lock:
                self.seen.add(messages.vehicle_of(topic))
            self.services.call("POST", "telemetry", "/telemetry", json=payload)
        elif topic.endswith("/events"):
            self.services.call("POST", "events", "/events", json=payload)

    def welcome(self, hostname: str) -> None:
        response = self.services.call(
            "POST", "devices", "/vehicles/claim", json={"hostname": hostname}
        )
        if response.status_code != 200:
            reason = response.json().get("detail", "access denied")
            self.publish(messages.hello_reply(hostname), {"granted": False, "reason": reason})
            log.warning("refused %s: %s", hostname, reason)
            return
        vehicle = response.json()
        assignment = Assignment.parse(vehicle)
        self.services.call(
            "POST",
            "sessions",
            "/sessions",
            json={"vehicle_id": assignment.vehicle_id, "hostname": hostname},
        )
        self.publish(
            messages.hello_reply(hostname), {"granted": True, "assignment": assignment.to_dict()}
        )
        log.info("%s is now %s", hostname, assignment.vehicle_id)

    def farewell(self, hostname: str, reason: str) -> None:
        response = self.services.call(
            "POST", "devices", "/vehicles/release", json={"hostname": hostname}
        )
        if response.status_code != 200:
            return
        vehicle_id = response.json()["vehicle_id"]
        self.services.call(
            "POST", "sessions", f"/sessions/{vehicle_id}/close", json={"reason": reason}
        )
        log.info("%s went offline: %s", vehicle_id, reason)

    def beat(self) -> None:
        with self.lock:
            seen, self.seen = sorted(self.seen), set()
        if seen:
            self.services.call("POST", "devices", "/vehicles/heartbeat", json={"vehicle_ids": seen})

    def configure(self, vehicle_id: str, config: Config) -> dict:
        response = self.services.call(
            "PUT", "devices", f"/vehicles/{vehicle_id}/config", json=config.model_dump()
        )
        if response.status_code == 404:
            raise HTTPException(404, f"no vehicle {vehicle_id}")
        response.raise_for_status()
        vehicle = response.json()
        if not vehicle["online"]:
            raise HTTPException(
                409, f"{vehicle_id} is offline, the change applies when it connects"
            )
        self.publish(messages.config(vehicle_id), config.model_dump())
        return vehicle


class Bridge:
    def __init__(self, broker: Broker, router_factory) -> None:
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="router", clean_session=False
        )
        self.client.username_pw_set(broker.username, broker.password)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.broker = broker
        self.router = router_factory(self.publish)
        self.stopped = threading.Event()

    def publish(self, topic: str, payload: dict) -> None:
        self.client.publish(topic, json.dumps(payload), qos=1)

    def on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        log.info("connected to the broker (%s)", reason_code)
        for topic in (messages.HELLO, messages.PRESENCE, messages.TELEMETRY, messages.EVENTS):
            client.subscribe(topic, qos=1)

    def on_message(self, client, userdata, message) -> None:
        try:
            self.router.handle(message.topic, json.loads(message.payload))
        except (json.JSONDecodeError, KeyError, ValueError, httpx.HTTPError) as error:
            log.warning("could not handle %s: %s", message.topic, error)

    def heartbeat(self) -> None:
        while not self.stopped.wait(HEARTBEAT):
            try:
                self.router.beat()
            except httpx.HTTPError as error:
                log.warning("heartbeat failed: %s", error)

    def start(self) -> None:
        self.client.connect_async(self.broker.host, self.broker.port, keepalive=15)
        self.client.loop_start()
        threading.Thread(target=self.heartbeat, daemon=True).start()

    def stop(self) -> None:
        self.stopped.set()
        self.client.loop_stop()


def create_app(bridge: Bridge | None = None, connect: bool = True) -> FastAPI:
    bridge = bridge or Bridge(
        Broker.from_env("server"), lambda publish: Router(Services(), publish)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if connect:
            bridge.start()
        yield
        if connect:
            bridge.stop()

    app = FastAPI(title="road-log router", lifespan=lifespan)

    @app.post("/vehicles/{vehicle_id}/config")
    def configure(vehicle_id: str, config: Config) -> dict:
        return bridge.router.configure(vehicle_id, config)

    @app.get("/health")
    def health() -> dict:
        return {"broker": bridge.client.is_connected()}

    return app
