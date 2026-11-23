# ruff: noqa: RUF001
"""Live beginner-pick ledger: archive today's list, score it after the next close.

Keeps a separate analysis book. Does not rewrite E1 parameters.
"""
from __future__ import annotations

import csv
import json
import logging
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from app.services.beginner_picks import HOLD_TRADING_DAYS, OPEN_GAP_SKIP, TAKE_PROFIT

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_MAX_SESSIONS = 180
RULE_CHANGE_MIN_SETTLED_DAYS = 40


def _db_path(data_dir: Path) -> Path:
    path = Path(data_dir) / "user_data" / "tickflow.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _json_legacy_path(data_dir: Path) -> Path:
    return Path(data_dir) / "user_data" / "beginner_pick_log.json"


def _empty_log() -> dict[str, Any]:
    return {"purpose": "ledger", "auto_tune": False, "sessions": []}


def _connect(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(data_dir), timeout=10)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS beginner_sessions ("
        "as_of TEXT PRIMARY KEY NOT NULL,"
        "payload TEXT NOT NULL,"
        "updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS beginner_snapshots ("
        "as_of TEXT PRIMARY KEY NOT NULL,"
        "payload TEXT NOT NULL,"
        "archived_at TEXT NOT NULL)"
    )
    return conn


def _migrate_json_if_needed(data_dir: Path) -> None:
    json_path = _json_legacy_path(data_dir)
    if not json_path.exists():
        return
    try:
        conn = _connect(data_dir)
        try:
            n = conn.execute("SELECT COUNT(*) FROM beginner_sessions").fetchone()[0]
        finally:
            conn.close()
        if int(n or 0) == 0:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            sessions = raw.get("sessions") if isinstance(raw, dict) else None
            if isinstance(sessions, list) and sessions:
                save_log(data_dir, {"sessions": sessions})
    except (OSError, json.JSONDecodeError, sqlite3.Error) as exc:
        logger.warning("beginner pick json migrate skipped: %s", exc)
        return
    try:
        json_path.unlink()
        tmp = json_path.with_suffix(".json.tmp")
        if tmp.exists():
            tmp.unlink()
    except OSError as exc:
        logger.warning("beginner pick json leftover: %s", exc)


def load_log_readonly(data_dir: Path) -> dict[str, Any]:
    """Read the ledger. A missing file returns an empty log and creates nothing."""
    path = Path(data_dir) / "user_data" / "tickflow.db"
    if not path.exists():
        return _empty_log()
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            rows = conn.execute(
                "SELECT payload FROM beginner_sessions ORDER BY as_of"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("beginner pick db unreadable: %s", exc)
        return _empty_log()
    sessions: list[Any] = []
    for (payload,) in rows:
        try:
            item = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            sessions.append(item)
    return {
        "purpose": "ledger",
        "auto_tune": False,
        "sessions": sessions,
    }


def load_log(data_dir: Path) -> dict[str, Any]:
    _migrate_json_if_needed(data_dir)
    try:
        conn = _connect(data_dir)
        try:
            rows = conn.execute(
                "SELECT payload FROM beginner_sessions ORDER BY as_of"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("beginner pick db unreadable: %s", exc)
        return _empty_log()
    sessions: list[Any] = []
    for (payload,) in rows:
        try:
            item = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            sessions.append(item)
    return {
        "purpose": "ledger",
        "auto_tune": False,
        "sessions": sessions,
    }


def save_log(data_dir: Path, log: dict[str, Any]) -> None:
    sessions = [s for s in (log.get("sessions") or []) if isinstance(s, dict) and s.get("as_of")]
    sessions.sort(key=lambda s: str(s.get("as_of") or ""))
    if len(sessions) > _MAX_SESSIONS:
        sessions = sessions[-_MAX_SESSIONS:]
    now = datetime.now().isoformat(timespec="seconds")
    conn = _connect(data_dir)
    try:
        conn.execute("DELETE FROM beginner_sessions")
        conn.executemany(
            "INSERT INTO beginner_sessions(as_of, payload, updated_at) VALUES (?, ?, ?)",
            [
                (str(s["as_of"]), json.dumps(s, ensure_ascii=False), now)
                for s in sessions
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def archive_payload(payload: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    """Keep one session per signal date. Do not wipe already settled prices."""
    as_of = _as_date(payload.get("as_of"))
    if as_of is None:
        return load_log(data_dir)
    picks_in = payload.get("picks") or []
    fresh_picks = []
    for row in picks_in:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        fresh_picks.append({
            "symbol": str(row["symbol"]),
            "name": str(row.get("name") or row["symbol"]),
            "signal_close": _round(row.get("close"), 4),
            "change_pct": _round(row.get("change_pct"), 4),
            "momentum_20d": _round(row.get("momentum_20d"), 4),
            "vol_ratio_5d": _round(row.get("vol_ratio_5d"), 3),
            "mktcap_yi": _round(row.get("mktcap_yi"), 1),
            "score": _round(row.get("score"), 4),
            "dd60": _round(row.get("dd60"), 4),
            "amt_q": _round(row.get("amt_q"), 2),
            "reasons": list(row.get("reasons") or []),
            "theme": row.get("theme"),
        })
    meta = {
        "verdict": payload.get("verdict"),
        "pick_mode": payload.get("pick_mode"),
        "headline": payload.get("headline"),
        "csi_band": payload.get("csi_band"),
        "g1": payload.get("g1"),
        "funnel": payload.get("funnel") or {},
        "gates": payload.get("gates") or [],
    }
    with _LOCK:
        log = load_log(data_dir)
        sessions = log["sessions"]
        existing = next((s for s in sessions if s.get("as_of") == as_of.isoformat()), None)
        if existing is None:
            sessions.append({
                "as_of": as_of.isoformat(),
                "archived_at": datetime.now().isoformat(timespec="seconds"),
                **meta,
                "picks": fresh_picks,
            })
        else:
            existing.update(meta)
            old_by_sym = {
                p.get("symbol"): p for p in (existing.get("picks") or []) if isinstance(p, dict)
            }
            merged = []
            for row in fresh_picks:
                prev = old_by_sym.get(row["symbol"], {})
                merged.append({**prev, **row})
            existing["picks"] = merged
        sessions.sort(key=lambda s: s.get("as_of") or "")
        save_log(data_dir, log)
        return log


def _unique_dates(frame: pl.DataFrame) -> list[date]:
    if frame.is_empty() or "date" not in frame.columns:
        return []
    work = frame
    if work.schema.get("date") != pl.Date:
        work = work.with_columns(pl.col("date").cast(pl.Date, strict=False))
    out: list[date] = []
    for value in work["date"].unique().sort().to_list():
        day = _as_date(value)
        if day is not None:
            out.append(day)
    return out


def _bar_on(frame: pl.DataFrame, symbol: str, day: date) -> dict[str, Any] | None:
    if frame.is_empty():
        return None
    work = frame
    if work.schema.get("date") != pl.Date:
        work = work.with_columns(pl.col("date").cast(pl.Date, strict=False))
    hit = work.filter((pl.col("symbol") == symbol) & (pl.col("date") == day))
    if hit.is_empty():
        return None
    return hit.row(0, named=True)


def _f(row: dict[str, Any] | None, key: str) -> float | None:
    if not row:
        return None
    try:
        value = row.get(key)
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _settle_pick(
    pick: dict[str, Any],
    bars: pl.DataFrame,
    t1: date | None,
    later: list[date],
) -> dict[str, Any]:
    signal_close = _f(pick, "signal_close")
    if t1 is None:
        pick["status"] = "pending"
        return pick
    bar1 = _bar_on(bars, pick["symbol"], t1)
    buy_open = _f(bar1, "open")
    next_close = _f(bar1, "close")
    pick["buy_date"] = t1.isoformat()
    pick["buy_open"] = _round(buy_open, 4)
    pick["next_open"] = _round(buy_open, 4)
    pick["next_high"] = _round(_f(bar1, "high"), 4)
    pick["next_close"] = _round(next_close, 4)
    pick["next_close_date"] = t1.isoformat()
    gap = None
    if signal_close and buy_open and signal_close > 0:
        gap = buy_open / signal_close - 1.0
    pick["gap"] = _round(gap, 4)
    skipped = gap is not None and gap > OPEN_GAP_SKIP
    pick["skipped_gap"] = skipped
    vs_signal = None
    if signal_close and next_close and signal_close > 0:
        vs_signal = next_close / signal_close - 1.0
    pick["next_close_vs_signal"] = _round(vs_signal, 4)
    pick["correct_next_close"] = None if vs_signal is None else vs_signal > 0
    vs_buy = None
    if buy_open and next_close and buy_open > 0:
        vs_buy = next_close / buy_open - 1.0
    pick["next_close_vs_buy"] = _round(vs_buy, 4)
    pick["rose_after_buy"] = None if skipped or vs_buy is None else vs_buy > 0
    if skipped:
        pick["status"] = "skipped_gap"
        return pick
    if next_close is None:
        pick["status"] = "pending"
        return pick

    tp_price = buy_open * (1.0 + TAKE_PROFIT) if buy_open else None
    tp_hit = False
    tp_date = None
    sellable = later[:HOLD_TRADING_DAYS]
    for day in sellable:
        bar = _bar_on(bars, pick["symbol"], day)
        high = _f(bar, "high")
        if tp_price and high is not None and high >= tp_price:
            tp_hit = True
            tp_date = day.isoformat()
            break
    pick["tp_checked_days"] = len(sellable)
    pick["tp_hit"] = tp_hit if sellable else None
    pick["tp_date"] = tp_date
    if later:
        bar2 = _bar_on(bars, pick["symbol"], later[0])
        tplus1_close = _f(bar2, "close")
        pick["tplus1_date"] = later[0].isoformat()
        pick["tplus1_close"] = _round(tplus1_close, 4)
        tplus1_vs_buy = None
        if buy_open and tplus1_close and buy_open > 0:
            tplus1_vs_buy = tplus1_close / buy_open - 1.0
        pick["tplus1_vs_buy"] = _round(tplus1_vs_buy, 4)
    pick["status"] = "settled"
    return pick


def settle_log(repo: Any, data_dir: Path) -> dict[str, Any]:
    """Fill next-session prices for any archived list that already has bars."""
    with _LOCK:
        log = load_log(data_dir)
        sessions = log["sessions"]
        if not sessions:
            return log
        latest = None
        try:
            latest = repo.latest_daily_date()
        except Exception:
            latest = None
        if latest is None:
            return log

        symbols: list[str] = []
        min_as_of: date | None = None
        for session in sessions:
            as_of = _as_date(session.get("as_of"))
            if as_of is None:
                continue
            if min_as_of is None or as_of < min_as_of:
                min_as_of = as_of
            for pick in session.get("picks") or []:
                sym = pick.get("symbol") if isinstance(pick, dict) else None
                if sym:
                    symbols.append(str(sym))
        symbols = sorted(set(symbols))
        bars = pl.DataFrame()
        if symbols and min_as_of is not None:
            try:
                bars = repo.get_daily_batch(
                    symbols,
                    min_as_of + timedelta(days=1),
                    latest + timedelta(days=1),
                    columns=["symbol", "date", "open", "high", "close"],
                )
            except Exception:
                logger.exception("beginner pick review batch failed")
                bars = pl.DataFrame()
        if bars is None:
            bars = pl.DataFrame()

        calendar = _unique_dates(bars)
        for session in sessions:
            as_of = _as_date(session.get("as_of"))
            if as_of is None:
                continue
            after = [d for d in calendar if d > as_of]
            if not after and latest <= as_of:
                session["settled"] = False
                continue
            t1 = after[0] if after else None
            later = after[1:] if after else []
            if t1 is None and latest > as_of and not (session.get("picks") or []):
                session["buy_date"] = None
                session["settled"] = True
                session["next_close_win"] = 0
                session["next_close_n"] = 0
                continue
            picks = session.get("picks") or []
            scored = [_settle_pick(p, bars, t1, later) if isinstance(p, dict) else p for p in picks]
            session["picks"] = scored
            scored_dir = [
                p for p in scored
                if isinstance(p, dict) and p.get("correct_next_close") is not None
            ]
            wins = [p for p in scored_dir if p.get("correct_next_close") is True]
            session["buy_date"] = t1.isoformat() if t1 else None
            session["next_close_n"] = len(scored_dir)
            session["next_close_win"] = len(wins)
            if not picks:
                session["settled"] = t1 is not None or latest > as_of
            else:
                session["settled"] = bool(scored_dir) and all(
                    isinstance(p, dict) and p.get("status") in {"settled", "skipped_gap"}
                    for p in scored
                )
        save_log(data_dir, log)
        try:
            export_review(log, data_dir)
        except Exception:
            logger.exception("beginner pick review export failed")
        return log


def summarize(log: dict[str, Any]) -> dict[str, Any]:
    sessions = [s for s in log.get("sessions") or [] if isinstance(s, dict)]
    settled = [s for s in sessions if s.get("settled") and int(s.get("next_close_n") or 0) > 0]
    win = sum(int(s.get("next_close_win") or 0) for s in settled)
    n = sum(int(s.get("next_close_n") or 0) for s in settled)
    empty_days = sum(1 for s in sessions if s.get("pick_mode") == "e1_skip_regime")
    rose_n = 0
    rose_win = 0
    for session in sessions:
        for pick in session.get("picks") or []:
            if not isinstance(pick, dict) or pick.get("skipped_gap"):
                continue
            flag = pick.get("rose_after_buy")
            if flag is None:
                continue
            rose_n += 1
            if flag:
                rose_win += 1
    rate = (win / n) if n else None
    settled_days = len(settled)
    ready = settled_days >= RULE_CHANGE_MIN_SETTLED_DAYS
    gate_note = (
        f"已结算且有名单 {settled_days} 天，门槛 {RULE_CHANGE_MIN_SETTLED_DAYS} 天。"
        + (
            "样本够了也只出分析：写明改哪条阈值、用多少样本、预期影响，同意后才改代码。"
            if ready
            else "未满门槛，只记不改规则。"
        )
    )
    return {
        "days_logged": len(sessions),
        "days_settled": settled_days,
        "empty_days": empty_days,
        "picks_settled": n,
        "next_close_win": win,
        "next_close_win_rate": _round(rate, 4),
        "rose_after_buy_n": rose_n,
        "rose_after_buy_win": rose_win,
        "auto_tune": False,
        "rule_change": {
            "min_settled_days": RULE_CHANGE_MIN_SETTLED_DAYS,
            "settled_days": settled_days,
            "ready": ready,
            "changes_rules": False,
            "note": gate_note,
        },
        "note": (
            "这是单独账本：记下当时为什么推荐、次日开高低收、T+1 可卖日收盘。"
            "不自动改选股条件。"
            + gate_note
        ),
    }


REVIEW_MD_NAME = "beginner_pick_review.md"
REVIEW_CSV_NAME = "beginner_pick_review.csv"

_CSV_COLUMNS = [
    "as_of", "pick_mode", "csi_band", "symbol", "name",
    "signal_close", "buy_date", "buy_open", "next_high", "next_close",
    "next_close_vs_signal", "next_close_vs_buy", "correct_next_close",
    "tplus1_date", "tplus1_close", "tplus1_vs_buy",
    "gap", "skipped_gap", "tp_hit", "tp_date", "tp_checked_days", "status",
    "dd60", "amt_q", "vol_ratio_5d", "score", "change_pct", "reasons",
]


def _txt(value: Any) -> str:
    return "—" if value is None else str(value)


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _avg(values: list[float]) -> str:
    return _pct(sum(values) / len(values)) if values else "—"


def _reason_text(pick: dict[str, Any]) -> str:
    reasons = [str(r) for r in (pick.get("reasons") or []) if r]
    head = reasons[0] if reasons else ""
    parts = [head]
    if pick.get("dd60") is not None:
        parts.append(f"dd60={pick['dd60']}")
    if pick.get("amt_q") is not None:
        parts.append(f"额分位={pick['amt_q']}")
    return " / ".join(p for p in parts if p).replace("|", "／")


def export_review(log: dict[str, Any], data_dir: Path) -> dict[str, Path]:
    """把账本导出成给 AI 复盘用的 md + csv, 只读且不改选股规则。

    md 给人看/给 AI 直接读, csv 给后续量化分析做结构化输入。
    两个文件都落在 data/user_data/, 属本地数据, 不入库。
    """
    user_dir = Path(data_dir) / "user_data"
    user_dir.mkdir(parents=True, exist_ok=True)
    sessions = [s for s in (log.get("sessions") or []) if isinstance(s, dict)]
    stats = summarize(log)
    rows: list[dict[str, Any]] = []
    vs_signal: list[float] = []
    vs_buy: list[float] = []
    tp_n = 0
    tp_hit = 0
    tp_observing = 0

    for session in reversed(sessions):
        picks = [p for p in (session.get("picks") or []) if isinstance(p, dict)]
        if not picks:
            rows.append({
                "as_of": session.get("as_of"),
                "pick_mode": session.get("pick_mode"),
                "csi_band": session.get("csi_band"),
                "name": "（当日空仓 / 无名单）",
            })
            continue
        for pick in picks:
            a = _f(pick, "next_close_vs_signal")
            b = _f(pick, "next_close_vs_buy")
            if a is not None:
                vs_signal.append(a)
            if b is not None:
                vs_buy.append(b)
            if pick.get("tp_hit") is not None:
                tp_n += 1
                tp_hit += 1 if pick.get("tp_hit") else 0
                checked = pick.get("tp_checked_days")
                if (
                    pick.get("tp_hit") is False
                    and isinstance(checked, int)
                    and checked < HOLD_TRADING_DAYS
                ):
                    tp_observing += 1
            rows.append({
                "as_of": session.get("as_of"),
                "pick_mode": session.get("pick_mode"),
                "csi_band": session.get("csi_band"),
                **{k: pick.get(k) for k in _CSV_COLUMNS if k in pick},
            })

    lines = [
        "# 今日名单 · 实盘复盘账本",
        "",
        f"生成时间：{datetime.now().isoformat(timespec='seconds')}　|　"
        "数据源：本机 enriched 日 K　|　auto_tune=false（只记录，不自动改选股条件）",
        "",
        "## 汇总",
        "",
        f"- 记录天数：{stats['days_logged']}（已结算 {stats['days_settled']}，空仓 {stats['empty_days']}）",
        f"- 已对照票次：{stats['picks_settled']}；次日收盘上涨 {stats['next_close_win']} 只，"
        f"胜率 {_pct(stats['next_close_win_rate'])}",
        f"- 改规则门槛：{stats['rule_change']['note']}",
        f"- 次日平均涨跌：相对信号收盘 {_avg(vs_signal)}，相对开盘买入 {_avg(vs_buy)}",
        f"- 持有期内 +5% 止盈命中：{tp_hit}/{tp_n}"
        f"（其中 {tp_observing} 只观察期未满 {HOLD_TRADING_DAYS} 日, 暂未命中不是结论）",
        "",
        "## 字段口径",
        "",
        "- 信号收盘＝推荐当天收盘；次日开盘＝按规则的买入价；次日收盘＝第二天的真实收盘价。",
        "- 「次日涨跌」＝次日收盘 / 信号收盘 − 1；「相对开盘」＝次日收盘 / 次日开盘 − 1。",
        "- 开盘高开超 1.5% 记为 skipped_gap（规则不买），但仍照实记录次日收盘。",
        "- T+1 收盘＝可卖日收盘；止盈＝持有期内最高价是否触及开盘价 +5%。",
        "- 止盈观察未满 20 个交易日时只记暂未命中, 不是最终结论。",
        "",
        "## 逐日明细（最近在前）",
        "",
        "| 信号日 | 代码 | 名称 | 信号收盘 | 次日日期 | 次日开盘 | 次日最高 | 次日收盘 | 次日涨跌 | 相对开盘 | T+1收盘 | 止盈 | 判定 | 当时依据 |",
        "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        verdict = "—"
        if row.get("correct_next_close") is True:
            verdict = "对"
        elif row.get("correct_next_close") is False:
            verdict = "错"
        if row.get("status") in (None, "pending") and row.get("next_close") is None:
            verdict = "待结算"
        tp = "—"
        if row.get("tp_hit") is True:
            tp = f"命中 {_txt(row.get('tp_date'))}"
        elif row.get("tp_hit") is False:
            checked = row.get("tp_checked_days")
            tp = (
                f"暂未命中(观察 {checked}/{HOLD_TRADING_DAYS} 日)"
                if isinstance(checked, int) and checked < HOLD_TRADING_DAYS
                else "未命中"
            )
        lines.append(
            "| {as_of} | {symbol} | {name} | {signal_close} | {buy_date} | {buy_open} | "
            "{next_high} | **{next_close}** | {vs_sig} | {vs_buy} | {tplus1} | {tp} | "
            "{verdict} | {why} |".format(
                as_of=_txt(row.get("as_of")),
                symbol=_txt(row.get("symbol")),
                name=_txt(row.get("name")),
                signal_close=_txt(row.get("signal_close")),
                buy_date=_txt(row.get("buy_date") or row.get("next_close_date")),
                buy_open=_txt(row.get("buy_open")),
                next_high=_txt(row.get("next_high")),
                next_close=_txt(row.get("next_close")),
                vs_sig=_pct(row.get("next_close_vs_signal")),
                vs_buy=_pct(row.get("next_close_vs_buy")),
                tplus1=_txt(row.get("tplus1_close")),
                tp=tp,
                verdict=verdict,
                why=_reason_text(row),
            )
        )
    lines += [
        "",
        "> 复盘用法：按信号日/当时依据分组，比较次日涨跌与后续止盈命中，",
        "> 找出哪类依据真有边际。本档只作分析输入，不自动改 E1 参数。",
        "",
    ]
    md_path = user_dir / REVIEW_MD_NAME
    md_path.write_text("\n".join(lines), encoding="utf-8")

    csv_path = user_dir / REVIEW_CSV_NAME
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                k: " | ".join(str(v) for v in row[k]) if isinstance(row.get(k), list) else row.get(k)
                for k in _CSV_COLUMNS
            })
    return {"markdown": md_path, "csv": csv_path}


def load_snapshot(data_dir: Path, as_of: Any) -> dict[str, Any] | None:
    """读某信号日的定版名单；没有定版过返回 None。"""
    day = _as_date(as_of)
    if day is None:
        return None
    try:
        conn = _connect(data_dir)
        try:
            row = conn.execute(
                "SELECT payload FROM beginner_snapshots WHERE as_of = ?",
                (day.isoformat(),),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("beginner snapshot unreadable: %s", exc)
        return None
    if not row:
        return None
    try:
        item = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None
    return item if isinstance(item, dict) else None


def save_snapshot_if_absent(data_dir: Path, payload: dict[str, Any]) -> bool:
    """每个信号日只定版一次；重复请求 / 管道重跑都不覆盖。"""
    day = _as_date(payload.get("as_of"))
    if day is None:
        return False
    body = json.dumps(
        {k: v for k, v in payload.items() if k != "live_review"},
        ensure_ascii=False,
    )
    try:
        conn = _connect(data_dir)
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO beginner_snapshots(as_of, payload, archived_at) "
                "VALUES (?, ?, ?)",
                (day.isoformat(), body, datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
            written = cur.rowcount > 0
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("beginner snapshot save failed: %s", exc)
        return False
    if written:
        logger.info("beginner picks pinned: as_of=%s", day.isoformat())
    return written


_DISPLAY_KEYS = (
    "signal_note",
    "honesty",
    "how_to_use",
    "hold_trading_days",
    "review_trading_days",
    "open_gap_skip",
    "take_profit",
    "index_symbol",
    "overlays",
)


def pin_or_restore(data_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Pin the signal-day list once. Later reads keep those picks.

    amt_q is a same-day cross-section rank, so a later refresh can change
    who is on the list. Buy instructions stay on the current code so the
    homepage does not keep an old sentence from the first snapshot.
    """
    with _LOCK:
        snap = load_snapshot(data_dir, payload.get("as_of"))
        if snap is None:
            save_snapshot_if_absent(data_dir, payload)
        else:
            display = {key: payload[key] for key in _DISPLAY_KEYS if key in payload}
            payload.update(snap)
            payload.update(display)
            payload.pop("live_review", None)
        return payload


def attach_review(repo: Any, data_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Pin the signal-day list, archive it, settle what K-line already allows."""
    payload = pin_or_restore(data_dir, payload)
    try:
        archive_payload(payload, data_dir)
        log = settle_log(repo, data_dir)
    except Exception:
        logger.exception("beginner pick review failed")
        payload["live_review"] = {
            "stats": summarize(_empty_log()),
            "sessions": [],
        }
        return payload
    sessions = list(reversed(log.get("sessions") or []))
    payload["live_review"] = {
        "stats": summarize(log),
        "sessions": sessions[:30],
    }
    return payload


def refresh_after_pipeline(repo: Any) -> None:
    """Run after daily K catch-up so reviews update even if the 今日 page is closed."""
    try:
        from app.services.beginner_picks import build_beginner_picks

        data_dir = Path(repo.store.data_dir)
        payload = build_beginner_picks(repo, data_dir)
        attach_review(repo, data_dir, payload)
    except Exception:
        logger.exception("beginner pick review after pipeline failed")
