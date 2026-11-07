"""Beginner pick engine tests: gates, H11, E1 only. No 90% claims."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.services import beginner_picks as bp


def test_index_below_ma20_is_weak_tag_not_empty_day():
    closes = [100.0] * 19 + [90.0]
    ok, detail = bp.index_above_ma20(closes)
    assert ok is False
    assert "弱市" in detail
    gates = bp.evaluate_gates(
        index_closes=closes,
        universe_n=300,
        up=120,
        down=150,
        flat=30,
    )
    assert any(g.id == "index_ma20" and g.hard is False and g.ok is False for g in gates)
    assert bp.verdict_from_gates(gates, 8)[0] == "open"


def test_index_above_ma20_is_open():
    closes = list(range(80, 100))
    ok, detail = bp.index_above_ma20([float(x) for x in closes])
    assert ok is True
    assert ">" in detail


def test_index_short_history_fail_closed():
    ok, detail = bp.index_above_ma20([1.0, 2.0, 3.0])
    assert ok is False
    assert "不足" in detail


def test_g1_formula():
    assert bp.compute_g1(80, 20, 0) == pytest.approx(0.6)
    assert bp.compute_g1(0, 0, 0) is None


def test_main_board_only():
    assert bp.is_main_board("600000.SH") is True
    assert bp.is_main_board("000001.SZ") is True
    assert bp.is_main_board("002001.SZ") is True
    assert bp.is_main_board("300001.SZ") is False
    assert bp.is_main_board("688001.SH") is False
    assert bp.is_main_board("920001.BJ") is False


def test_h11_strong_negative_even_with_attachment_wording():
    assert bp.classify_announcement_title("关于立案调查的专项说明") == "hard"
    assert bp.classify_announcement_title("公司被执行人公告") == "hard"


def test_h11_down_context_not_hard():
    assert bp.classify_announcement_title("非经营性资金占用及其他关联资金往来情况表") is None
    assert bp.classify_announcement_title("投资者关系活动记录") is None


def test_h11_plain_hard_negative():
    assert bp.classify_announcement_title("收到中国证监会行政处罚事先告知书") == "hard"
    assert bp.classify_announcement_title("关于收到监管函的公告") == "hard"


def test_weak_index_still_shows_daily_picks():
    gates = [
        bp.Gate("index_ma20", "指数", False, "弱市", hard=False),
        bp.Gate("universe", "覆盖", True, "ok", hard=True),
        bp.Gate("breadth_g1", "广度", True, "G1=+0.1", hard=False),
    ]
    fake_pick = bp.Pick("600001.SH", "测试", 10, 0.012, -0.08, 1.3, 20, 0.5, ["x"])
    payload = bp.build_payload(
        as_of=date(2026, 11, 3),
        gates=gates,
        picks=[fake_pick],
        funnel={"raw": 1},
        overlays=bp.OverlayStatus(),
        g1=0.1,
    )
    assert payload["verdict"] == "open"
    assert "今日深跌抄底" in payload["headline"]
    assert payload["picks"][0]["symbol"] == "600001.SH"
    assert payload["hold_trading_days"] == 20
    assert payload["review_trading_days"] == 20
    assert payload["take_profit"] == 0.05
    assert "2026-11-03" in payload["signal_note"]
    assert "开盘买" in payload["signal_note"]
    assert "1.5%" in payload["signal_note"]
    assert payload["open_gap_skip"] == 0.015
    assert "E1" in payload["honesty"]["why_not_next_day"]
    assert "次日开盘" in payload["honesty"]["why_not_next_day"]
    blob = str(payload["honesty"])
    assert "81.1" not in blob
    assert "2.40" not in blob
    assert "67.6" not in blob
    assert payload["honesty"]["evidence"]["path"] == "docs/e1-evidence.md"
    assert payload["honesty"]["evidence"]["sample_start"] == "2026-02-11"
    assert "不是 90%" in payload["honesty"]["headline"]
    assert payload["honesty"]["not_a_guarantee"] is True
    assert payload["honesty"]["rise_causes"]
    assert any(c["use"] == "keep" for c in payload["honesty"]["rise_causes"])
    assert any(c["use"] == "drop" for c in payload["honesty"]["rise_causes"])
    assert any("止盈" in line for line in payload["how_to_use"])


def test_universe_fail_hides_picks_and_avoids_90_claim():
    gates = [
        bp.Gate("index_ma20", "指数", True, "ok", hard=False),
        bp.Gate("universe", "覆盖", False, "不足", hard=True),
    ]
    fake_pick = bp.Pick("600001.SH", "测试", 10, 0.012, -0.08, 1.3, 20, 0.5, ["x"])
    payload = bp.build_payload(
        as_of=date(2026, 11, 3),
        gates=gates,
        picks=[fake_pick],
        funnel={"raw": 1},
        overlays=bp.OverlayStatus(),
        g1=0.1,
    )
    assert payload["verdict"] == "closed"
    assert payload["picks"] == []
    assert "不是 90%" in payload["honesty"]["headline"]


def test_open_gate_with_no_hits_is_no_candidates():
    gates = [
        bp.Gate("index_ma20", "指数", True, "ok"),
        bp.Gate("universe", "覆盖", True, "ok"),
    ]
    payload = bp.build_payload(
        as_of=date(2026, 11, 3),
        gates=gates,
        picks=[],
        funnel={"raw": 300},
        overlays=bp.OverlayStatus(),
        g1=0.3,
    )
    assert payload["verdict"] == "no_candidates"
    assert payload["headline"] == "今日无合格票"


def test_universe_gate_fail_closed():
    gates = bp.evaluate_gates(
        index_closes=[float(x) for x in range(80, 100)],
        universe_n=50,
        up=30,
        down=20,
        flat=0,
    )
    hard = [g for g in gates if g.hard]
    assert any(g.id == "universe" and g.ok is False for g in hard)
    assert bp.verdict_from_gates(gates, 3)[0] == "closed"


def test_overlay_h11_and_buyback_from_csv(tmp_path: Path):
    imported = tmp_path / "imported"
    imported.mkdir()
    (imported / "announcements.csv").write_text(
        "code,day,title,kind\n"
        "600111,2026-10-20,收到行政处罚事先告知书,other\n"
        "600111,2026-10-21,资金占用情况表,other\n"
        "600222,2026-10-20,投资者关系活动记录,ir_activity\n",
        encoding="utf-8",
    )
    (imported / "buyback_live.csv").write_text(
        "code,day,name,progress,amount_lower\n"
        "600222,2026-10-15,测试回购,006,1000000\n",
        encoding="utf-8",
    )
    bp._OVERLAY_CACHE.update(sig=None, ann=None, buyback=None)
    buyback, h11, overlays = bp.overlay_sets(tmp_path, date(2026, 11, 1))
    assert overlays.announcements is True
    assert overlays.buyback is True
    assert "600111.SH" in h11
    assert "情况表" not in h11.get("600111.SH", "")
    assert "600222.SH" in buyback
    assert "600222.SH" not in h11


def test_csi300_panic_allows_e1():
    closes = [100.0] * 59 + [90.0]
    band, detail = bp.csi300_band(closes)
    assert band == "PANIC"
    assert "恐慌" in detail
    gates = bp.evaluate_gates(
        index_closes=[90.0] * 20,
        universe_n=300,
        up=100,
        down=180,
        flat=20,
        csi_closes=closes,
    )
    csi = next(g for g in gates if g.id == "csi300_band")
    assert csi.ok is True
    assert csi.hard is False


def test_csi300_strong_blocks_e1_but_not_hard_close():
    closes = list(range(40, 100))
    band, detail = bp.csi300_band([float(x) for x in closes])
    assert band == "STRONG"
    assert "强势" in detail
    gates = bp.evaluate_gates(
        index_closes=[float(x) for x in range(80, 100)],
        universe_n=300,
        up=200,
        down=80,
        flat=20,
        csi_closes=[float(x) for x in closes],
    )
    csi = next(g for g in gates if g.id == "csi300_band")
    assert csi.ok is False
    assert csi.hard is False
    assert bp.verdict_from_gates(gates, 0)[0] == "no_candidates"


def test_e1_selects_deep_drawdown_with_volume():
    rows = [
        {
            "symbol": "600001.SH", "name": "深跌放量", "close": 12.0,
            "change_pct": -0.02, "dd60": -0.35, "amt_q": 10.0,
            "vol_ratio_5d": 1.8, "r20": -0.20, "dnd20": 0, "volume": 1e6,
        },
        {
            "symbol": "600002.SH", "name": "深跌无量", "close": 12.0,
            "change_pct": -0.02, "dd60": -0.40, "amt_q": 8.0,
            "vol_ratio_5d": 0.7, "r20": -0.22, "dnd20": 0, "volume": 1e6,
        },
        {
            "symbol": "600003.SH", "name": "热门额", "close": 12.0,
            "change_pct": -0.02, "dd60": -0.36, "amt_q": 80.0,
            "vol_ratio_5d": 2.0, "r20": -0.18, "dnd20": 0, "volume": 1e6,
        },
        {
            "symbol": "300001.SZ", "name": "创业板", "close": 12.0,
            "change_pct": -0.02, "dd60": -0.40, "amt_q": 5.0,
            "vol_ratio_5d": 2.0, "r20": -0.25, "dnd20": 0, "volume": 1e6,
        },
    ]
    picks, funnel = bp.select_e1_snipers(rows)
    assert [p.symbol for p in picks] == ["600001.SH"]
    assert picks[0].dd60 == pytest.approx(-0.35)
    assert picks[0].amt_q == pytest.approx(10.0)
    assert funnel["e1_picks"] == 1
    assert any("深跌" in r for r in picks[0].reasons)
    assert any("+5%" in r for r in picks[0].reasons)
    assert not any("回购" in r for r in picks[0].reasons)


def test_e1_h11_veto():
    rows = [{
        "symbol": "600010.SH", "name": "有雷", "close": 10.0,
        "change_pct": -0.01, "dd60": -0.40, "amt_q": 5.0,
        "vol_ratio_5d": 1.7, "r20": -0.2, "dnd20": 0, "volume": 1e6,
    }]
    picks, funnel = bp.select_e1_snipers(rows, h11={"600010.SH": "立案调查"})
    assert picks == []
    assert funnel["h11_pass"] == 0



def test_g1_text_is_not_market_strength():
    gates = bp.evaluate_gates(
        index_closes=[90.0] * 20,
        universe_n=300,
        up=200,
        down=80,
        flat=20,
    )
    g1 = next(g for g in gates if g.id == "breadth_g1")
    assert g1.label == "个股涨跌家数"
    assert "不是大盘强弱" in g1.detail
    assert "偏强" not in g1.detail


def test_to_cn_symbol_from_legacy_codes():
    assert bp.to_cn_symbol("600000") == "600000.SH"
    assert bp.to_cn_symbol("000001") == "000001.SZ"
    assert bp.to_cn_symbol("sh600000") == "600000.SH"


