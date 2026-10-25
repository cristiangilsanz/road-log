from __future__ import annotations

from math import atan2, cos, degrees, radians, sin, sqrt

EARTH_RADIUS = 6_371_000.0

Point = tuple[float, float]


def haversine(a: Point, b: Point) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS * atan2(sqrt(h), sqrt(1 - h))


def bearing(a: Point, b: Point) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    x = sin(lon2 - lon1) * cos(lat2)
    y = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(lon2 - lon1)
    return (degrees(atan2(x, y)) + 360) % 360


def interpolate(a: Point, b: Point, fraction: float) -> Point:
    return (a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction)
