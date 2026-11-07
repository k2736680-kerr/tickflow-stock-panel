# ruff: noqa: RUF001
"""Optional Supabase KV for user state. Market K-line stays on local parquet.

Fail-open: missing URL, network errors, or driver issues never break the panel.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tickflow_kv (
    key text PRIMARY KEY,
    value jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""
_LOCK = threading.Lock()
_SCHEMA_READY = False


def enabled() -> bool:
    import os

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    url = _dsn()
    return bool(url)


def _dsn() -> str:
    try:
        from app.config import settings
        return str(getattr(settings, "supabase_db_url", "") or "").strip()
    except Exception:
        return ""


def _connect():
    import psycopg

    dsn = _dsn()
    if not dsn:
        return None
    return psycopg.connect(dsn, connect_timeout=8)


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    conn.execute(_TABLE_SQL)
    conn.commit()
    _SCHEMA_READY = True


def put(key: str, value: Any) -> bool:
    if not enabled():
        return False
    try:
        with _LOCK:
            conn = _connect()
            if conn is None:
                return False
            try:
                _ensure_schema(conn)
                payload = json.dumps(value, ensure_ascii=False, default=str)
                conn.execute(
                    """
                    INSERT INTO tickflow_kv(key, value, updated_at)
                    VALUES (%s, %s::jsonb, now())
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = now()
                    """,
                    (key, payload),
                )
                conn.commit()
            finally:
                conn.close()
        logger.info("supabase put %s", key)
        return True
    except Exception as exc:
        logger.warning("supabase put %s failed: %s", key, exc)
        return False


def get(key: str) -> tuple[Any, datetime | None] | tuple[None, None]:
    if not enabled():
        return None, None
    try:
        with _LOCK:
            conn = _connect()
            if conn is None:
                return None, None
            try:
                _ensure_schema(conn)
                row = conn.execute(
                    "SELECT value, updated_at FROM tickflow_kv WHERE key = %s",
                    (key,),
                ).fetchone()
            finally:
                conn.close()
        if not row:
            return None, None
        value, updated = row
        if isinstance(value, str):
            value = json.loads(value)
        return value, updated
    except Exception as exc:
        logger.warning("supabase get %s failed: %s", key, exc)
        return None, None


def push_async(key: str, value: Any) -> None:
    threading.Thread(target=put, args=(key, value), daemon=True, name=f"sb-{key}").start()


def _file_mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return None


def _remote_newer(updated: datetime | None, path: Path) -> bool:
    if updated is None:
        return False
    local = _file_mtime(path)
    if local is None:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return updated > local


def push_user_state() -> None:
    """Push preferences / watchlist / groups. Safe to call from write paths."""
    if not enabled():
        return
    try:
        from app.services import preferences, watchlist

        push_async("preferences", preferences.load())
        entries = watchlist._read_entries()
        push_async("watchlist", entries.to_dicts())
        push_async("watchlist_groups", watchlist._read_groups())
    except Exception as exc:
        logger.warning("supabase push user state failed: %s", exc)


def restore_user_state() -> None:
    """If remote copy is newer or local file is missing, write it back."""
    if not enabled():
        return
    try:
        from app.services import preferences, watchlist

        prefs, prefs_at = get("preferences")
        pref_path = preferences._path()
        if isinstance(prefs, dict) and prefs and _remote_newer(prefs_at, pref_path):
            pref_path.write_text(json.dumps(prefs, indent=2, ensure_ascii=False), encoding="utf-8")
            preferences._invalidate_cache()
            logger.info("supabase restored preferences")

        groups, groups_at = get("watchlist_groups")
        groups_path = watchlist._groups_path()
        if isinstance(groups, list) and _remote_newer(groups_at, groups_path):
            watchlist._write_groups(groups)
            logger.info("supabase restored watchlist groups")

        rows, rows_at = get("watchlist")
        watch_path = watchlist._path()
        if isinstance(rows, list) and _remote_newer(rows_at, watch_path):
            import polars as pl

            df = pl.DataFrame(rows) if rows else watchlist._empty_entries()
            watchlist._write_entries(df)
            logger.info("supabase restored watchlist (%s rows)", 0 if df is None else df.height)
    except Exception as exc:
        logger.warning("supabase restore failed: %s", exc)


def bootstrap() -> None:
    if not enabled():
        logger.info("supabase 未配置，用户数据只放本机")
        return
    restore_user_state()
    put("heartbeat", {"at": datetime.now(UTC).isoformat(), "app": "tickflow-stock-panel"})
    push_user_state()
