"""生成备件库存数据库 data/inventory.db（含少量缺货件，用于降级/替代逻辑）。"""

from __future__ import annotations

import json
import pathlib
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANUAL = ROOT / "data" / "manual" / "parts_catalog.json"
DB = ROOT / "data" / "inventory.db"

# 故意缺货的备件（用于演示"缺件 → 降级/替代"逻辑）
ZERO_STOCK = {"ZX-OS-02", "QS-RD-02", "KL-IP-03"}

DEFAULT_QTY = {
    "ZX-AF-01": 12,
    "ZX-OS-02": 0,
    "ZX-IV-03": 3,
    "ZX-PS-04": 8,
    "ZX-BL-05": 6,
    "ZX-OC-06": 24,
    "QS-MT-01": 1,
    "QS-RD-02": 0,
    "QS-BT-03": 2,
    "QS-BR-04": 4,
    "QS-SN-05": 7,
    "KL-SL-01": 10,
    "KL-BR-02": 5,
    "KL-IP-03": 0,
    "KL-CC-04": 9,
    "KL-VL-05": 3,
}


def main() -> None:
    parts = json.loads(MANUAL.read_text(encoding="utf-8"))
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE parts(part_code TEXT PRIMARY KEY, name TEXT, family TEXT, models TEXT, qty INTEGER)"
    )
    for p in parts:
        qty = DEFAULT_QTY.get(p["part_code"], 5)
        if p["part_code"] in ZERO_STOCK:
            qty = 0
        con.execute(
            "INSERT OR REPLACE INTO parts VALUES (?,?,?,?,?)",
            (p["part_code"], p["name"], p["family"], " / ".join(p["models"]), qty),
        )
    con.commit()
    rows = con.execute("SELECT COUNT(*), SUM(qty=0) FROM parts").fetchone()
    print(f"[seed_inventory] {rows[0]} 个备件（其中 {rows[1]} 个缺货）-> {DB}")
    con.close()


if __name__ == "__main__":
    main()
