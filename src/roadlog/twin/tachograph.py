from __future__ import annotations

import random

from roadlog.messages import Assignment
from roadlog.routes import route
from roadlog.rules import HOUR
from roadlog.twin.control_unit import ControlUnit, Event, Reading
from roadlog.twin.vehicle import Vehicle, profile


class Tachograph:
    def __init__(self, assignment: Assignment, seed: int | str | None = None) -> None:
        self.assignment = assignment
        rng = random.Random(assignment.vehicle_id if seed is None else seed)
        chosen = route(assignment.route)
        self.vehicle = Vehicle(
            route=chosen,
            profile=profile(assignment.profile),
            cards=(assignment.driver_card, f"{assignment.driver_card}B"),
            rng=rng,
            distance=chosen.length * rng.uniform(0.05, 0.85),
        )
        self.vehicle.clock.continuous = rng.uniform(0, 4 * HOUR)
        self.vehicle.clock.daily = self.vehicle.clock.continuous + rng.uniform(0, 3 * HOUR)
        self.control_unit = ControlUnit()
        self.telemetry_interval = assignment.telemetry_interval
        self.sampling_interval = assignment.sampling_interval
        self.reading = self.read()

    def read(self) -> Reading:
        location = self.vehicle.location
        return Reading(
            latitude=location.latitude,
            longitude=location.longitude,
            heading=location.heading,
            gnss_speed=self.vehicle.gnss_speed(),
            odometer_speed=self.vehicle.odometer_speed(),
            card=self.vehicle.card if self.vehicle.card_inserted else None,
            activity=self.vehicle.activity.value,
        )

    def tick(self, simulated_seconds: float) -> list[Event]:
        self.vehicle.step(simulated_seconds)
        self.reading = self.read()
        return self.control_unit.inspect(self.reading, self.vehicle.clock)

    def configure(self, telemetry_interval: float, sampling_interval: float) -> None:
        self.telemetry_interval = telemetry_interval
        self.sampling_interval = sampling_interval

    def telemetry(self, timestamp: float) -> dict:
        reading = self.reading
        return {
            "vehicle_id": self.assignment.vehicle_id,
            "timestamp": timestamp,
            "latitude": round(reading.latitude, 6),
            "longitude": round(reading.longitude, 6),
            "heading": round(reading.heading, 1),
            "gnss_speed": round(reading.gnss_speed, 1),
            "odometer_speed": round(reading.odometer_speed, 1),
            "driver_card": reading.card,
            "activity": reading.activity,
            "continuous_driving": round(self.vehicle.clock.continuous),
            "daily_driving": round(self.vehicle.clock.daily),
            "route": self.vehicle.route.name,
            "telemetry_interval": self.telemetry_interval,
            "sampling_interval": self.sampling_interval,
        }

    def event(self, event: Event, timestamp: float) -> dict:
        return {
            "vehicle_id": self.assignment.vehicle_id,
            "timestamp": timestamp,
            "kind": event.kind,
            "severity": event.severity,
            "message": event.message,
            "latitude": round(self.reading.latitude, 6),
            "longitude": round(self.reading.longitude, 6),
        }
