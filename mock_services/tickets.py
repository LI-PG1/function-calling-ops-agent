"""报修工单 / 领料通知 mock 服务（SQLite + 失败注入）。"""

from __future__ import annotations

import pathlib
import sqlite3
import time
import uuid
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tickets.db"


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS tickets("
        "ticket_id TEXT PRIMARY KEY, device_id TEXT, fault_code TEXT, "
        "description TEXT, status TEXT, parts TEXT, created_at TEXT)"
    )
    return con


def _maybe_fail(fail_mode: str) -> None:
    if fail_mode == "timeout":
        time.sleep(3.0)
    if fail_mode == "error":
        raise RuntimeError("ticket service: HTTP 500")


def create_ticket(
    device_id: str, fault_code: str, description: str = "", fail_mode: str = "off"
) -> dict:
    _maybe_fail(fail_mode)
    tid = "T" + uuid.uuid4().hex[:8].upper()
    con = _conn()
    try:
        con.execute(
            "INSERT INTO tickets VALUES (?,?,?,?,?,?,?)",
            (
                tid,
                device_id,
                fault_code,
                description,
                "created",
                "",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        con.commit()
    finally:
        con.close()
    return {"ticket_id": tid, "status": "created"}


def request_pickup(ticket_id: str, parts: list[str], fail_mode: str = "off") -> dict:
    _maybe_fail(fail_mode)
    con = _conn()
    try:
        cur = con.execute(
            "UPDATE tickets SET status='pickup_requested', parts=? WHERE ticket_id=?",
            (",".join(parts), ticket_id),
        )
        con.commit()
        if cur.rowcount == 0:
            raise ValueError(f"ticket not found: {ticket_id}")
    finally:
        con.close()
    return {"ticket_id": ticket_id, "pickup": "requested", "parts": parts}


if __name__ == "__main__":
    t = create_ticket("ZX-110A-03", "E-ZX-02", "排气高温报警")
    print(t, request_pickup(t["ticket_id"], ["ZX-OC-06"]))
