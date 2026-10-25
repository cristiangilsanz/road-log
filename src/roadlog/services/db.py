from __future__ import annotations

import time

from sqlalchemy import (
    Column,
    Engine,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
)
from sqlalchemy.exc import OperationalError

from roadlog.settings import database_url

metadata = MetaData()

vehicles = Table(
    "vehicles",
    metadata,
    Column("vehicle_id", String(20), primary_key=True),
    Column("plate", String(20), nullable=False),
    Column("route", String(60), nullable=False),
    Column("profile", String(30), nullable=False),
    Column("driver_card", String(30), nullable=False),
    Column("driver_name", String(60), nullable=False),
    Column("telemetry_interval", Float, nullable=False),
    Column("sampling_interval", Float, nullable=False),
    Column("hostname", String(80), unique=True),
    Column("last_seen", Float),
)

sessions = Table(
    "sessions",
    metadata,
    Column("session_id", Integer, primary_key=True, autoincrement=True),
    Column("vehicle_id", String(20), nullable=False, index=True),
    Column("hostname", String(80), nullable=False),
    Column("started_at", Float, nullable=False),
    Column("ended_at", Float),
    Column("end_reason", String(60)),
)

telemetry = Table(
    "telemetry",
    metadata,
    Column("telemetry_id", Integer, primary_key=True, autoincrement=True),
    Column("vehicle_id", String(20), nullable=False, index=True),
    Column("timestamp", Float, nullable=False, index=True),
    Column("latitude", Float, nullable=False),
    Column("longitude", Float, nullable=False),
    Column("heading", Float, nullable=False),
    Column("gnss_speed", Float, nullable=False),
    Column("odometer_speed", Float, nullable=False),
    Column("driver_card", String(30)),
    Column("activity", String(20), nullable=False),
    Column("continuous_driving", Integer, nullable=False),
    Column("daily_driving", Integer, nullable=False),
    Column("route", String(60), nullable=False),
)

events = Table(
    "events",
    metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("vehicle_id", String(20), nullable=False, index=True),
    Column("timestamp", Float, nullable=False, index=True),
    Column("kind", String(30), nullable=False),
    Column("severity", String(20), nullable=False),
    Column("message", String(200), nullable=False),
    Column("latitude", Float, nullable=False),
    Column("longitude", Float, nullable=False),
)


def connect(tables: list[Table], url: str | None = None, attempts: int = 30) -> Engine:
    engine = create_engine(url or database_url(), pool_pre_ping=True)
    for attempt in range(attempts):
        try:
            metadata.create_all(engine, tables=tables)
            return engine
        except OperationalError:
            if attempt + 1 == attempts:
                raise
            time.sleep(2)
    return engine


def now_ms() -> float:
    return time.time() * 1000
