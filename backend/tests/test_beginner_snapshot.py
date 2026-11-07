from __future__ import annotations

from pathlib import Path

from app.services import beginner_pick_review as review


def _payload(as_of: str, symbol: str, close: float, vol: int) -> dict:
    return {
        "as_of": as_of,
        "verdict": "open",
        "pick_mode": "e1",
        "headline": "今日深跌抄底",
        "picks": [{"symbol": symbol, "name": "测试票", "close": close}],
        "funnel": {"amt_q": 21, "vol": vol},
        "gates": [],
    }


def _no_settle(monkeypatch) -> None:
    monkeypatch.setattr(
        review, "settle_log", lambda repo, data_dir: review._empty_log()
    )


def test_same_as_of_is_pinned_after_first_call(tmp_path: Path, monkeypatch) -> None:
    _no_settle(monkeypatch)
    first = review.attach_review(
        None, tmp_path, _payload("2026-11-05", "603900.SH", 5.46, 2)
    )
    second = review.attach_review(
        None, tmp_path, _payload("2026-11-05", "605286.SH", 22.88, 1)
    )
    assert first["picks"][0]["symbol"] == "603900.SH"
    assert second["picks"][0]["symbol"] == "603900.SH"
    assert second["funnel"] == {"amt_q": 21, "vol": 2}
    assert "live_review" in second


def test_snapshot_is_per_signal_day(tmp_path: Path, monkeypatch) -> None:
    _no_settle(monkeypatch)
    review.attach_review(None, tmp_path, _payload("2026-11-05", "603900.SH", 5.46, 2))
    other = review.attach_review(
        None, tmp_path, _payload("2026-11-06", "605286.SH", 22.88, 1)
    )
    assert other["picks"][0]["symbol"] == "605286.SH"
    assert review.load_snapshot(tmp_path, "2026-11-05")["picks"][0]["symbol"] == "603900.SH"
    assert review.load_snapshot(tmp_path, "2026-11-06")["picks"][0]["symbol"] == "605286.SH"


def test_live_review_is_not_stored_in_snapshot(tmp_path: Path, monkeypatch) -> None:
    _no_settle(monkeypatch)
    review.attach_review(None, tmp_path, _payload("2026-11-05", "603900.SH", 5.46, 2))
    snap = review.load_snapshot(tmp_path, "2026-11-05")
    assert "live_review" not in snap
    assert review.load_snapshot(tmp_path, "not-a-date") is None
