import pytest

from roadlog.geo import bearing, haversine, interpolate
from roadlog.routes import Route, load_routes, route

MADRID = (40.4168, -3.7038)
VALENCIA = (39.4699, -0.3763)


def test_haversine_matches_the_known_distance():
    assert haversine(MADRID, VALENCIA) == pytest.approx(302_000, rel=0.01)
    assert haversine(MADRID, MADRID) == 0


def test_bearing_points_the_right_way():
    assert bearing((0.0, 0.0), (0.0, 1.0)) == pytest.approx(90)
    assert bearing((0.0, 0.0), (1.0, 0.0)) == pytest.approx(0)
    assert bearing((0.0, 0.0), (-1.0, 0.0)) == pytest.approx(180)


def test_interpolate_walks_between_points():
    assert interpolate((0.0, 0.0), (2.0, 4.0), 0.5) == (1.0, 2.0)


def test_eight_real_routes_are_bundled():
    routes = load_routes()
    assert len(routes) == 8
    assert route("Madrid - Valencia").length == pytest.approx(357_000, rel=0.02)
    assert all(150_000 < item.length < 600_000 for item in routes.values())


def test_speeds_come_from_the_road_network():
    speeds = route("Madrid - Seville").speeds
    assert max(speeds) < 110
    assert min(speeds) > 5


def test_locate_follows_the_route():
    chosen = route("Madrid - Valencia")
    start = chosen.locate(0)
    end = chosen.locate(chosen.length + 1000)
    assert haversine((start.latitude, start.longitude), MADRID) < 3000
    assert haversine((end.latitude, end.longitude), VALENCIA) < 3000


def test_reversing_swaps_the_ends():
    chosen = route("Madrid - Valencia")
    back = chosen.reversed()
    assert back.name == "Valencia - Madrid"
    assert back.points[0] == chosen.points[-1]
    assert back.length == pytest.approx(chosen.length)


def test_unknown_routes_are_rejected():
    with pytest.raises(ValueError, match="Madrid - Valencia"):
        route("Lisbon - Porto")


def test_routes_need_a_speed_per_segment():
    with pytest.raises(ValueError, match="one speed per segment"):
        Route("broken", "a", "b", ((0.0, 0.0), (0.0, 1.0)), (50.0, 60.0))
