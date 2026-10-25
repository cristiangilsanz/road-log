from __future__ import annotations

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
from sqlalchemy import Engine, insert, select

from roadlog.services.db import connect, events, now_ms

MAX_ROWS = 500


class Event(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=20)
    timestamp: float
    kind: str = Field(min_length=1, max_length=30)
    severity: str = Field(pattern="^(info|warning|infringement)$")
    message: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


def create_app(engine: Engine | None = None) -> FastAPI:
    engine = engine or connect([events])
    app = FastAPI(title="road-log events")

    @app.post("/events", status_code=201)
    def store(event: Event) -> dict:
        with engine.begin() as connection:
            connection.execute(insert(events).values(**event.model_dump()))
        return {"stored": True}

    @app.get("/events")
    def recent(
        seconds: float = Query(300, gt=0, le=7 * 86400), vehicle_id: str | None = None
    ) -> list[dict]:
        query = (
            select(events)
            .where(events.c.timestamp >= now_ms() - seconds * 1000)
            .order_by(events.c.timestamp.desc())
            .limit(MAX_ROWS)
        )
        if vehicle_id:
            query = query.where(events.c.vehicle_id == vehicle_id)
        with engine.connect() as connection:
            return [dict(row) for row in connection.execute(query).mappings()]

    return app
