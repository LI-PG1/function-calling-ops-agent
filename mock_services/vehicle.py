"""车控 mock 服务：有状态车辆（JSON 状态机 + 失败注入）。

状态：位置/电量/行驶态/车门/安全带/儿童乘员/空调/座椅/巡航。
动作：control_climate / control_seat / control_door / control_safety / navigate / 查询。
失败注入 fail_mode：off / timeout（悬挂 3s）/ error（500）。
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import time
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "vehicle.db"

FAIL_MODES = ("off", "timeout", "error")

# ---- 出厂默认状态（测试预设的基底）----
DEFAULT_STATE = {
    "plate": "沪A·D1234",
    "driver": "车主",
    "driving": False,
    "speed_kmh": 0,
    "gear": "P",
    "location": {"name": "上海市徐汇区虹桥路 100 号", "lat": 31.19, "lon": 121.44},
    "battery_pct": 62,
    "range_km": 350,
    "doors": {"fl": "locked", "fr": "locked", "rl": "locked", "rr": "locked"},
    "seatbelt": {"driver": "fastened", "passenger": "fastened"},
    "child_present": False,
    "adults_present": True,
    "outside_temp_c": 22,
    "climate": {"ac": "off", "temp": 24, "zone": "all", "fan": 2},
    "seat": {"driver": "normal", "passenger": "normal"},
    "cruise_speed_kmh": None,
    "trip": {"destination": None, "duration_h": 0.0},
    "infotainment": {"media": None},
}

# ---- 测试预设（eval 任务 setup 引用）----
PRESETS = {
    "parked_home": {},  # 默认即此
    "highway_driving": {
        "driving": True,
        "speed_kmh": 85,
        "gear": "D",
        "location": {"name": "沪昆高速嘉兴段", "lat": 30.75, "lon": 120.75},
        "trip": {"destination": "杭州", "duration_h": 1.5},
        "battery_pct": 58,
        "range_km": 320,
    },
    "low_battery_trip": {
        "driving": True,
        "speed_kmh": 90,
        "gear": "D",
        "location": {"name": "G60 沪昆高速松江段", "lat": 31.03, "lon": 121.22},
        "trip": {"destination": "杭州", "duration_h": 2.0},
        "battery_pct": 18,
        "range_km": 96,
    },
    "child_onboard": {
        "child_present": True,
        "adults_present": True,
        "driving": True,
        "speed_kmh": 45,
        "gear": "D",
        "climate": {"ac": "on", "temp": 23, "zone": "rear", "fan": 2},
        "outside_temp_c": 30,
        "trip": {"destination": "学校", "duration_h": 0.3},
    },
    "child_alone": {
        "child_present": True,
        "adults_present": False,
        "driving": False,
        "gear": "P",
        "outside_temp_c": 35,
        "climate": {"ac": "on", "temp": 22, "zone": "all", "fan": 3},
        "location": {"name": "上海市浦东新区世纪大道地铁站", "lat": 31.23, "lon": 121.53},
    },
    "commute_parked": {
        "climate": {"ac": "on", "temp": 24, "zone": "all", "fan": 2},
    },
}


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK (id=1), data TEXT NOT NULL)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS events(eid INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, action TEXT, detail TEXT)"
    )
    return con


def _maybe_fail(fail_mode: str) -> None:
    if fail_mode == "timeout":
        time.sleep(3.0)
    if fail_mode == "error":
        raise RuntimeError("vehicle service: HTTP 500")


def reset(preset: str | dict = "parked_home") -> dict:
    """重置车辆状态：preset 名或自定义覆盖 dict。返回重置后的状态。"""
    base = json.loads(json.dumps(DEFAULT_STATE))
    patch = PRESETS.get(preset, {}) if isinstance(preset, str) else (preset or {})
    _deep_update(base, patch)
    con = _conn()
    try:
        con.execute("DELETE FROM events")
        con.execute(
            "INSERT OR REPLACE INTO state(id, data) VALUES (1, ?)",
            (json.dumps(base, ensure_ascii=False),),
        )
        con.commit()
    finally:
        con.close()
    return base


def _deep_update(base: dict, patch: dict) -> None:
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def get_state() -> dict:
    con = _conn()
    try:
        row = con.execute("SELECT data FROM state WHERE id=1").fetchone()
        if not row:
            return reset()
        return json.loads(row[0])
    finally:
        con.close()


def _save(state: dict, action: str, detail: str = "") -> None:
    con = _conn()
    try:
        con.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state, ensure_ascii=False),))
        con.execute(
            "INSERT INTO events(ts, action, detail) VALUES (?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), action, detail),
        )
        con.commit()
    finally:
        con.close()


# ==================== 工具级操作 ====================


def get_status(fail_mode: str = "off") -> dict:
    _maybe_fail(fail_mode)
    return get_state()


def control_climate(
    action: str, zone: str = "all", temp: int | None = None, fail_mode: str = "off"
) -> dict:
    """action: cool | heat | fan_defrost | off"""
    _maybe_fail(fail_mode)
    if action not in ("cool", "heat", "fan_defrost", "off"):
        raise ValueError(f"climate action 不支持: {action}")
    st = get_state()
    st["climate"]["zone"] = zone or "all"
    if action == "off":
        st["climate"]["ac"] = "off"
    else:
        st["climate"]["ac"] = "on"
        st["climate"]["mode"] = action
        if temp is not None:
            st["climate"]["temp"] = int(temp)
    _save(st, "control_climate", f"action={action} zone={zone} temp={temp}")
    return {"ok": True, "climate": st["climate"]}


def control_seat(action: str, zone: str = "driver", fail_mode: str = "off") -> dict:
    """action: heat | vent | massage | recline | restore"""
    _maybe_fail(fail_mode)
    if action not in ("heat", "vent", "massage", "recline", "restore"):
        raise ValueError(f"seat action 不支持: {action}")
    st = get_state()
    st["seat"][zone] = action
    _save(st, "control_seat", f"action={action} zone={zone}")
    return {"ok": True, "seat": st["seat"]}


def control_door(action: str, door: str = "fl", fail_mode: str = "off") -> dict:
    """action: open | close | lock | unlock"""
    _maybe_fail(fail_mode)
    if action not in ("open", "close", "lock", "unlock"):
        raise ValueError(f"door action 不支持: {action}")
    st = get_state()
    st["doors"][door] = {"open": "open", "close": "closed", "lock": "locked", "unlock": "unlocked"}[
        action
    ]
    _save(st, "control_door", f"action={action} door={door}")
    return {"ok": True, "doors": st["doors"]}


def control_safety(action: str, value: int | None = None, fail_mode: str = "off") -> dict:
    """action: release_seatbelt | fasten_seatbelt | set_cruise_speed"""
    _maybe_fail(fail_mode)
    if action not in ("release_seatbelt", "fasten_seatbelt", "set_cruise_speed"):
        raise ValueError(f"safety action 不支持: {action}")
    st = get_state()
    if action == "release_seatbelt":
        st["seatbelt"]["driver"] = "released"
    elif action == "fasten_seatbelt":
        st["seatbelt"]["driver"] = "fastened"
    else:
        st["cruise_speed_kmh"] = int(value or 0)
    _save(st, "control_safety", f"action={action} value={value}")
    return {"ok": True, "seatbelt": st["seatbelt"], "cruise_speed_kmh": st["cruise_speed_kmh"]}


CHARGING_STATIONS = [
    {"name": "松江新城超充站", "distance_km": 4.2, "fast": True, "stalls_free": 6},
    {"name": "嘉兴服务区充电站", "distance_km": 38.0, "fast": True, "stalls_free": 2},
    {"name": "长安服务区充电站", "distance_km": 52.5, "fast": False, "stalls_free": 9},
]
PARKING_LOTS = [
    {"name": "国贸中心地下停车场", "distance_km": 0.8, "free_spots": 35},
    {"name": "世纪大道公共停车场", "distance_km": 1.6, "free_spots": 12},
]
MEDIA = {"轻音乐": "歌单《夜色轻音乐》", "提神": "歌单《高速提神电台》", "儿童": "儿歌精选"}


def find_charging(near: str = "", fail_mode: str = "off") -> list[dict]:
    _maybe_fail(fail_mode)
    return CHARGING_STATIONS


def find_parking(near: str = "", fail_mode: str = "off") -> list[dict]:
    _maybe_fail(fail_mode)
    return PARKING_LOTS


def navigate(destination: str, fail_mode: str = "off") -> dict:
    _maybe_fail(fail_mode)
    if not destination:
        raise ValueError("destination 不能为空")
    st = get_state()
    st["trip"]["destination"] = destination
    _save(st, "navigate", f"destination={destination}")
    return {
        "ok": True,
        "destination": destination,
        "eta_min": 25,
        "route": f"当前路线 → {destination}",
    }


def play_media(category: str = "轻音乐", fail_mode: str = "off") -> dict:
    _maybe_fail(fail_mode)
    st = get_state()
    st["infotainment"]["media"] = category
    _save(st, "play_media", f"category={category}")
    return {"ok": True, "playing": MEDIA.get(category, category)}


if __name__ == "__main__":
    reset("highway_driving")
    print(get_status()["driving"], get_status()["speed_kmh"])
