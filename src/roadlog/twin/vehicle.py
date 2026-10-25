from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum

from roadlog.routes import Location, Route
from roadlog.rules import HOUR, MINUTE, DriverClock

RESPONSE_TIME = 30.0
LOADING_TIME = 40 * MINUTE
CREW_CHANGE = 15 * MINUTE


class Activity(StrEnum):
    DRIVING = "driving"
    BREAK = "break"
    CREW_CHANGE = "crew-change"
    LOADING = "loading"


@dataclass(frozen=True)
class Profile:
    name: str
    speed_cap: float
    break_after: float
    daily_stop_after: float
    odometer_factor: float = 1.0
    cardless_after_stop: float = 0.0


PROFILES = {
    profile.name: profile
    for profile in (
        Profile("careful", 84, 4.05 * HOUR, 8.6 * HOUR),
        Profile("speeder", 104, 4.15 * HOUR, 8.8 * HOUR),
        Profile("tired", 85, 5.05 * HOUR, 9.6 * HOUR),
        Profile("faulty-odometer", 84, 4.1 * HOUR, 8.7 * HOUR, odometer_factor=0.88),
        Profile("forgetful", 84, 4.1 * HOUR, 8.7 * HOUR, cardless_after_stop=20 * MINUTE),
    )
}


def profile(name: str) -> Profile:
    if name not in PROFILES:
        raise ValueError(f"unknown profile {name!r}, choose one of: {', '.join(PROFILES)}")
    return PROFILES[name]


@dataclass
class Vehicle:
    route: Route
    profile: Profile
    cards: tuple[str, str]
    rng: random.Random
    distance: float = 0.0
    speed: float = 0.0
    activity: Activity = Activity.DRIVING
    remaining: float = 0.0
    cardless: float = 0.0
    trips: int = 0
    driver: int = 0
    clocks: tuple[DriverClock, DriverClock] = field(
        default_factory=lambda: (DriverClock(), DriverClock())
    )

    @property
    def location(self) -> Location:
        return self.route.locate(self.distance)

    @property
    def card(self) -> str:
        return self.cards[self.driver]

    @property
    def clock(self) -> DriverClock:
        return self.clocks[self.driver]

    @property
    def co_driver(self) -> DriverClock:
        return self.clocks[1 - self.driver]

    @property
    def card_inserted(self) -> bool:
        return self.cardless <= 0

    def step(self, seconds: float) -> None:
        self.co_driver.rest(seconds)
        if self.activity is Activity.DRIVING:
            self._drive(seconds)
        else:
            self._stand(seconds)

    def _stop(self, activity: Activity, duration: float) -> None:
        self.activity = activity
        self.remaining = duration
        self.speed = 0.0

    def _drive(self, seconds: float) -> None:
        if self.clock.daily >= self.profile.daily_stop_after:
            self._stop(Activity.CREW_CHANGE, CREW_CHANGE)
            return
        if self.clock.continuous >= self.profile.break_after:
            self._stop(Activity.BREAK, 45 * MINUTE + self.rng.uniform(0, 10 * MINUTE))
            return
        target = min(self.location.speed_limit, self.profile.speed_cap) + self.rng.gauss(0, 1.0)
        self.speed += (max(target, 0.0) - self.speed) * min(1.0, seconds / RESPONSE_TIME)
        self.distance += self.speed / 3.6 * seconds
        self.clock.drive(seconds)
        self.cardless = max(0.0, self.cardless - seconds)
        if self.distance >= self.route.length:
            self.route = self.route.reversed()
            self.distance = 0.0
            self.trips += 1
            self._stop(Activity.LOADING, LOADING_TIME)

    def _stand(self, seconds: float) -> None:
        self.remaining -= seconds
        if self.activity is not Activity.LOADING:
            self.clock.rest(seconds)
        if self.remaining <= 0:
            if self.activity is Activity.CREW_CHANGE:
                self.driver = 1 - self.driver
            self.activity = Activity.DRIVING
            self.cardless = self.profile.cardless_after_stop

    def gnss_speed(self) -> float:
        return max(0.0, self.speed + self.rng.gauss(0, 0.6)) if self.speed else 0.0

    def odometer_speed(self) -> float:
        reading = self.speed * self.profile.odometer_factor
        return max(0.0, reading * (1 + self.rng.gauss(0, 0.005))) if reading else 0.0
