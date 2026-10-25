from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Engine, insert, or_, select, update

from roadlog.messages import MAX_INTERVAL, MIN_INTERVAL
from roadlog.services.db import connect, now_ms, vehicles

FLEET = [
    ("TRK-01", "4821 KLM", "Madrid - Seville", "careful", "ESD1001", "Lucía Romero"),
    ("TRK-02", "7310 HBX", "Madrid - Valencia", "speeder", "ESD1002", "Javier Ortega"),
    ("TRK-03", "2954 JTR", "Bilbao - Madrid", "tired", "ESD1003", "Marta Ibáñez"),
    ("TRK-04", "6643 LDN", "Madrid - Zaragoza", "faulty-odometer", "ESD1004", "Andrés Molina"),
    ("TRK-05", "1187 MKC", "Valencia - Barcelona", "forgetful", "ESD1005", "Elena Castro"),
    ("TRK-06", "5079 GRP", "Barcelona - Zaragoza", "careful", "ESD1006", "Pablo Navarro"),
    ("TRK-07", "3362 KVS", "Madrid - Salamanca", "speeder", "ESD1007", "Sara Delgado"),
    ("TRK-08", "9405 JNF", "Seville - Malaga", "tired", "ESD1008", "Diego Herrera"),
]
TELEMETRY_INTERVAL = 2.0
SAMPLING_INTERVAL = 1.0
STALE_AFTER = 90_000


class Claim(BaseModel):
    hostname: str = Field(min_length=1, max_length=80)


class Heartbeat(BaseModel):
    vehicle_ids: list[str]


class Config(BaseModel):
    telemetry_interval: float = Field(ge=MIN_INTERVAL, le=MAX_INTERVAL)
    sampling_interval: float = Field(ge=MIN_INTERVAL, le=MAX_INTERVAL)


def seed(engine: Engine) -> None:
    with engine.begin() as connection:
        if connection.execute(select(vehicles.c.vehicle_id).limit(1)).first():
            return
        connection.execute(
            insert(vehicles),
            [
                {
                    "vehicle_id": vehicle_id,
                    "plate": plate,
                    "route": route,
                    "profile": profile,
                    "driver_card": card,
                    "driver_name": driver,
                    "telemetry_interval": TELEMETRY_INTERVAL,
                    "sampling_interval": SAMPLING_INTERVAL,
                }
                for vehicle_id, plate, route, profile, card, driver in FLEET
            ],
        )


def present(row) -> dict:
    vehicle = dict(row)
    fresh = vehicle["last_seen"] is not None and vehicle["last_seen"] > now_ms() - STALE_AFTER
    vehicle["online"] = vehicle["hostname"] is not None and fresh
    return vehicle


def create_app(engine: Engine | None = None) -> FastAPI:
    engine = engine or connect([vehicles])
    seed(engine)
    app = FastAPI(title="road-log devices")

    def one(connection, *conditions):
        query = select(vehicles).where(*conditions).order_by(vehicles.c.vehicle_id)
        row = connection.execute(query).mappings().first()
        return present(row) if row else None

    def claimable():
        return or_(vehicles.c.hostname.is_(None), vehicles.c.last_seen < now_ms() - STALE_AFTER)

    @app.get("/vehicles")
    def list_vehicles() -> list[dict]:
        with engine.connect() as connection:
            rows = connection.execute(select(vehicles).order_by(vehicles.c.vehicle_id))
            return [present(row) for row in rows.mappings()]

    @app.get("/vehicles/{vehicle_id}")
    def get_vehicle(vehicle_id: str) -> dict:
        with engine.connect() as connection:
            vehicle = one(connection, vehicles.c.vehicle_id == vehicle_id)
        if not vehicle:
            raise HTTPException(404, f"no vehicle {vehicle_id}")
        return vehicle

    @app.post("/vehicles/claim")
    def claim(request: Claim) -> dict:
        with engine.begin() as connection:
            vehicle = one(connection, vehicles.c.hostname == request.hostname)
            if not vehicle:
                vehicle = one(connection, claimable())
            if not vehicle:
                raise HTTPException(409, "every vehicle already has a tachograph")
            taken = connection.execute(
                update(vehicles)
                .where(
                    vehicles.c.vehicle_id == vehicle["vehicle_id"],
                    or_(vehicles.c.hostname == request.hostname, claimable()),
                )
                .values(hostname=request.hostname, last_seen=now_ms())
            )
            if not taken.rowcount:
                raise HTTPException(409, "the vehicle was claimed by another tachograph")
            return one(connection, vehicles.c.vehicle_id == vehicle["vehicle_id"])

    @app.post("/vehicles/release")
    def release(request: Claim) -> dict:
        with engine.begin() as connection:
            vehicle = one(connection, vehicles.c.hostname == request.hostname)
            if not vehicle:
                raise HTTPException(404, f"no vehicle is linked to {request.hostname}")
            connection.execute(
                update(vehicles)
                .where(vehicles.c.vehicle_id == vehicle["vehicle_id"])
                .values(hostname=None)
            )
            return {**vehicle, "hostname": None, "online": False}

    @app.post("/vehicles/heartbeat")
    def heartbeat(request: Heartbeat) -> dict:
        with engine.begin() as connection:
            seen = connection.execute(
                update(vehicles)
                .where(
                    vehicles.c.vehicle_id.in_(request.vehicle_ids), vehicles.c.hostname.isnot(None)
                )
                .values(last_seen=now_ms())
            )
        return {"seen": seen.rowcount}

    @app.put("/vehicles/{vehicle_id}/config")
    def configure(vehicle_id: str, config: Config) -> dict:
        with engine.begin() as connection:
            changed = connection.execute(
                update(vehicles)
                .where(vehicles.c.vehicle_id == vehicle_id)
                .values(**config.model_dump())
            )
            if not changed.rowcount:
                raise HTTPException(404, f"no vehicle {vehicle_id}")
            return one(connection, vehicles.c.vehicle_id == vehicle_id)

    return app
