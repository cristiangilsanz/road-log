from collections import Counter

import pytest

from roadlog.rules import HOUR, MINUTE, DriverClock
from roadlog.twin.control_unit import ControlUnit, Reading
from roadlog.twin.tachograph import Tachograph
from roadlog.twin.vehicle import Activity, profile

from conftest import assignment


def simulate(profile_name, hours=24, step=30.0, seeds=3):
    kinds = Counter()
    for seed in range(seeds):
        tachograph = Tachograph(assignment(profile_name), seed=seed)
        for _ in range(int(hours * HOUR / step)):
            kinds.update(event.kind for event in tachograph.tick(step))
    return kinds


def reading(gnss=80.0, odometer=80.0, card="ESD0001"):
    return Reading(40.0, -3.0, 90.0, gnss, odometer, card, "driving")


def test_careful_drivers_stay_within_the_law():
    assert simulate("careful") == Counter()


def test_each_profile_breaks_its_own_rule():
    assert set(simulate("speeder")) == {"speeding"}
    assert set(simulate("faulty-odometer")) == {"sensor-mismatch"}
    assert set(simulate("forgetful")) == {"no-card"}
    assert {"break-overdue", "daily-limit"} <= set(simulate("tired"))


def test_trucks_turn_around_after_loading():
    tachograph = Tachograph(assignment(), seed=1)
    vehicle = tachograph.vehicle
    vehicle.distance = vehicle.route.length - 10
    vehicle.speed = 80
    vehicle.clocks = (DriverClock(), DriverClock())
    tachograph.tick(60)
    assert vehicle.activity is Activity.LOADING
    assert vehicle.route.name == "Valencia - Madrid"
    assert vehicle.trips == 1


def test_breaks_stop_the_truck_and_reset_the_clock():
    tachograph = Tachograph(assignment(), seed=2)
    vehicle = tachograph.vehicle
    vehicle.clock.continuous = vehicle.profile.break_after
    tachograph.tick(60)
    assert vehicle.activity is Activity.BREAK and vehicle.speed == 0
    for _ in range(60):
        tachograph.tick(60)
    assert vehicle.activity is Activity.DRIVING
    assert vehicle.clock.continuous < HOUR


def test_the_co_driver_takes_over_at_the_end_of_a_shift():
    tachograph = Tachograph(assignment(), seed=4)
    vehicle = tachograph.vehicle
    vehicle.clock.daily = vehicle.profile.daily_stop_after
    tachograph.tick(60)
    assert vehicle.activity is Activity.CREW_CHANGE
    for _ in range(20):
        tachograph.tick(60)
    assert vehicle.activity is Activity.DRIVING
    assert vehicle.card == "ESD0001B"
    assert tachograph.telemetry(0.0)["driver_card"] == "ESD0001B"
    assert vehicle.co_driver.daily == vehicle.profile.daily_stop_after


def test_the_resting_co_driver_starts_a_fresh_day():
    tachograph = Tachograph(assignment(), seed=5)
    vehicle = tachograph.vehicle
    vehicle.clocks = (DriverClock(), DriverClock(continuous=4 * HOUR, daily=8 * HOUR))
    for _ in range(9 * 60):
        tachograph.tick(60)
    assert vehicle.driver == 0
    assert vehicle.co_driver.daily == 0 and vehicle.co_driver.continuous == 0


def test_unknown_profiles_are_rejected():
    with pytest.raises(ValueError, match="careful"):
        profile("reckless")


def test_telemetry_carries_the_driving_clock():
    tachograph = Tachograph(assignment(), seed=3)
    tachograph.tick(60)
    data = tachograph.telemetry(1000.0)
    assert data["vehicle_id"] == "TRK-99"
    assert data["continuous_driving"] == round(tachograph.vehicle.clock.continuous)
    assert data["telemetry_interval"] == 2.0


def test_speeding_is_reported_once_per_episode():
    unit = ControlUnit()
    clock = DriverClock()
    kinds = [
        e.kind for speed in (95, 97, 96, 85, 94) for e in unit.inspect(reading(speed, speed), clock)
    ]
    assert kinds == ["speeding", "speeding"]


def test_sensor_mismatch_needs_three_samples():
    unit = ControlUnit()
    clock = DriverClock()
    found = [unit.inspect(reading(80, 70), clock) for _ in range(4)]
    assert [len(events) for events in found] == [0, 0, 1, 0]
    assert "odometer 70" in found[2][0].message


def test_small_speed_differences_are_tolerated():
    unit = ControlUnit()
    assert not any(unit.inspect(reading(80, 78.5), DriverClock()) for _ in range(5))


def test_driving_without_a_card_is_reported_once():
    unit = ControlUnit()
    clock = DriverClock()
    events = [e for _ in range(3) for e in unit.inspect(reading(card=None), clock)]
    assert [e.kind for e in events] == ["no-card"]
    assert events[0].severity == "infringement"


def test_driving_time_warnings_escalate():
    unit = ControlUnit()
    clock = DriverClock(continuous=4.25 * HOUR, daily=4.25 * HOUR)
    assert [e.kind for e in unit.inspect(reading(), clock)] == ["break-due"]
    clock.drive(16 * MINUTE)
    assert [e.kind for e in unit.inspect(reading(), clock)] == ["break-overdue"]
    clock.drive(10 * MINUTE)
    assert unit.inspect(reading(), clock) == []
    clock.drive(25 * MINUTE)
    assert [e.kind for e in unit.inspect(reading(), clock)] == ["break-overdue"]


def test_the_daily_limit_is_reported_once():
    unit = ControlUnit()
    clock = DriverClock(daily=9 * HOUR + MINUTE)
    assert "daily-limit" in [e.kind for e in unit.inspect(reading(), clock)]
    assert "daily-limit" not in [e.kind for e in unit.inspect(reading(), clock)]
