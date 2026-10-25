from __future__ import annotations

import gzip
import json
from bisect import bisect_right
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from itertools import accumulate, pairwise

from roadlog.geo import Point, bearing, haversine, interpolate


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    heading: float
    speed_limit: float


@dataclass(frozen=True)
class Route:
    name: str
    origin: str
    destination: str
    points: tuple[Point, ...]
    speeds: tuple[float, ...]
    offsets: tuple[float, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.points) < 2 or len(self.speeds) != len(self.points) - 1:
            raise ValueError(f"route {self.name!r} needs one speed per segment")
        lengths = (haversine(a, b) for a, b in pairwise(self.points))
        object.__setattr__(self, "offsets", (0.0, *accumulate(lengths)))

    @property
    def length(self) -> float:
        return self.offsets[-1]

    def reversed(self) -> Route:
        return Route(
            name=f"{self.destination} - {self.origin}",
            origin=self.destination,
            destination=self.origin,
            points=self.points[::-1],
            speeds=self.speeds[::-1],
        )

    def locate(self, distance: float) -> Location:
        distance = min(max(distance, 0.0), self.length)
        segment = min(bisect_right(self.offsets, distance) - 1, len(self.speeds) - 1)
        start, end = self.points[segment], self.points[segment + 1]
        span = self.offsets[segment + 1] - self.offsets[segment]
        fraction = (distance - self.offsets[segment]) / span if span else 0.0
        latitude, longitude = interpolate(start, end, fraction)
        return Location(latitude, longitude, bearing(start, end), self.speeds[segment])


@cache
def load_routes() -> dict[str, Route]:
    path = files("roadlog") / "data" / "routes.json.gz"
    with gzip.open(path.open("rb"), "rt", encoding="utf-8") as handle:
        raw = json.load(handle)
    return {
        item["name"]: Route(
            name=item["name"],
            origin=item["origin"],
            destination=item["destination"],
            points=tuple((lat, lon) for lat, lon in item["points"]),
            speeds=tuple(item["speeds"]),
        )
        for item in raw
    }


def route(name: str) -> Route:
    routes = load_routes()
    if name not in routes:
        raise ValueError(f"unknown route {name!r}, choose one of: {', '.join(routes)}")
    return routes[name]
