from __future__ import annotations

from dataclasses import dataclass

from roadlog.rules import (
    BREAK_WARNING,
    CONTINUOUS_DRIVING_LIMIT,
    MINUTE,
    SPEED_LIMIT,
    DriverClock,
)

MOVING = 5.0
MISMATCH_RATIO = 0.05
MISMATCH_FLOOR = 2.0
MISMATCH_SAMPLES = 3
SPEED_RELEASE = SPEED_LIMIT - 2
OVERDUE_REPEAT = 30 * MINUTE

INFO = "info"
WARNING = "warning"
INFRINGEMENT = "infringement"


@dataclass(frozen=True)
class Reading:
    latitude: float
    longitude: float
    heading: float
    gnss_speed: float
    odometer_speed: float
    card: str | None
    activity: str


@dataclass(frozen=True)
class Event:
    kind: str
    severity: str
    message: str


def hours(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60}h{minutes % 60:02d}"


class ControlUnit:
    def __init__(self) -> None:
        self.speeding = False
        self.mismatches = 0
        self.cardless = False
        self.warned = False
        self.overdue_reported_at: float | None = None
        self.daily_reported = False

    def inspect(self, reading: Reading, clock: DriverClock) -> list[Event]:
        events = [
            *self._speed(reading),
            *self._sensors(reading),
            *self._card(reading),
            *self._driving_time(clock),
        ]
        return events

    def _speed(self, reading: Reading) -> list[Event]:
        if reading.gnss_speed > SPEED_LIMIT and not self.speeding:
            self.speeding = True
            return [
                Event(
                    "speeding",
                    WARNING,
                    f"Speeding at {reading.gnss_speed:.0f} km/h, limit {SPEED_LIMIT:.0f}",
                )
            ]
        if reading.gnss_speed < SPEED_RELEASE:
            self.speeding = False
        return []

    def _sensors(self, reading: Reading) -> list[Event]:
        gap = abs(reading.gnss_speed - reading.odometer_speed)
        if reading.gnss_speed > MOVING and gap > max(
            MISMATCH_FLOOR, MISMATCH_RATIO * reading.gnss_speed
        ):
            self.mismatches += 1
            if self.mismatches == MISMATCH_SAMPLES:
                return [
                    Event(
                        "sensor-mismatch",
                        WARNING,
                        f"GNSS {reading.gnss_speed:.0f} km/h but odometer "
                        f"{reading.odometer_speed:.0f} km/h",
                    )
                ]
        else:
            self.mismatches = 0
        return []

    def _card(self, reading: Reading) -> list[Event]:
        moving = reading.gnss_speed > MOVING
        if moving and reading.card is None and not self.cardless:
            self.cardless = True
            return [Event("no-card", INFRINGEMENT, "Driving without a driver card")]
        if reading.card is not None:
            self.cardless = False
        return []

    def _driving_time(self, clock: DriverClock) -> list[Event]:
        events = []
        if clock.continuous >= BREAK_WARNING and not self.warned:
            self.warned = True
            events.append(Event("break-due", INFO, f"Break due in {hours(clock.until_break)}"))
        if clock.continuous < BREAK_WARNING:
            self.warned = False
            self.overdue_reported_at = None
        if clock.break_overdue and (
            self.overdue_reported_at is None
            or clock.continuous - self.overdue_reported_at >= OVERDUE_REPEAT
        ):
            self.overdue_reported_at = clock.continuous
            events.append(
                Event(
                    "break-overdue",
                    INFRINGEMENT,
                    f"{hours(clock.continuous)} driven without a 45 min break, "
                    f"limit {hours(CONTINUOUS_DRIVING_LIMIT)}",
                )
            )
        if clock.daily_exceeded and not self.daily_reported:
            self.daily_reported = True
            events.append(
                Event("daily-limit", INFRINGEMENT, f"{hours(clock.daily)} driven today, limit 9h00")
            )
        if not clock.daily_exceeded:
            self.daily_reported = False
        return events
