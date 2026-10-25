from __future__ import annotations

from dataclasses import asdict, dataclass

HELLO = "fleet/hello"
PRESENCE = "fleet/presence/+"
TELEMETRY = "fleet/vehicles/+/telemetry"
EVENTS = "fleet/vehicles/+/events"

MIN_INTERVAL = 0.2
MAX_INTERVAL = 60.0


def hello_reply(hostname: str) -> str:
    return f"fleet/hello/{hostname}"


def presence(hostname: str) -> str:
    return f"fleet/presence/{hostname}"


def telemetry(vehicle_id: str) -> str:
    return f"fleet/vehicles/{vehicle_id}/telemetry"


def events(vehicle_id: str) -> str:
    return f"fleet/vehicles/{vehicle_id}/events"


def config(vehicle_id: str) -> str:
    return f"fleet/vehicles/{vehicle_id}/config"


def vehicle_of(topic: str) -> str:
    return topic.split("/")[2]


def host_of(topic: str) -> str:
    return topic.split("/")[2]


def valid_interval(value) -> float:
    number = float(value)
    if not MIN_INTERVAL <= number <= MAX_INTERVAL:
        raise ValueError(f"intervals must be between {MIN_INTERVAL} and {MAX_INTERVAL} seconds")
    return number


@dataclass(frozen=True)
class Assignment:
    vehicle_id: str
    plate: str
    route: str
    profile: str
    driver_card: str
    driver_name: str
    telemetry_interval: float
    sampling_interval: float

    @classmethod
    def parse(cls, payload: dict) -> Assignment:
        fields = {name: payload[name] for name in cls.__dataclass_fields__}
        fields["telemetry_interval"] = valid_interval(fields["telemetry_interval"])
        fields["sampling_interval"] = valid_interval(fields["sampling_interval"])
        return cls(**fields)

    def to_dict(self) -> dict:
        return asdict(self)
