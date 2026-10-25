import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from roadlog.messages import Assignment
from roadlog.services.db import metadata


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    metadata.create_all(engine)
    return engine


def assignment(profile="careful", route="Madrid - Valencia", vehicle_id="TRK-99"):
    return Assignment(
        vehicle_id=vehicle_id,
        plate="0000 AAA",
        route=route,
        profile=profile,
        driver_card="ESD0001",
        driver_name="Test Driver",
        telemetry_interval=2.0,
        sampling_interval=1.0,
    )
