"""The ledger must export real next-day closes so a later session can review it."""
from datetime import date
from pathlib import Path

import polars as pl

from app.services.beginner_pick_review import (
    REVIEW_CSV_NAME,
    REVIEW_MD_NAME,
    archive_payload,
    settle_log,
)


class _Repo:
    def __init__(self, bars: pl.DataFrame, latest: date):
        self._bars = bars
        self._latest = latest
        self.store = type("S", (), {"data_dir": Path(".")})()

    def latest_daily_date(self):
        return self._latest

    def get_daily_batch(self, symbols, start, end, columns=None):
        if self._bars.is_empty() or "date" not in self._bars.columns:
            return pl.DataFrame()
        df = self._bars.filter((pl.col("date") >= start) & (pl.col("date") <= end))
        if columns:
            df = df.select([c for c in columns if c in df.columns])
        return df


def test_settlement_writes_review_files(tmp_path: Path):
    archive_payload(
        {
            "as_of": "2026-11-02",
            "verdict": "open",
            "pick_mode": "e1",
            "headline": "today picks",
            "picks": [{
                "symbol": "600001.SH",
                "name": "sample",
                "close": 10.0,
                "dd60": -0.35,
                "amt_q": 12.0,
                "reasons": ["deep dip"],
            }],
        },
        tmp_path,
    )
    bars = pl.DataFrame({
        "symbol": ["600001.SH", "600001.SH"],
        "date": [date(2026, 11, 3), date(2026, 11, 4)],
        "open": [10.05, 10.40],
        "high": [10.30, 10.60],
        "close": [10.20, 10.50],
    })
    settle_log(_Repo(bars, date(2026, 11, 4)), tmp_path)

    md = (tmp_path / "user_data" / REVIEW_MD_NAME).read_text(encoding="utf-8")
    assert "600001.SH" in md
    assert "10.2" in md
    assert "+2.00%" in md
    assert "auto_tune=false" in md
    assert "deep dip" in md
    assert "暂未命中" in md

    csv_text = (tmp_path / "user_data" / REVIEW_CSV_NAME).read_text(encoding="utf-8-sig")
    assert "next_close" in csv_text.splitlines()[0]
    assert "tp_checked_days" in csv_text.splitlines()[0]
    assert "600001.SH" in csv_text
    assert "10.2" in csv_text
    assert "deep dip" in csv_text


def test_pending_day_is_marked_not_faked(tmp_path: Path):
    archive_payload(
        {
            "as_of": "2026-11-04",
            "verdict": "open",
            "pick_mode": "e1",
            "picks": [{"symbol": "600001.SH", "name": "sample", "close": 10.0}],
        },
        tmp_path,
    )
    settle_log(_Repo(pl.DataFrame(), date(2026, 11, 4)), tmp_path)
    md = (tmp_path / "user_data" / REVIEW_MD_NAME).read_text(encoding="utf-8")
    assert "待结算" in md
