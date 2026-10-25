from __future__ import annotations

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, insert, select

from roadlog.services.db import connect, now_ms, telemetry

MAX_ROWS = 1000


class Sample(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=20)
    timestamp: float
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    heading: float = 0.0
    gnss_speed: float = Field(ge=0)
    odometer_speed: float = Field(ge=0)
    driver_card: str | None = None
    activity: str
    continuous_driving: int = Field(ge=0)
    daily_driving: int = Field(ge=0)
    route: str


def create_app(engine: Engine | None = None) -> FastAPI:
    engine = engine or connect([telemetry])
    app = FastAPI(title="road-log telemetry")

    @app.post("/telemetry", status_code=201)
    def store(sample: Sample) -> dict:
        with engine.begin() as connection:
            connection.execute(insert(telemetry).values(**sample.model_dump()))
        return {"stored": True}

    @app.get("/telemetry/latest")
    def latest() -> list[dict]:
        newest = (
            select(telemetry.c.vehicle_id, func.max(telemetry.c.timestamp).label("timestamp"))
            .group_by(telemetry.c.vehicle_id)
            .subquery()
        )
        query = select(telemetry).join(
            newest,
            (telemetry.c.vehicle_id == newest.c.vehicle_id)
            & (telemetry.c.timestamp == newest.c.timestamp),
        )
        with engine.connect() as connection:
            rows = connection.execute(query).mappings()
            return sorted((dict(row) for row in rows), key=lambda row: row["vehicle_id"])

    @app.get("/telemetry/{vehicle_id}")
    def recent(vehicle_id: str, seconds: float = Query(60, gt=0, le=86400)) -> list[dict]:
        query = (
            select(telemetry)
            .where(
                telemetry.c.vehicle_id == vehicle_id,
                telemetry.c.timestamp >= now_ms() - seconds * 1000,
            )
            .order_by(telemetry.c.timestamp.desc())
            .limit(MAX_ROWS)
        )
        with engine.connect() as connection:
            return [dict(row) for row in connection.execute(query).mappings()]

    return app
