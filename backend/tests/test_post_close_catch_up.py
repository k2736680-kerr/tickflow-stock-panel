from datetime import date, datetime

from app.jobs.daily_pipeline import in_post_close_window, should_catch_up_today
from app.market_time import CN_TZ

_NO_DAY = date(2000, 1, 1)  # 哨兵: 今天还没补跑过
_TUE = date(2026, 11, 3)    # 目标交易日
_MON = date(2026, 11, 2)    # 本地/远端仍停在上一交易日


def _t(hh: int, mm: int, day: int = 3) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=CN_TZ)


def test_window_boundaries():
    assert in_post_close_window(_t(14, 59)) is False
    assert in_post_close_window(_t(15, 4)) is False
    assert in_post_close_window(_t(15, 5)) is True
    assert in_post_close_window(_t(16, 20)) is True
    assert in_post_close_window(_t(19, 59)) is True
    assert in_post_close_window(_t(20, 0)) is False
    assert in_post_close_window(_t(16, 20, day=7)) is False  # 周六


def test_catch_up_waits_when_remote_not_ready():
    # 数据源仍停在昨天: 只等下一轮, 不空跑全市场
    assert should_catch_up_today(_MON, _MON, _t(16, 20), done_day=_NO_DAY) is False
    assert should_catch_up_today(_MON, None, _t(16, 20), done_day=_NO_DAY) is False


def test_catch_up_triggers_when_remote_arrived():
    assert should_catch_up_today(_MON, _TUE, _t(16, 20), done_day=_NO_DAY) is True
    assert should_catch_up_today(None, _TUE, _t(16, 20), done_day=_NO_DAY) is True


def test_catch_up_skips_when_local_already_current():
    assert should_catch_up_today(_TUE, _TUE, _t(16, 20), done_day=_NO_DAY) is False


def test_catch_up_skips_when_already_done_today():
    assert should_catch_up_today(_MON, _TUE, _t(16, 20), done_day=_TUE) is False


def test_catch_up_skips_outside_window():
    assert should_catch_up_today(_MON, _TUE, _t(20, 5), done_day=_NO_DAY) is False
    assert should_catch_up_today(_MON, _TUE, _t(10, 0), done_day=_NO_DAY) is False
