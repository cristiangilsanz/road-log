from roadlog.rules import HOUR, MINUTE, DriverClock


def test_driving_adds_to_both_counters():
    clock = DriverClock()
    clock.drive(2 * HOUR)
    assert clock.continuous == clock.daily == 2 * HOUR
    assert clock.until_break == 2.5 * HOUR


def test_a_45_minute_break_resets_continuous_driving():
    clock = DriverClock()
    clock.drive(4 * HOUR)
    clock.rest(45 * MINUTE)
    assert clock.continuous == 0
    assert clock.daily == 4 * HOUR


def test_a_short_stop_is_not_a_break():
    clock = DriverClock()
    clock.drive(4 * HOUR)
    clock.rest(30 * MINUTE)
    clock.drive(MINUTE)
    clock.rest(30 * MINUTE)
    assert clock.continuous == 4 * HOUR + MINUTE


def test_a_daily_rest_resets_the_day():
    clock = DriverClock()
    clock.drive(8 * HOUR)
    clock.rest(9 * HOUR)
    assert clock.daily == 0


def test_limits_follow_regulation_561_2006():
    clock = DriverClock()
    clock.drive(4.25 * HOUR)
    assert clock.break_due and not clock.break_overdue
    clock.drive(0.5 * HOUR)
    assert clock.break_overdue
    clock.drive(4.5 * HOUR)
    assert clock.daily_exceeded
