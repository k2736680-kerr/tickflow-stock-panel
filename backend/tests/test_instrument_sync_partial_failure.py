from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from app.services import instrument_sync as sync


class _FakeExchanges:
    def __init__(self, failing: set[str]):
        self.failing = failing

    def get_instruments(self, ex: str, instrument_type: str = "stock") -> list[dict]:
        if ex in self.failing:
            raise RuntimeError("503 Service Unavailable")
        prefix, suffix = ("600", "SH") if ex == "SH" else ("430", "BJ")
        return [
            {
                "symbol": f"{prefix}00{i}.{suffix}",
                "name": f"新票{i}",
                "code": f"{prefix}00{i}",
                "exchange": ex,
                "region": "CN",
                "type": "stock",
                "ext": {},
            }
            for i in range(2)
        ]


def _patch(monkeypatch, failing: set[str]) -> None:
    monkeypatch.setattr(sync, "_fetch_instruments_via_provider", lambda: None)
    monkeypatch.setattr(
        sync, "get_client",
        lambda: type("C", (), {"exchanges": _FakeExchanges(failing)})(),
    )
    monkeypatch.setattr(
        "app.markets.get_market",
        lambda m: type("M", (), {"exchanges": ["SH", "SZ", "BJ"]})(),
    )


def _old_table(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "symbol": ["000001.SZ", "000002.SZ"],
        "name": ["平安银行", "万科A"],
        "exchange": ["SZ", "SZ"],
        "market": ["cn", "cn"],
        "as_of": [date(2026, 11, 5)] * 2,
    }).write_parquet(out)


def test_partial_failure_preserves_old_market_rows(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "instruments" / "instruments.parquet"
    _old_table(out)
    _patch(monkeypatch, {"SZ"})

    written = sync.sync_instruments(tmp_path, markets=["cn"])
    df = pl.read_parquet(out)
    syms = set(df["symbol"].to_list())

    assert "000001.SZ" in syms and "000002.SZ" in syms, "深市旧维表必须保留"
    assert dict(zip(df["symbol"].to_list(), df["name"].to_list()))["000001.SZ"] == "平安银行"
    assert any(s.startswith("600") for s in syms), "成功的沪市数据要写入"
    assert any(s.startswith("430") for s in syms), "成功的京市数据要写入"
    assert written == df.height


def test_all_cn_failed_keeps_existing_file_untouched(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "instruments" / "instruments.parquet"
    _old_table(out)
    before = out.read_bytes()
    _patch(monkeypatch, {"SH", "SZ", "BJ"})

    assert sync.sync_instruments(tmp_path, markets=["cn"]) == 0
    assert out.read_bytes() == before
