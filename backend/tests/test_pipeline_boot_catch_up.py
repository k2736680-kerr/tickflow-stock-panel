from datetime import datetime, timedelta

from app.jobs.daily_pipeline import expected_kline_as_of, needs_boot_catch_up
from app.market_time import CN_TZ


def test_expected_kline_before_close_uses_previous_weekday():
    tue_morning = datetime(2026, 11, 3, 10, 0, tzinfo=CN_TZ)
    assert expected_kline_as_of(tue_morning) == datetime(2026, 11, 2).date()


def test_expected_kline_one_minute_before_close_still_previous_day():
    tue = datetime(2026, 11, 3, 14, 59, tzinfo=CN_TZ)
    assert expected_kline_as_of(tue) == datetime(2026, 11, 2).date()


def test_expected_kline_after_close_uses_today_on_weekday():
    # 收盘(15:00)后即把今天当目标日, 不再等 17:00 的固定钟点。
    for hh, mm in [(15, 0), (15, 30), (16, 20), (17, 30)]:
        tue = datetime(2026, 11, 3, hh, mm, tzinfo=CN_TZ)
        assert expected_kline_as_of(tue) == datetime(2026, 11, 3).date()


def test_expected_kline_weekend_uses_friday():
    sat = datetime(2026, 11, 7, 12, 0, tzinfo=CN_TZ)
    sun = datetime(2026, 11, 8, 18, 0, tzinfo=CN_TZ)
    assert expected_kline_as_of(sat) == datetime(2026, 11, 6).date()
    assert expected_kline_as_of(sun) == datetime(2026, 11, 6).date()


def test_expected_kline_monday_morning_uses_friday():
    monday = datetime(2026, 11, 2, 9, 0, tzinfo=CN_TZ)
    assert expected_kline_as_of(monday) == datetime(2026, 10, 30).date()


def test_needs_boot_catch_up_false_when_local_matches_expected():
    now = datetime(2026, 11, 3, 18, 0, tzinfo=CN_TZ)
    latest = expected_kline_as_of(now)
    assert needs_boot_catch_up(latest, now) is False


def test_needs_boot_catch_up_true_when_empty_or_behind():
    now = datetime(2026, 11, 3, 18, 0, tzinfo=CN_TZ)
    assert needs_boot_catch_up(None, now) is True
    assert needs_boot_catch_up(expected_kline_as_of(now) - timedelta(days=5), now) is True
