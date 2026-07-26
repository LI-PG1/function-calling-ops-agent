"""备件库存 mock 服务（SQLite + 失败注入）。

失败注入 fail_mode：off / timeout（悬挂，由调用方超时截断）/ error（500）/ empty（空结果）。
"""

from __future__ import annotations

import pathlib
import sqlite3
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "inventory.db"

FAIL_MODES = ("off", "timeout", "error", "empty")


def query_parts(device_model: str = "", part_name: str = "", fail_mode: str = "off") -> list[dict]:
    if fail_mode == "timeout":
        time.sleep(3.0)  # 模拟悬挂
    if fail_mode == "error":
        raise RuntimeError("inventory service: HTTP 500")
    if fail_mode == "empty":
        return []

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        sql = "SELECT part_code, name, qty, models FROM parts WHERE 1=1"
        args: list = []
        if part_name:
            sql += " AND (name LIKE ? OR part_code LIKE ?)"
            args += [f"%{part_name}%", f"%{part_name}%"]
        if device_model:
            sql += " AND models LIKE ?"
            args.append(f"%{device_model}%")
        cur = con.execute(sql, args)
        cols = ["part_code", "name", "qty", "models"]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


if __name__ == "__main__":
    print(query_parts(part_name="油分离器"))
