from __future__ import annotations

from dataclasses import dataclass

HOUR = 3600.0
MINUTE = 60.0

SPEED_LIMIT = 90.0
CONTINUOUS_DRIVING_LIMIT = 4.5 * HOUR
BREAK_WARNING = 4.25 * HOUR
BREAK_LENGTH = 45 * MINUTE
DAILY_DRIVING_LIMIT = 9 * HOUR
DAILY_REST = 9 * HOUR


@dataclass
class DriverClock:
    continuous: float = 0.0
    daily: float = 0.0
    resting: float = 0.0

    def drive(self, seconds: float) -> None:
        self.continuous += seconds
        self.daily += seconds
        self.resting = 0.0

    def rest(self, seconds: float) -> None:
        self.resting += seconds
        if self.resting >= BREAK_LENGTH:
            self.continuous = 0.0
        if self.resting >= DAILY_REST:
            self.daily = 0.0

    @property
    def break_due(self) -> bool:
        return self.continuous >= BREAK_WARNING

    @property
    def break_overdue(self) -> bool:
        return self.continuous > CONTINUOUS_DRIVING_LIMIT

    @property
    def daily_exceeded(self) -> bool:
        return self.daily > DAILY_DRIVING_LIMIT

    @property
    def until_break(self) -> float:
        return CONTINUOUS_DRIVING_LIMIT - self.continuous
