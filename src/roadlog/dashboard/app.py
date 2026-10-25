from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from importlib.resources import files

import httpx
import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from roadlog import messages
from roadlog.routes import load_routes
from roadlog.settings import ROUTER_PORT, SERVICE_PORTS, Broker, env, service_url, sim_speed

STATIC = files("roadlog") / "dashboard" / "static"

log = logging.getLogger("roadlog.dashboard")


class Config(BaseModel):
    telemetry_interval: float
    sampling_interval: float


class Hub:
    def __init__(self) -> None:
        self.sockets: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def join(self, socket: WebSocket) -> None:
        await socket.accept()
        self.sockets.add(socket)

    def leave(self, socket: WebSocket) -> None:
        self.sockets.discard(socket)

    async def broadcast(self, message: dict) -> None:
        for socket in list(self.sockets):
            try:
                await socket.send_json(message)
            except (RuntimeError, WebSocketDisconnect):
                self.leave(socket)

    def push(self, message: dict) -> None:
        if self.loop and self.sockets:
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)


class Listener:
    def __init__(self, broker: Broker, hub: Hub) -> None:
        self.hub = hub
        self.broker = broker
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dashboard")
        self.client.username_pw_set(broker.username, broker.password)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        for topic in (messages.TELEMETRY, messages.EVENTS, messages.PRESENCE):
            client.subscribe(topic, qos=0)

    def on_message(self, client, userdata, message) -> None:
        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError:
            return
        kind = message.topic.rsplit("/", 1)[-1]
        if message.topic.startswith("fleet/presence/"):
            kind = "presence"
            payload["hostname"] = messages.host_of(message.topic)
        self.hub.push({"type": kind, "data": payload})

    def start(self) -> None:
        self.client.connect_async(self.broker.host, self.broker.port, keepalive=15)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()


def create_app(http: httpx.AsyncClient | None = None, listen: bool = True) -> FastAPI:
    hub = Hub()
    listener = Listener(Broker.from_env("dashboard"), hub)
    urls = {name: service_url(name, port) for name, port in SERVICE_PORTS.items()}
    urls["router"] = env("ROUTER_URL", f"http://localhost:{ROUTER_PORT}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub.loop = asyncio.get_running_loop()
        app.state.http = http or httpx.AsyncClient(timeout=5)
        if listen:
            listener.start()
        yield
        if listen:
            listener.stop()
        await app.state.http.aclose()

    app = FastAPI(title="road-log dashboard", lifespan=lifespan)
    app.state.hub = hub

    async def call(method: str, service: str, path: str, **kwargs):
        try:
            response = await app.state.http.request(method, urls[service] + path, **kwargs)
        except httpx.HTTPError as error:
            raise HTTPException(503, f"{service} service unavailable: {error}") from error
        if response.status_code >= 400:
            detail = response.json().get("detail", response.text)
            raise HTTPException(response.status_code, detail)
        return response.json()

    @app.get("/api/fleet")
    async def fleet() -> dict:
        vehicles = await call("GET", "devices", "/vehicles")
        latest = {
            row["vehicle_id"]: row for row in await call("GET", "telemetry", "/telemetry/latest")
        }
        for vehicle in vehicles:
            vehicle["telemetry"] = latest.get(vehicle["vehicle_id"])
        return {"vehicles": vehicles, "sim_speed": sim_speed()}

    @app.get("/api/routes")
    def routes() -> list[dict]:
        return [{"name": item.name, "points": item.points[::4]} for item in load_routes().values()]

    @app.get("/api/vehicles/{vehicle_id}/telemetry")
    async def telemetry(vehicle_id: str, seconds: float = 60) -> list[dict]:
        return await call(
            "GET", "telemetry", f"/telemetry/{vehicle_id}", params={"seconds": seconds}
        )

    @app.get("/api/events")
    async def events(seconds: float = 300, vehicle_id: str | None = None) -> list[dict]:
        params = {"seconds": seconds} | ({"vehicle_id": vehicle_id} if vehicle_id else {})
        return await call("GET", "events", "/events", params=params)

    @app.post("/api/vehicles/{vehicle_id}/config")
    async def configure(vehicle_id: str, config: Config) -> dict:
        return await call(
            "POST", "router", f"/vehicles/{vehicle_id}/config", json=config.model_dump()
        )

    @app.websocket("/ws")
    async def live(socket: WebSocket) -> None:
        await hub.join(socket)
        try:
            while True:
                await socket.receive_text()
        except WebSocketDisconnect:
            hub.leave(socket)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(STATIC / "index.html"))

    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    return app
