from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Engine, insert, select, update

from roadlog.services.db import connect, now_ms, sessions


class Opening(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=20)
    hostname: str = Field(min_length=1, max_length=80)


class Closing(BaseModel):
    reason: str = Field(default="switched off", max_length=60)


def create_app(engine: Engine | None = None) -> FastAPI:
    engine = engine or connect([sessions])
    app = FastAPI(title="road-log sessions")
    is_open = sessions.c.ended_at.is_(None)

    def close_open(connection, vehicle_id: str, reason: str) -> int:
        return connection.execute(
            update(sessions)
            .where(sessions.c.vehicle_id == vehicle_id, is_open)
            .values(ended_at=now_ms(), end_reason=reason)
        ).rowcount

    @app.post("/sessions", status_code=201)
    def open_session(request: Opening) -> dict:
        with engine.begin() as connection:
            close_open(connection, request.vehicle_id, "replaced by a new session")
            started = now_ms()
            result = connection.execute(
                insert(sessions).values(
                    vehicle_id=request.vehicle_id, hostname=request.hostname, started_at=started
                )
            )
        return {
            "session_id": result.inserted_primary_key[0],
            "vehicle_id": request.vehicle_id,
            "hostname": request.hostname,
            "started_at": started,
        }

    @app.post("/sessions/{vehicle_id}/close")
    def close_session(vehicle_id: str, request: Closing) -> dict:
        with engine.begin() as connection:
            if not close_open(connection, vehicle_id, request.reason):
                raise HTTPException(404, f"{vehicle_id} has no open session")
        return {"vehicle_id": vehicle_id, "closed": True, "reason": request.reason}

    @app.get("/sessions")
    def list_sessions(active: bool = False, vehicle_id: str | None = None) -> list[dict]:
        query = select(sessions).order_by(sessions.c.started_at.desc()).limit(200)
        if active:
            query = query.where(is_open)
        if vehicle_id:
            query = query.where(sessions.c.vehicle_id == vehicle_id)
        with engine.connect() as connection:
            return [dict(row) for row in connection.execute(query).mappings()]

    return app
