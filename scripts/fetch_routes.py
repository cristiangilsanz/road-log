import gzip
import json
import time
import urllib.request
from pathlib import Path

OSRM = "https://router.project-osrm.org/route/v1/driving/{coordinates}?overview=full&geometries=geojson&annotations=distance,duration"
TARGET = Path(__file__).resolve().parent.parent / "src" / "roadlog" / "data" / "routes.json.gz"
MIN_PIECE = 250.0

CITIES = {
    "Madrid": (40.4168, -3.7038),
    "Valencia": (39.4699, -0.3763),
    "Zaragoza": (41.6488, -0.8891),
    "Seville": (37.3891, -5.9845),
    "Barcelona": (41.3851, 2.1734),
    "Bilbao": (43.2630, -2.9350),
    "Salamanca": (40.9701, -5.6631),
    "Malaga": (36.7213, -4.4214),
}

ROUTES = [
    ("Madrid", "Valencia"),
    ("Madrid", "Zaragoza"),
    ("Madrid", "Seville"),
    ("Barcelona", "Zaragoza"),
    ("Bilbao", "Madrid"),
    ("Valencia", "Barcelona"),
    ("Madrid", "Salamanca"),
    ("Seville", "Malaga"),
]


def fetch(origin, destination):
    points = ";".join(f"{CITIES[name][1]},{CITIES[name][0]}" for name in (origin, destination))
    request = urllib.request.Request(
        OSRM.format(coordinates=points), headers={"User-Agent": "road-log route fetcher"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        route = json.load(response)["routes"][0]
    annotation = route["legs"][0]["annotation"]
    return route["geometry"]["coordinates"], annotation["distance"], annotation["duration"]


def simplify(coordinates, distances, durations):
    points = [[round(coordinates[0][1], 5), round(coordinates[0][0], 5)]]
    speeds = []
    length = time_taken = 0.0
    for index, (distance, duration) in enumerate(zip(distances, durations, strict=True)):
        length += distance
        time_taken += duration
        last = index == len(distances) - 1
        if length >= MIN_PIECE or last:
            lon, lat = coordinates[index + 1]
            points.append([round(lat, 5), round(lon, 5)])
            speed = length / time_taken * 3.6 if time_taken else 0.0
            speeds.append(round(speed, 1))
            length = time_taken = 0.0
    return points, speeds


def main():
    routes = []
    for origin, destination in ROUTES:
        points, speeds = simplify(*fetch(origin, destination))
        name = f"{origin} - {destination}"
        routes.append(
            {
                "name": name,
                "origin": origin,
                "destination": destination,
                "points": points,
                "speeds": speeds,
            }
        )
        print(f"{name}: {len(points)} points")
        time.sleep(1)
    with gzip.open(TARGET, "wt", encoding="utf-8") as handle:
        json.dump(routes, handle, separators=(",", ":"))


if __name__ == "__main__":
    main()
