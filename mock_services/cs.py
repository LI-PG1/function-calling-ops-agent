"""人工客服 mock 服务：转人工工单（含失败注入）。"""

from __future__ import annotations

import pathlib
import sqlite3
import time
import uuid
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "cs.db"

PRIORITIES = ("normal", "urgent", "critical")


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS cs_tickets(cs_id TEXT PRIMARY KEY, reason TEXT, priority TEXT,"
        " status TEXT, created_at TEXT)"
    )
    return con


def _maybe_fail(fail_mode: str) -> None:
    if fail_mode == "timeout":
        time.sleep(3.0)
    if fail_mode == "error":
        raise RuntimeError("cs service: HTTP 500")


def reset() -> None:
    con = _conn()
    try:
        con.execute("DELETE FROM cs_tickets")
        con.commit()
    finally:
        con.close()


def create_ticket(reason: str, priority: str = "normal", fail_mode: str = "off") -> dict:
    _maybe_fail(fail_mode)
    if not reason:
        raise ValueError("reason 不能为空")
    if priority not in PRIORITIES:
        priority = "normal"
    cs_id = "CS" + uuid.uuid4().hex[:8].upper()
    con = _conn()
    try:
        con.execute(
            "INSERT INTO cs_tickets VALUES (?,?,?,?,?)",
            (cs_id, reason, priority, "queued", datetime.now().isoformat(timespec="seconds")),
        )
        con.commit()
    finally:
        con.close()
    return {
        "cs_id": cs_id,
        "status": "queued",
        "priority": priority,
        "message": "已转人工客服，客服将在 3 分钟内接入",
    }


def list_tickets() -> list[dict]:
    con = _conn()
    try:
        rows = con.execute("SELECT * FROM cs_tickets ORDER BY created_at DESC").fetchall()
        cols = ["cs_id", "reason", "priority", "status", "created_at"]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        con.close()


if __name__ == "__main__":
    print(create_ticket("测试工单", "normal"))
