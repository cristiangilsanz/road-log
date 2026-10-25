from __future__ import annotations

import os
from dataclasses import dataclass


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Broker:
    host: str
    port: int
    username: str
    password: str

    @classmethod
    def from_env(cls, role: str) -> Broker:
        return cls(
            host=env("MQTT_HOST", "localhost"),
            port=int(env("MQTT_PORT", "1883")),
            username=env(f"MQTT_{role.upper()}_USER", role),
            password=env(f"MQTT_{role.upper()}_PASSWORD", ""),
        )


def service_url(name: str, port: int) -> str:
    return env(f"{name.upper()}_URL", f"http://localhost:{port}")


SERVICE_PORTS = {"devices": 8001, "sessions": 8002, "telemetry": 8003, "events": 8004}
ROUTER_PORT = 8005
DASHBOARD_PORT = 8080


def database_url() -> str:
    return env("DATABASE_URL", "sqlite:///roadlog.db")


def sim_speed() -> float:
    return float(env("SIM_SPEED", "60"))
