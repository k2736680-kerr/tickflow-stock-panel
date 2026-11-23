# ruff: noqa: RUF001, RUF002, RUF003
"""Beginner pick engine: E1 dip-sniper from the verified gupiaotuijian rule.

Only WEAK/PANIC CSI300 vs MA60. Take-profit +5% or max 20 days.
Does not claim a 90% win rate and does not auto-trade.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from app.markets import normalize_symbol
from app.price_limits import is_risk_warning_name

logger = logging.getLogger(__name__)

INDEX_SYMBOL = "000001.SH"
CSI300_SYMBOL = "000300.SH"
HOLD_TRADING_DAYS = 20
REVIEW_TRADING_DAYS = 20
TOP_N = 1
MIN_UNIVERSE = 200
MIN_PRICE = 3.0
MAX_PRICE = 26.99
TAKE_PROFIT = 0.05
DD60_MAX = -0.30
DD60_FLOOR = -0.50
AMT_Q_MAX = 20.0
VOLR_MIN = 1.5
DND20_MAX = 1
E1_OK_BANDS = ("PANIC", "WEAK")
E1_LOOKBACK_DATES = 100
OPEN_GAP_SKIP = 0.015
BUYBACK_LOOKBACK_DAYS = 60
H11_LOOKBACK_DAYS = 60
MAIN_PREFIX = ("600", "601", "603", "605", "000", "001", "002", "003")
EVIDENCE_REF = {
    "id": "e1-local-replay-2026-02-11-2026-09-28",
    "sample_start": "2026-02-11",
    "sample_end": "2026-09-28",
    "path": "docs/e1-evidence.md",
    "ledger": "data/user_data/tickflow.db",
    "note": "买入当天收盘高于开盘不是高命中口径。能卖掉的高命中，是可卖日起 20 日内摸到买入价 +5%。",
    "replay": {
        "computed_on": "2026-11-07",
        "sample_start": "2026-02-11",
        "sample_end": "2026-09-28",
        "bought": 164,
        "same_day_close_up": 0.585,
        "same_day_high_plus_1pct": 0.774,
        "sellable_plus_5pct_20d": 0.817,
    },
}

# trading-agent H11：强负面无条件否决；其余硬负面若命中披露附件体裁则降级。
NEG_HARD = (
    "立案调查", "被调查", "行政处罚", "违规担保", "资金占用", "大额减持",
    "亏损", "预亏", "业绩预减", "终止上市", "退市整理", "强制退市", "冻结",
    "失信", "被执行", "问询函", "监管函", "警示函",
)
STRONG_NEG = (
    "立案调查", "被调查", "行政处罚", "违规担保", "终止上市",
    "退市整理", "强制退市", "失信", "被执行",
)
DOWN_CTX = (
    "汇总表", "情况表", "专项说明", "专项报告", "专项核查", "鉴证", "审计报告",
    "独立董事", "保荐", "摘要", "会计师", "回复", "撤销退市风险警示",
    "撤销其他风险警示", "摘帽", "业绩说明会", "募集资金",
)

HONESTY = {
    "not_a_guarantee": True,
    "headline": "高胜率来自止盈规则，不是 90% 明天上涨。",
    "why_not_next_day": (
        "今日名单只接 E1 深跌抄底。"
        "条件：距 60 日高点回撤 30%～50%，成交额分位后 20%，价格 3～26.99 元，量比 ≥1.5，主板非 ST。"
        "只在沪深300相对 60 日线处于弱势或恐慌时做（偏离 ≤−1%）。震荡和强势空仓。"
        "买法：次日开盘买。开盘已经涨超 1.5% 不追。买入当天卖不掉。"
        "从买入后的下一交易日挂 +5%，碰到就卖，碰不到最多拿 20 个交易日。"
        "买入当天收盘高于开盘不是这套规则的高命中。数字见证据记录里的重放。"
    ),
    "historical_note": (
        "拐头硬凑每天有名单、主线补涨、强势时照样抄底，都已经停用。"
        "样本和结论写在证据记录里，本页不重复数字。"
    ),
    "live_note": (
        "沪深300不弱时名单会空，这是规则，不是坏了。"
        "没有 60 日行情时才是数据没准备好。"
        "每次名单单独记进复盘账本，下一交易日收盘后自动对照涨跌。"
        "已结算且有名单的交易日不满 40 天，只记不改规则。"
        "满 40 天也要先写改哪条阈值、用多少样本、预期影响，同意后才改代码。"
    ),
    "evidence": EVIDENCE_REF,
    "rise_causes": [
        {
            "cause": "E1 深跌抄底：回撤 30%～50% + 成交额后20% + 只在沪深300弱势/恐慌做 + 可卖日起 +5%止盈",
            "result": "保留。买入当天收盘必红不是这套口径。",
            "use": "keep",
        },
        {
            "cause": "每天硬凑 8 只主板缩量拐头",
            "result": "已停用。每天都有名单，历史没有稳定优势。",
            "use": "drop",
        },
        {
            "cause": "看板主线里买 0～4% 补涨",
            "result": "已停用。历史接近一半一半。",
            "use": "drop",
        },
        {
            "cause": "E1 在沪深300强势时照样抄底",
            "result": "已停用。强市不做。",
            "use": "drop",
        },
        {
            "cause": "硬负面公告（立案调查、退市、监管函）",
            "result": "用来否决，不让这些票进名单。",
            "use": "keep",
        },
        {
            "cause": "涨停 / 连板 / 资金流红绿柱 / 倒推上涨原因再搜",
            "result": "已停用。分不出明天谁涨。",
            "use": "drop",
        },
    ],
    "what_we_kept": [
        "E1 深跌 + 成交额后 20% + 价格上限 26.99",
        "只在沪深300弱势/恐慌出票，强势空仓",
        "盘中 +5% 止盈，最多 20 日，不设固定止损",
        "硬负面否决，每天最多 1 只",
    ],
    "what_we_dropped": [
        "每天硬凑拐头或主线补涨（约 50%）",
        "指数跌破 20 日线当空仓开关（改看沪深300相对 60 日线）",
        "15 道实时闸门、资金流、AI 荐股、一键跟单",
        "把集合胜率写成单票 90%",
    ],
}


@dataclass
class Gate:
    id: str
    label: str
    ok: bool
    detail: str
    hard: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "ok": self.ok,
            "detail": self.detail,
            "hard": self.hard,
        }


@dataclass
class OverlayStatus:
    announcements: bool = False
    buyback: bool = False
    announcement_rows: int = 0
    buyback_rows: int = 0
    note: str = "未导入外部研究库，仅用本机行情。"

    def as_dict(self) -> dict[str, Any]:
        return {
            "announcements": self.announcements,
            "buyback": self.buyback,
            "announcement_rows": self.announcement_rows,
            "buyback_rows": self.buyback_rows,
            "note": self.note,
        }


@dataclass
class Pick:
    symbol: str
    name: str
    close: float | None
    change_pct: float | None
    momentum_20d: float | None
    vol_ratio_5d: float | None
    mktcap_yi: float | None
    score: float
    reasons: list[str] = field(default_factory=list)
    theme: str | None = None
    dd60: float | None = None
    amt_q: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "close": _round(self.close, 2),
            "change_pct": _round(self.change_pct, 4),
            "momentum_20d": _round(self.momentum_20d, 4),
            "vol_ratio_5d": _round(self.vol_ratio_5d, 3),
            "mktcap_yi": _round(self.mktcap_yi, 1),
            "score": _round(self.score, 4),
            "reasons": self.reasons,
            "theme": self.theme,
            "dd60": _round(self.dd60, 4),
            "amt_q": _round(self.amt_q, 2),
        }


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def is_main_board(symbol: str) -> bool:
    """沪深主板（含原中小板）。创业板 / 科创板 / 北交所不进小白池。"""
    code = str(symbol).split(".", 1)[0].zfill(6)
    return code.startswith(MAIN_PREFIX)


def compute_g1(up: int, down: int, flat: int) -> float | None:
    total = up + down + flat
    if total <= 0:
        return None
    return (up - down) / total


def index_above_ma20(closes: list[float]) -> tuple[bool, str]:
    """上证收盘是否在 MA20 上方。只当天气标签。"""
    clean = [float(x) for x in closes if x is not None]
    if len(clean) < 20:
        return False, f"指数 K 线不足 20 根（现有 {len(clean)} 根），弱市标记未知"
    price = clean[-1]
    ma20 = sum(clean[-20:]) / 20.0
    if price > ma20:
        return True, f"上证 {price:.2f} > MA20 {ma20:.2f}（强市标签）"
    return False, f"上证 {price:.2f} ≤ MA20 {ma20:.2f}（弱市标签，不因此空仓）"


def state_of_csi300(dev: float | None) -> str | None:
    if dev is None:
        return None
    if dev <= -0.04:
        return "PANIC"
    if dev <= -0.01:
        return "WEAK"
    if dev < 0.02:
        return "NEUT"
    return "STRONG"


def csi300_band(closes: list[float]) -> tuple[str | None, str]:
    """沪深300 相对 MA60 的状态。E1 只在 WEAK/PANIC 做。"""
    clean = [float(x) for x in closes if x is not None]
    if len(clean) < 60:
        return None, f"沪深300 不足 60 根（现有 {len(clean)} 根），不能判断强弱"
    price = clean[-1]
    ma60 = sum(clean[-60:]) / 60.0
    if ma60 <= 0:
        return None, "沪深300 均线无效"
    dev = price / ma60 - 1.0
    band = state_of_csi300(dev)
    label = {"PANIC": "恐慌", "WEAK": "弱势", "NEUT": "震荡", "STRONG": "强势"}.get(band or "", band or "")
    return band, f"沪深300 {price:.2f} / MA60 {ma60:.2f} 偏离 {dev:+.1%}（{label}）"


def classify_announcement_title(title: str) -> str | None:
    """返回 hard / None。soft 与 info 不否决（避免 15 门叠死）。"""
    text = str(title or "")
    if not text:
        return None
    strong = [k for k in STRONG_NEG if k in text]
    if strong:
        return "hard"
    hard_hits = [k for k in NEG_HARD if k in text]
    if not hard_hits:
        return None
    if any(k in text for k in DOWN_CTX):
        return None
    return "hard"


def to_cn_symbol(code: str) -> str:
    raw = str(code or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith(("sh", "sz", "bj")) and "." not in raw:
        return normalize_symbol(raw)
    if raw.isdigit() or raw.endswith((".SH", ".SZ", ".BJ", ".sh", ".sz", ".bj")):
        return normalize_symbol(raw)
    return normalize_symbol(raw)


def evaluate_gates(
    *,
    index_closes: list[float] | None,
    universe_n: int,
    up: int,
    down: int,
    flat: int,
    csi_closes: list[float] | None = None,
) -> list[Gate]:
    gates: list[Gate] = []
    if not index_closes:
        gates.append(Gate("index_ma20", "指数在 20 日线上方", False, "没有指数行情，弱市标记未知", hard=False))
    else:
        ok, detail = index_above_ma20(index_closes)
        gates.append(Gate("index_ma20", "指数在 20 日线上方", ok, detail, hard=False))

    if csi_closes is not None:
        if not csi_closes:
            gates.append(Gate("csi300_band", "沪深300弱势/恐慌", False, "没有沪深300，不能做深跌抄底", hard=True))
        else:
            band, detail = csi300_band(csi_closes)
            e1_ok = band in E1_OK_BANDS
            gates.append(Gate(
                "csi300_band",
                "沪深300弱势/恐慌",
                e1_ok,
                detail,
                hard=band is None,
            ))

    uni_ok = universe_n >= MIN_UNIVERSE
    gates.append(Gate(
        "universe",
        "行情覆盖足够",
        uni_ok,
        f"可交易样本 {universe_n} 只" + ("" if uni_ok else f"（少于 {MIN_UNIVERSE}，数据不足）"),
    ))

    g1 = compute_g1(up, down, flat)
    if g1 is None:
        g1_text = "涨跌家数未知，只作参考、不否决"
        g1_ok = True
    else:
        g1_ok = True
        tone = "上涨家数多于下跌" if g1 >= 0.20 else ("下跌家数更多" if g1 < 0 else "涨跌家数接近")
        g1_text = f"G1={g1:+.3f}（{tone}，只看个股家数，不是大盘强弱）"
    gates.append(Gate("breadth_g1", "个股涨跌家数", g1_ok, g1_text, hard=False))
    return gates


def _mktcap_yi(close: float | None, float_shares: float | None) -> float | None:
    if close is None or float_shares is None:
        return None
    try:
        if close <= 0 or float_shares <= 0:
            return None
        return float(close) * float(float_shares) / 1e8
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number



def verdict_from_gates(gates: list[Gate], pick_n: int, *, empty_headline: str | None = None) -> tuple[str, str]:
    hard_fail = next((g for g in gates if g.hard and not g.ok), None)
    if hard_fail:
        return "closed", "今日不买"
    if pick_n <= 0:
        return "no_candidates", empty_headline or "今日无合格票"
    return "open", f"今日深跌抄底 {pick_n} 只"


def build_payload(
    *,
    as_of: date | None,
    gates: list[Gate],
    picks: list[Pick],
    funnel: dict[str, int],
    overlays: OverlayStatus,
    g1: float | None,
    themes: list[dict[str, Any]] | None = None,
    pick_mode: str = "e1",
    empty_headline: str | None = None,
    csi_band: str | None = None,
) -> dict[str, Any]:
    status, headline = verdict_from_gates(
        gates,
        len(picks) if all(g.ok for g in gates if g.hard) else 0,
        empty_headline=empty_headline,
    )
    show_picks = status == "open"
    if as_of:
        signal_note = (
            f"按 {as_of.isoformat()} 收盘选出 · 下一交易日开盘买（涨超 "
            f"{OPEN_GAP_SKIP * 100:.1f}% 不追）· 买入当天卖不掉 · 下一天起挂 "
            f"+{TAKE_PROFIT * 100:.0f}%，否则最多 {HOLD_TRADING_DAYS} 日"
        )
    else:
        signal_note = "还没有信号日"
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "signal_note": signal_note,
        "verdict": status,
        "headline": headline,
        "hold_trading_days": HOLD_TRADING_DAYS,
        "review_trading_days": REVIEW_TRADING_DAYS,
        "open_gap_skip": OPEN_GAP_SKIP,
        "take_profit": TAKE_PROFIT,
        "index_symbol": INDEX_SYMBOL,
        "g1": _round(g1, 4),
        "gates": [g.as_dict() for g in gates],
        "picks": [p.as_dict() for p in picks] if show_picks else [],
        "themes": themes or [],
        "pick_mode": pick_mode,
        "csi_band": csi_band,
        "funnel": funnel,
        "overlays": overlays.as_dict(),
        "honesty": HONESTY,
        "how_to_use": [
            "只买名单里的这一只。没有名单就空仓。",
            "沪深300不弱（震荡/强势）时名单会空：今日空仓，不要回头去买拐头或补涨凑数。",
            f"次日开盘买。开盘已经涨超 {OPEN_GAP_SKIP * 100:.1f}% 的不要追。",
            f"买入当天卖不掉。从下一交易日挂 +{TAKE_PROFIT * 100:.0f}% 止盈，碰到就走。碰不到就拿到第 {HOLD_TRADING_DAYS} 个交易日，中途不加仓、不设固定止损。",
            "出现立案调查 / 退市 / 监管函，立刻拿掉。",
        ],
    }


_OVERLAY_CACHE: dict[str, Any] = {
    "sig": None, "ann": None, "buyback": None, "ann_n": 0, "bb_n": 0,
}


def imported_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "imported"


def _file_sig(path: Path) -> tuple[str, int, int]:
    try:
        st = path.stat()
        return (path.name, st.st_mtime_ns, st.st_size)
    except OSError:
        return (path.name, 0, 0)


def overlay_status_from_files(data_dir: Path) -> OverlayStatus:
    """只看文件是否存在, 不读 46MB 公告库 (空行情时也要能秒回)。"""
    root = imported_dir(data_dir)
    ann_path = root / "announcements.csv"
    bb_path = root / "buyback_live.csv"
    ann_ok = ann_path.exists() and ann_path.stat().st_size > 0
    bb_ok = bb_path.exists() and bb_path.stat().st_size > 0
    parts = []
    if ann_ok:
        parts.append("公告库已拷贝 (H11 否决)")
    if bb_ok:
        parts.append("回购清单已拷贝 (加分)")
    note = (
        "已接入：" + "，".join(parts) + "。源目录里那十几万缓存文件没有拷贝，也不需要。"
        if parts else
        "未导入外部研究库，仅用本机行情。删除源目录前请确认 data/imported 已拷贝。"
    )
    return OverlayStatus(
        announcements=ann_ok,
        buyback=bb_ok,
        announcement_rows=0,
        buyback_rows=0,
        note=note,
    )


def _hard_negative_mask(titles: pl.Expr) -> pl.Expr:
    text = titles.fill_null("")
    strong = pl.any_horizontal([text.str.contains(k, literal=True) for k in STRONG_NEG])
    hard = pl.any_horizontal([text.str.contains(k, literal=True) for k in NEG_HARD])
    ctx = pl.any_horizontal([text.str.contains(k, literal=True) for k in DOWN_CTX])
    return strong | (hard & ~ctx)


def _load_overlay_frames(data_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame, OverlayStatus]:
    root = imported_dir(data_dir)
    ann_path = root / "announcements.csv"
    bb_path = root / "buyback_live.csv"
    sig = (_file_sig(ann_path), _file_sig(bb_path))
    cached = _OVERLAY_CACHE
    if cached["sig"] == sig and cached["ann"] is not None and cached["buyback"] is not None:
        overlays = OverlayStatus(
            announcements=cached["ann_n"] > 0,
            buyback=cached["bb_n"] > 0,
            announcement_rows=cached["ann_n"],
            buyback_rows=cached["bb_n"],
            note=_overlay_note(cached["ann_n"], cached["bb_n"]),
        )
        return cached["ann"], cached["buyback"], overlays

    ann = pl.DataFrame()
    buyback = pl.DataFrame()
    ann_n = 0
    bb_n = 0
    if ann_path.exists():
        try:
            raw = pl.read_csv(
                ann_path,
                columns=["code", "day", "title"],
                schema_overrides={"code": pl.Utf8, "day": pl.Utf8, "title": pl.Utf8},
            )
            ann_n = len(raw)
            if not raw.is_empty():
                ann = raw.filter(_hard_negative_mask(pl.col("title")))
        except Exception as exc:
            logger.warning("announcements.csv 读取失败: %s", exc)
    if bb_path.exists():
        try:
            buyback = pl.read_csv(
                bb_path,
                columns=["code", "day"],
                schema_overrides={"code": pl.Utf8, "day": pl.Utf8},
            )
            bb_n = len(buyback)
        except Exception as exc:
            logger.warning("buyback_live.csv 读取失败: %s", exc)
    cached.update(sig=sig, ann=ann, buyback=buyback, ann_n=ann_n, bb_n=bb_n)
    overlays = OverlayStatus(
        announcements=ann_n > 0,
        buyback=bb_n > 0,
        announcement_rows=ann_n,
        buyback_rows=bb_n,
        note=_overlay_note(ann_n, bb_n),
    )
    return ann, buyback, overlays


def _overlay_note(ann_n: int, bb_n: int) -> str:
    parts = []
    if ann_n:
        parts.append(f"公告库 {ann_n} 条 (H11 否决)")
    if bb_n:
        parts.append(f"回购清单 {bb_n} 条 (只记录，不进名单)")
    if not parts:
        return "未导入外部研究库，仅用本机行情。删除源目录前请确认 data/imported 已拷贝。"
    return "已接入：" + "，".join(parts) + "。源目录里那十几万缓存文件没有拷贝，也不需要。"


def overlay_sets(
    data_dir: Path,
    as_of: date,
) -> tuple[set[str], dict[str, str], OverlayStatus]:
    """返回 (回购代码集合, 硬负面 symbol→标题, 覆盖状态)。"""
    ann, buyback, overlays = _load_overlay_frames(data_dir)
    start = (as_of - timedelta(days=H11_LOOKBACK_DAYS)).isoformat()
    end = as_of.isoformat()
    h11: dict[str, str] = {}
    if not ann.is_empty() and {"code", "day", "title"} <= set(ann.columns):
        window = ann.filter((pl.col("day") >= start) & (pl.col("day") <= end))
        for rec in window.select(["code", "title"]).iter_rows(named=True):
            symbol = to_cn_symbol(str(rec.get("code") or ""))
            if symbol and symbol not in h11:
                h11[symbol] = str(rec.get("title") or "")[:80]
    buyback_syms: set[str] = set()
    bb_start = (as_of - timedelta(days=BUYBACK_LOOKBACK_DAYS)).isoformat()
    if not buyback.is_empty() and {"code", "day"} <= set(buyback.columns):
        window = buyback.filter((pl.col("day") >= bb_start) & (pl.col("day") <= end))
        for code in window["code"].to_list():
            symbol = to_cn_symbol(str(code or ""))
            if symbol:
                buyback_syms.add(symbol)
    return buyback_syms, h11, overlays


def _index_closes(repo: Any, as_of: date, symbol: str = INDEX_SYMBOL, lookback_days: int = 80) -> list[float]:
    start = as_of - timedelta(days=lookback_days)
    try:
        df = repo.get_index_daily(symbol, start, as_of, columns=["date", "close"])
    except Exception as exc:
        logger.warning("读取指数失败 %s: %s", symbol, exc)
        return []
    if df is None or df.is_empty() or "close" not in df.columns:
        return []
    ordered = df.sort("date") if "date" in df.columns else df
    closes: list[float] = []
    for value in ordered["close"].to_list():
        number = _num(value)
        if number is not None:
            closes.append(number)
    return closes



def compute_e1_features(hist: pl.DataFrame) -> pl.DataFrame:
    """给历史日 K 算 dd60 / 成交额分位 / 量比 / 近 20 日跌停天数。"""
    if hist.is_empty() or "symbol" not in hist.columns or "close" not in hist.columns:
        return pl.DataFrame()
    work = hist
    if "date" not in work.columns:
        return pl.DataFrame()
    if work.schema.get("date") != pl.Date:
        work = work.with_columns(pl.col("date").cast(pl.Date, strict=False))
    work = work.sort(["symbol", "date"])
    high_col = "high" if "high" in work.columns else "close"
    amount_col = "amount" if "amount" in work.columns else None
    volume_col = "volume" if "volume" in work.columns else None
    exprs: list[pl.Expr] = [
        (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("ret1"),
        (pl.col("close") / pl.col("close").shift(20).over("symbol") - 1).alias("r20"),
        pl.col(high_col).rolling_max(window_size=60, min_samples=60).over("symbol").alias("hi60"),
    ]
    if amount_col:
        exprs.append(
            pl.col(amount_col).rolling_mean(window_size=20, min_samples=20).over("symbol").alias("amt20")
        )
    if volume_col:
        exprs.append(
            pl.col(volume_col).shift(1).rolling_mean(window_size=5, min_samples=5).over("symbol").alias("vol5")
        )
    work = work.with_columns(exprs)
    more: list[pl.Expr] = [
        (pl.col("ret1") <= -0.095).cast(pl.Int8).fill_null(0)
        .rolling_sum(window_size=20, min_samples=20)
        .over("symbol")
        .alias("dnd20"),
        (pl.col("close") / pl.col("hi60") - 1).alias("dd60"),
    ]
    if "amt20" in work.columns:
        more.append(pl.col("amt20").log().alias("logamt"))
    if volume_col and "vol5" in work.columns:
        more.append((pl.col(volume_col) / pl.col("vol5")).alias("vol_ratio_5d"))
    work = work.with_columns(more)
    if "logamt" in work.columns:
        ranked = work.filter(pl.col("logamt").is_not_null()).with_columns(
            (
                100.0
                * (pl.col("logamt").rank("average").over("date") - 1)
                / (pl.len().over("date") - 1).clip(lower_bound=1)
            ).alias("amt_q")
        )
        work = work.join(ranked.select(["symbol", "date", "amt_q"]), on=["symbol", "date"], how="left")
    if "change_pct" not in work.columns and "ret1" in work.columns:
        work = work.with_columns(pl.col("ret1").alias("change_pct"))
    if "momentum_20d" not in work.columns and "r20" in work.columns:
        work = work.with_columns(pl.col("r20").alias("momentum_20d"))
    return work


def select_e1_snipers(
    rows: list[dict[str, Any]],
    *,
    h11: dict[str, str] | None = None,
    top_n: int = TOP_N,
) -> tuple[list[Pick], dict[str, int]]:
    """E1：深跌 + 成交额后 20% + 放量。只返回形态命中，状态闸门在调用方。"""
    h11 = h11 or {}
    funnel = {
        "raw": len(rows), "main_board": 0, "not_st": 0, "price": 0,
        "dd60": 0, "amt_q": 0, "vol": 0, "h11_pass": 0, "e1_picks": 0,
    }
    scored: list[tuple[float, Pick]] = []
    for rec in rows:
        symbol = str(rec.get("symbol") or "")
        if not is_main_board(symbol):
            continue
        funnel["main_board"] += 1
        name = str(rec.get("name") or symbol)
        if is_risk_warning_name(name) or "退" in name:
            continue
        funnel["not_st"] += 1
        close = _num(rec.get("close"))
        if close is None or close < MIN_PRICE or close > MAX_PRICE:
            continue
        funnel["price"] += 1
        change = _num(rec.get("change_pct")) or 0.0
        if bool(rec.get("signal_limit_up")) or change >= 0.095:
            continue
        volume = _num(rec.get("volume"))
        if volume is not None and volume <= 0:
            continue
        dnd20 = _num(rec.get("dnd20"))
        if dnd20 is not None and dnd20 > DND20_MAX:
            continue
        dd60 = _num(rec.get("dd60"))
        if dd60 is None or dd60 > DD60_MAX or dd60 <= DD60_FLOOR:
            continue
        funnel["dd60"] += 1
        amt_q = _num(rec.get("amt_q"))
        if amt_q is None or amt_q > AMT_Q_MAX:
            continue
        funnel["amt_q"] += 1
        vol = _num(rec.get("vol_ratio_5d"))
        if vol is None or vol < VOLR_MIN:
            continue
        funnel["vol"] += 1
        if h11.get(symbol):
            continue
        funnel["h11_pass"] += 1
        r20 = _num(rec.get("r20"))
        if r20 is None:
            r20 = _num(rec.get("momentum_20d")) or 0.0
        key = dd60 * 0.6 + r20
        reasons = [
            f"距 60 日高点 {dd60 * 100:.1f}%（深跌还没修完）",
            f"成交额分位 {amt_q:.0f}（后 20%，不是热门额）",
            f"量比 {vol:.2f}（已经开始放量）",
            f"次日开盘买，涨超 {OPEN_GAP_SKIP * 100:.1f}% 不追",
            f"买入当天卖不掉。下一天起挂 +{TAKE_PROFIT * 100:.0f}%，否则最多 {HOLD_TRADING_DAYS} 日",
        ]
        scored.append((key, Pick(
            symbol=symbol,
            name=name,
            close=close,
            change_pct=change,
            momentum_20d=r20,
            vol_ratio_5d=vol,
            mktcap_yi=_mktcap_yi(close, _num(rec.get("float_shares"))),
            score=key,
            reasons=reasons,
            dd60=dd60,
            amt_q=amt_q,
        )))
    # 回撤更接近 30% 的排前面。后半段里只留这一只，比按跌得最深排前 6 更准。
    scored.sort(key=lambda item: item[0], reverse=True)
    picks = [item[1] for item in scored[:top_n]]
    funnel["e1_picks"] = len(picks)
    return picks, funnel


def _load_e1_history(repo: Any) -> tuple[pl.DataFrame, date | None]:
    """E1 回撤/成交额分位必须用日 K 分区，口径与本机回放一致。"""
    peek_fn = getattr(repo, "peek_recent_ohlc", None)
    if peek_fn is not None:
        try:
            hist, peeked = peek_fn(E1_LOOKBACK_DATES)
        except Exception as exc:
            logger.warning("日 K 分区读取失败: %s", exc)
            hist, peeked = pl.DataFrame(), None
        if hist is not None and not hist.is_empty():
            return hist, peeked
    latest, as_of = repo.get_enriched_latest()
    if latest is not None and not latest.is_empty() and as_of is not None:
        return latest, as_of
    return pl.DataFrame(), as_of



def _join_instruments(df: pl.DataFrame, repo: Any) -> pl.DataFrame:
    if df.is_empty():
        return df
    try:
        inst = repo.get_instruments_asset("stock")
    except Exception:
        return df
    if inst is None or inst.is_empty() or "symbol" not in inst.columns:
        return df
    cols = [c for c in ("symbol", "name", "float_shares", "total_shares", "region") if c in inst.columns]
    extra = [c for c in cols if c != "symbol" and c not in df.columns]
    if not extra:
        return df
    return df.join(inst.select(["symbol", *extra]), on="symbol", how="left")


def build_beginner_picks(repo: Any, data_dir: Path | None = None) -> dict[str, Any]:
    """主入口：读本机 enriched + 可选 imported 覆盖，返回 API 字典。"""
    data_dir = Path(data_dir) if data_dir is not None else Path(repo.store.data_dir)
    overlays = overlay_status_from_files(data_dir)
    try:
        hist, as_of = _load_e1_history(repo)
    except Exception as exc:
        logger.warning("enriched 读取失败: %s", exc)
        return build_payload(
            as_of=None,
            gates=[Gate("data", "本机行情", False, "行情还没准备好，请先到「数据」页同步")],
            picks=[],
            funnel={"raw": 0},
            overlays=overlays,
            g1=None,
        )
    if hist is None or hist.is_empty() or as_of is None:
        return build_payload(
            as_of=as_of if isinstance(as_of, date) else None,
            gates=[Gate("data", "本机行情", False, "还没有最新交易日数据，请先同步日 K")],
            picks=[],
            funnel={"raw": 0},
            overlays=overlays,
            g1=None,
        )

    hist = _join_instruments(hist, repo)
    if "region" in hist.columns:
        hist = hist.filter((pl.col("region") == "CN") | pl.col("region").is_null())
    if "symbol" in hist.columns:
        hist = hist.filter(
            pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ")
        )
        hist = hist.filter(pl.col("symbol").str.slice(0, 3).is_in(list(MAIN_PREFIX)))
    if "name" in hist.columns:
        upper = pl.col("name").fill_null("").str.to_uppercase()
        hist = hist.filter(~upper.str.contains("ST", literal=True))
        hist = hist.filter(~pl.col("name").fill_null("").str.contains("退", literal=True))
    feat = compute_e1_features(hist)
    if feat.is_empty() or "date" not in feat.columns:
        return build_payload(
            as_of=as_of,
            gates=[Gate("data", "本机行情", False, "历史不够，算不出 60 日回撤")],
            picks=[],
            funnel={"raw": 0},
            overlays=overlays,
            g1=None,
        )
    df = feat.filter(pl.col("date") == as_of)
    raw_n = len(df)
    change_col = "change_pct" if "change_pct" in df.columns else ("ret1" if "ret1" in df.columns else None)
    if change_col:
        up = int(df.filter(pl.col(change_col) > 0).height)
        down = int(df.filter(pl.col(change_col) < 0).height)
        flat = max(0, raw_n - up - down)
    else:
        up = down = flat = 0
    g1 = compute_g1(up, down, flat)
    index_closes = _index_closes(repo, as_of)
    csi_closes = _index_closes(repo, as_of, CSI300_SYMBOL, lookback_days=150)
    gates = evaluate_gates(
        index_closes=index_closes,
        universe_n=raw_n,
        up=up,
        down=down,
        flat=flat,
        csi_closes=csi_closes,
    )
    buyback: set[str] = set()
    h11: dict[str, str] = {}
    try:
        buyback, h11, overlays = overlay_sets(data_dir, as_of)
    except Exception as exc:
        logger.warning("imported 覆盖读取失败: %s", exc)

    rows = df.to_dicts()
    picks, funnel = select_e1_snipers(rows, h11=h11, top_n=TOP_N)
    band, _ = csi300_band(csi_closes) if csi_closes else (None, "")
    empty_headline = None
    if band not in E1_OK_BANDS:
        picks = []
        label = {"NEUT": "震荡", "STRONG": "强势"}.get(band or "", band or "未知")
        empty_headline = f"沪深300处于{label}，今日不做深跌抄底"
        pick_mode = "e1_skip_regime"
    elif picks:
        pick_mode = "e1"
    else:
        pick_mode = "e1_empty"
        empty_headline = "没有距60日高点跌超30%、成交额又在后20%、还在放量的主板票"
    _ = buyback  # 回购只作研究覆盖，不改变 E1 排序
    return build_payload(
        as_of=as_of,
        gates=gates,
        picks=picks,
        funnel=funnel,
        overlays=overlays,
        g1=g1,
        pick_mode=pick_mode,
        empty_headline=empty_headline,
        csi_band=band,
    )
