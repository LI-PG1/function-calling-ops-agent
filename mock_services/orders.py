"""Robotaxi 订单 mock 服务：订单状态机 + 幂等 + 失败注入。

状态机：created → accepted → enroute → arrived → onboard → completed
                                           └─ cancelled（终态）
规则：onboard 后/终态不可修改上车点；completed/cancelled 不可修改目的地；
     修改上车点/目的地支持幂等（同 payload 重复调用返回首次结果）。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
import time
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "orders.db"

ACTIVE_STATES = ("created", "accepted", "enroute", "arrived", "onboard")
FINAL_STATES = ("completed", "cancelled")

SEED_PRESETS = {
    "none": [],
    "enroute": [
        {
            "order_id": "ORD-2101",
            "status": "enroute",
            "user": "乘客 王",
            "driver": "司机 刘 · 沪A·T6655",
            "vehicle_plate": "沪A·T6655",
            "pickup_point": "世纪大道 2 号口",
            "destination": "虹桥火车站",
            "eta_min": 4,
            "price_cny": 46.5,
        },
    ],
    "arrived": [
        {
            "order_id": "ORD-2102",
            "status": "arrived",
            "user": "乘客 王",
            "driver": "司机 陈 · 沪A·T8899",
            "vehicle_plate": "沪A·T8899",
            "pickup_point": "静安寺地铁站 1 号口",
            "destination": "陆家嘴环路 100 号",
            "eta_min": 0,
            "price_cny": 32.0,
        },
    ],
    "onboard": [
        {
            "order_id": "ORD-2103",
            "status": "onboard",
            "user": "乘客 王",
            "driver": "司机 赵 · 沪A·T2211",
            "vehicle_plate": "沪A·T2211",
            "pickup_point": "徐家汇",
            "destination": "浦东机场 T2",
            "eta_min": 38,
            "price_cny": 158.0,
        },
    ],
}


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY, status TEXT, user TEXT, driver TEXT,"
        " vehicle_plate TEXT, pickup_point TEXT, destination TEXT, eta_min INTEGER, price_cny REAL, updated_at TEXT)"
    )
    con.execute("CREATE TABLE IF NOT EXISTS idem_log(key TEXT PRIMARY KEY, response TEXT, ts TEXT)")
    return con


def _maybe_fail(fail_mode: str) -> None:
    if fail_mode == "timeout":
        time.sleep(3.0)
    if fail_mode == "error":
        raise RuntimeError("order service: HTTP 500")


def reset(preset: str = "none") -> list[dict]:
    rows = SEED_PRESETS.get(preset, [])
    con = _conn()
    try:
        con.execute("DELETE FROM orders")
        con.execute("DELETE FROM idem_log")
        for o in rows:
            con.execute(
                "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    o["order_id"],
                    o["status"],
                    o["user"],
                    o["driver"],
                    o["vehicle_plate"],
                    o["pickup_point"],
                    o["destination"],
                    o["eta_min"],
                    o["price_cny"],
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
        con.commit()
    finally:
        con.close()
    return rows


def _row_to_dict(row) -> dict:
    cols = [
        "order_id",
        "status",
        "user",
        "driver",
        "vehicle_plate",
        "pickup_point",
        "destination",
        "eta_min",
        "price_cny",
        "updated_at",
    ]
    return dict(zip(cols, row))


def active_order() -> dict | None:
    con = _conn()
    try:
        row = con.execute(
            "SELECT * FROM orders WHERE status IN (?,?,?,?,?) ORDER BY updated_at DESC LIMIT 1",
            ACTIVE_STATES,
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        con.close()


def query_order(order_id: str = "", fail_mode: str = "off") -> dict:
    _maybe_fail(fail_mode)
    con = _conn()
    try:
        if order_id:
            row = con.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
            if not row:
                raise ValueError(f"订单不存在: {order_id}")
        else:
            row = con.execute(
                "SELECT * FROM orders WHERE status IN (?,?,?,?,?) ORDER BY updated_at DESC LIMIT 1",
                ACTIVE_STATES,
            ).fetchone()
            if not row:
                raise ValueError("当前没有进行中的订单")
        return _row_to_dict(row)
    finally:
        con.close()


def _idem(key: str, fn):
    con = _conn()
    try:
        hit = con.execute("SELECT response FROM idem_log WHERE key=?", (key,)).fetchone()
        if hit:
            return {**json.loads(hit[0]), "idempotent_replay": True}
    finally:
        con.close()
    resp = fn()
    con = _conn()
    try:
        con.execute(
            "INSERT OR REPLACE INTO idem_log VALUES (?,?,?)",
            (
                key,
                json.dumps(resp, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        con.commit()
    finally:
        con.close()
    return resp


def modify_pickup_point(order_id: str, point: str, fail_mode: str = "off") -> dict:
    _maybe_fail(fail_mode)
    if not order_id or not point:
        raise ValueError("order_id 与 point 均必填")
    key = "pickup:" + hashlib.md5(f"{order_id}|{point}".encode()).hexdigest()

    def _do():
        con = _conn()
        try:
            row = con.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
            if not row:
                raise ValueError(f"订单不存在: {order_id}")
            o = _row_to_dict(row)
            if o["status"] in FINAL_STATES or o["status"] == "onboard":
                raise ValueError(f"当前订单状态（{o['status']}）不可修改上车点")
            con.execute(
                "UPDATE orders SET pickup_point=?, updated_at=? WHERE order_id=?",
                (point, datetime.now().isoformat(timespec="seconds"), order_id),
            )
            con.commit()
            return {"ok": True, "order_id": order_id, "pickup_point": point, "status": o["status"]}
        finally:
            con.close()

    return _idem(key, _do)


def change_destination(order_id: str, destination: str, fail_mode: str = "off") -> dict:
    _maybe_fail(fail_mode)
    if not order_id or not destination:
        raise ValueError("order_id 与 destination 均必填")
    key = "dest:" + hashlib.md5(f"{order_id}|{destination}".encode()).hexdigest()

    def _do():
        con = _conn()
        try:
            row = con.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
            if not row:
                raise ValueError(f"订单不存在: {order_id}")
            o = _row_to_dict(row)
            if o["status"] in FINAL_STATES:
                raise ValueError(f"当前订单状态（{o['status']}）不可修改目的地")
            con.execute(
                "UPDATE orders SET destination=?, updated_at=? WHERE order_id=?",
                (destination, datetime.now().isoformat(timespec="seconds"), order_id),
            )
            con.commit()
            return {
                "ok": True,
                "order_id": order_id,
                "destination": destination,
                "status": o["status"],
            }
        finally:
            con.close()

    return _idem(key, _do)


if __name__ == "__main__":
    reset("arrived")
    print(active_order())
