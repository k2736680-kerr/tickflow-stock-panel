from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.services.beginner_pick_review import (
    archive_payload,
    attach_review,
    load_log_readonly,
    settle_log,
    summarize,
)


class _Repo:
    def __init__(self, bars: pl.DataFrame, latest: date):
        self._bars = bars
        self._latest = latest
        self.store = type("S", (), {"data_dir": Path(".")})()

    def latest_daily_date(self):
        return self._latest

    def get_daily_batch(self, symbols, start, end, columns=None):
        df = self._bars
        if "symbol" in df.columns:
            df = df.filter(pl.col("symbol").is_in(list(symbols)))
        df = df.filter((pl.col("date") >= start) & (pl.col("date") <= end))
        if columns:
            keep = [c for c in columns if c in df.columns]
            df = df.select(keep)
        return df


def _payload(as_of: str, picks: list[dict], *, verdict="open", pick_mode="e1"):
    return {
        "as_of": as_of,
        "verdict": verdict,
        "pick_mode": pick_mode,
        "headline": "今日深跌抄底",
        "picks": picks,
    }


def test_next_close_up_counts_as_correct(tmp_path: Path):
    data_dir = tmp_path
    archive_payload(
        _payload("2026-11-02", [{"symbol": "600001.SH", "name": "测试", "close": 10.0}]),
        data_dir,
    )
    bars = pl.DataFrame({
        "symbol": ["600001.SH", "600001.SH"],
        "date": [date(2026, 11, 3), date(2026, 11, 4)],
        "open": [10.05, 10.40],
        "high": [10.30, 10.60],
        "close": [10.20, 10.50],
    })
    log = settle_log(_Repo(bars, date(2026, 11, 4)), data_dir)
    pick = log["sessions"][0]["picks"][0]
    assert pick["correct_next_close"] is True
    assert pick["rose_after_buy"] is True
    assert pick["next_close_vs_signal"] == 0.02
    assert log["sessions"][0]["next_close_win"] == 1
    stats = summarize(log)
    assert stats["picks_settled"] == 1
    assert stats["next_close_win_rate"] == 1.0
    assert stats["auto_tune"] is False
    assert stats["rule_change"]["ready"] is False
    assert stats["rule_change"]["changes_rules"] is False
    assert stats["rule_change"]["min_settled_days"] == 40


def test_next_close_down_counts_as_wrong(tmp_path: Path):
    data_dir = tmp_path
    archive_payload(
        _payload("2026-11-02", [{"symbol": "600001.SH", "name": "测试", "close": 10.0}]),
        data_dir,
    )
    bars = pl.DataFrame({
        "symbol": ["600001.SH"],
        "date": [date(2026, 11, 3)],
        "open": [9.95],
        "high": [10.00],
        "close": [9.70],
    })
    log = settle_log(_Repo(bars, date(2026, 11, 3)), data_dir)
    pick = log["sessions"][0]["picks"][0]
    assert pick["correct_next_close"] is False
    assert pick["status"] == "settled"


def test_open_gap_skip_still_scores_next_close(tmp_path: Path):
    data_dir = tmp_path
    archive_payload(
        _payload("2026-11-02", [{"symbol": "600001.SH", "name": "测试", "close": 10.0}]),
        data_dir,
    )
    bars = pl.DataFrame({
        "symbol": ["600001.SH"],
        "date": [date(2026, 11, 3)],
        "open": [10.20],
        "high": [10.30],
        "close": [10.25],
    })
    log = settle_log(_Repo(bars, date(2026, 11, 3)), data_dir)
    pick = log["sessions"][0]["picks"][0]
    assert pick["skipped_gap"] is True
    assert pick["status"] == "skipped_gap"
    assert pick["correct_next_close"] is True
    assert log["sessions"][0]["settled"] is True


def test_pending_until_next_bar(tmp_path: Path):
    data_dir = tmp_path
    archive_payload(
        _payload("2026-11-02", [{"symbol": "600001.SH", "name": "测试", "close": 10.0}]),
        data_dir,
    )
    bars = pl.DataFrame({
        "symbol": ["600001.SH"],
        "date": [date(2026, 11, 2)],
        "open": [10.0],
        "high": [10.1],
        "close": [10.0],
    })
    log = settle_log(_Repo(bars, date(2026, 11, 2)), data_dir)
    assert log["sessions"][0].get("settled") in (False, None)
    pick = log["sessions"][0]["picks"][0]
    assert pick.get("correct_next_close") is None


def test_empty_regime_skip_is_logged(tmp_path: Path):
    data_dir = tmp_path
    archive_payload(
        _payload("2026-11-02", [], verdict="no_candidates", pick_mode="e1_skip_regime"),
        data_dir,
    )
    log = settle_log(_Repo(pl.DataFrame(), date(2026, 11, 3)), data_dir)
    assert log["sessions"][0]["picks"] == []
    assert log["sessions"][0]["settled"] is True
    stats = summarize(log)
    assert stats["empty_days"] == 1
    assert stats["picks_settled"] == 0


def test_reattach_does_not_wipe_settled_prices(tmp_path: Path):
    data_dir = tmp_path
    payload = _payload("2026-11-02", [{"symbol": "600001.SH", "name": "测试", "close": 10.0}])
    archive_payload(payload, data_dir)
    bars = pl.DataFrame({
        "symbol": ["600001.SH"],
        "date": [date(2026, 11, 3)],
        "open": [10.05],
        "high": [10.30],
        "close": [10.20],
    })
    repo = _Repo(bars, date(2026, 11, 3))
    settle_log(repo, data_dir)
    out = attach_review(repo, data_dir, payload)
    pick = out["live_review"]["sessions"][0]["picks"][0]
    assert pick["next_close"] == 10.2
    assert pick["correct_next_close"] is True
    assert out["live_review"]["stats"]["auto_tune"] is False


def test_ledger_keeps_features_for_later_analysis(tmp_path: Path):
    data_dir = tmp_path
    archive_payload(
        {
            "as_of": "2026-11-02",
            "verdict": "open",
            "pick_mode": "e1",
            "headline": "今日深跌抄底",
            "csi_band": "PANIC",
            "g1": -0.2,
            "funnel": {"e1_picks": 1},
            "gates": [{"id": "csi300_band", "ok": True, "detail": "恐慌"}],
            "picks": [{
                "symbol": "600001.SH",
                "name": "测试",
                "close": 10.0,
                "change_pct": -0.02,
                "dd60": -0.35,
                "amt_q": 12.0,
                "vol_ratio_5d": 1.8,
                "reasons": ["距 60 日高点 -35%"],
            }],
        },
        data_dir,
    )
    bars = pl.DataFrame({
        "symbol": ["600001.SH", "600001.SH"],
        "date": [date(2026, 11, 3), date(2026, 11, 4)],
        "open": [10.05, 10.40],
        "high": [10.30, 10.60],
        "close": [10.20, 10.50],
    })
    log = settle_log(_Repo(bars, date(2026, 11, 4)), data_dir)
    session = log["sessions"][0]
    pick = session["picks"][0]
    assert log["purpose"] == "ledger"
    assert log["auto_tune"] is False
    assert session["csi_band"] == "PANIC"
    assert pick["dd60"] == -0.35
    assert pick["amt_q"] == 12.0
    assert pick["next_high"] == 10.3
    assert pick["tplus1_date"] == "2026-11-04"
    assert pick["tplus1_close"] == 10.5
    assert (data_dir / "user_data" / "tickflow.db").exists()
    assert not (data_dir / "user_data" / "beginner_pick_log.json").exists()


def test_json_ledger_migrates_into_sqlite(tmp_path: Path):
    data_dir = tmp_path
    json_path = data_dir / "user_data" / "beginner_pick_log.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        '{"purpose":"ledger","sessions":[{"as_of":"2026-11-01","picks":[]}]}',
        encoding="utf-8",
    )
    log = settle_log(_Repo(pl.DataFrame(), date(2026, 11, 2)), data_dir)
    assert log["sessions"][0]["as_of"] == "2026-11-01"
    assert (data_dir / "user_data" / "tickflow.db").exists()
    assert not json_path.exists()


def test_readonly_ledger_does_not_create_db(tmp_path: Path):
    log = load_log_readonly(tmp_path)
    assert log["sessions"] == []
    assert not (tmp_path / "user_data" / "tickflow.db").exists()


def test_close_above_signal_can_still_be_down_from_the_open(tmp_path: Path):
    data_dir = tmp_path
    archive_payload(
        _payload("2026-11-02", [{"symbol": "600001.SH", "name": "测试", "close": 10.0}]),
        data_dir,
    )
    bars = pl.DataFrame({
        "symbol": ["600001.SH"],
        "date": [date(2026, 11, 3)],
        "open": [10.10],
        "high": [10.12],
        "close": [10.05],
    })
    log = settle_log(_Repo(bars, date(2026, 11, 3)), data_dir)
    pick = log["sessions"][0]["picks"][0]
    assert pick["skipped_gap"] is False
    assert pick["correct_next_close"] is True
    assert pick["rose_after_buy"] is False
    stats = summarize(log)
    assert stats["rose_after_buy_n"] == 1
    assert stats["rose_after_buy_win"] == 0


def test_rule_change_gate_opens_at_40_days_without_tuning():
    start = date(2025, 1, 2)
    sessions = [
        {
            "as_of": (start + timedelta(days=i)).isoformat(),
            "settled": True,
            "next_close_n": 1,
            "next_close_win": 0,
            "pick_mode": "e1",
        }
        for i in range(40)
    ]
    ready = summarize({"sessions": sessions})
    assert ready["days_settled"] == 40
    assert ready["rule_change"]["ready"] is True
    assert ready["auto_tune"] is False
    assert ready["rule_change"]["changes_rules"] is False
    short = summarize({"sessions": sessions[:39]})
    assert short["rule_change"]["ready"] is False
    assert "只记不改" in short["rule_change"]["note"]
