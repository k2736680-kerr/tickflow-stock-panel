"""Regression: a multi-day OHLC range must not be served from the single-day cache."""
from datetime import date

import polars as pl

from app.tickflow.repository import KlineRepository


def _repo_with_cache(cache_date: date) -> KlineRepository:
    repo = KlineRepository.__new__(KlineRepository)
    repo._enriched_warming = False
    repo._enriched_cache = pl.DataFrame({
        "symbol": ["600001.SH"],
        "date": [cache_date],
        "open": [10.0],
        "high": [10.2],
        "close": [10.1],
    })
    repo._enriched_cache_date = cache_date
    return repo


def _bars() -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": ["600001.SH", "600001.SH"],
        "date": [date(2026, 11, 3), date(2026, 11, 4)],
        "open": [10.05, 10.40],
        "high": [10.30, 10.60],
        "close": [10.20, 10.50],
    })


def test_multi_day_range_scans_parquet(monkeypatch):
    """The review ledger asks for 11-03..11-05 and must never get the 11-02 cache."""
    repo = _repo_with_cache(date(2026, 11, 2))
    calls: list[tuple] = []

    def fake_scan(self, symbols, start, end, columns=None):
        calls.append((symbols, start, end, columns))
        return _bars()

    monkeypatch.setattr(KlineRepository, "_scan_daily_batch", fake_scan)
    cols = ["symbol", "date", "open", "high", "close"]
    out = repo.get_daily_batch(
        ["600001.SH"], date(2026, 11, 3), date(2026, 11, 5), columns=cols,
    )
    assert len(calls) == 1
    assert calls[0][1:] == (date(2026, 11, 3), date(2026, 11, 5), cols)
    assert set(out["date"].to_list()) == {date(2026, 11, 3), date(2026, 11, 4)}


def test_exact_single_day_still_uses_cache(monkeypatch):
    repo = _repo_with_cache(date(2026, 11, 4))

    def fake_scan(self, symbols, start, end, columns=None):
        raise AssertionError("exact single-day request should hit the cache")

    monkeypatch.setattr(KlineRepository, "_scan_daily_batch", fake_scan)
    out = repo.get_daily_batch(
        ["600001.SH"], date(2026, 11, 4), date(2026, 11, 4),
        columns=["symbol", "date", "open", "high", "close"],
    )
    assert out["date"].to_list() == [date(2026, 11, 4)]
