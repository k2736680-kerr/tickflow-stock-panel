#!/usr/bin/env python3
# ruff: noqa: RUF001
"""Print the live E1 ledger sample gate.

Does not recompute docs/e1-evidence.md and does not change pick rules.
Does not create tickflow.db when the ledger is missing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.beginner_pick_review import load_log_readonly, summarize  # noqa: E402


def _data_dir() -> Path:
    raw = os.environ.get("DATA_DIR", "").strip()
    if not raw:
        return REPO / "data"
    path = Path(raw)
    if path.is_absolute():
        return path
    return (REPO / path).resolve()


def main() -> int:
    data_dir = _data_dir()
    stats = summarize(load_log_readonly(data_dir))
    gate = stats["rule_change"]
    rate = stats["next_close_win_rate"]
    rate_text = "尚无" if rate is None else f"{rate * 100:.1f}%"
    print(f"数据目录：{data_dir}")
    print(f"已记录交易日：{stats['days_logged']}")
    print(f"已结算且有名单：{stats['days_settled']}")
    print(f"空仓天数：{stats['empty_days']}")
    print(f"已对照票次：{stats['picks_settled']}")
    print(f"账本次日收盘上涨比例：{rate_text}（只来自账本，不是历史回放）")
    print(
        f"改规则门槛：{gate['settled_days']}/{gate['min_settled_days']}"
        f"，ready={gate['ready']}"
    )
    print(gate["note"])
    print("auto_tune=false。历史回放数字见 docs/e1-evidence.md，本脚本不重算。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
