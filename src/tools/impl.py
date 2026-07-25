"""工具实现：入参校验 + mock 服务封装 + 失败注入注册表 + 规则库检索。

- 失败注入：评测运行时通过 set_injection 注册（generic：error / timeout / empty），
  invoke 在执行前消费一次——用于"失败注入下可靠性行为"的评测；
- search_safety_rules：规则库检索——默认关键词；设置 EMBED_BASE_URL 时走
  自部署向量服务（Qwen3-Embedding-4B），任何失败自动回落关键词并标注 mode。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import time
import urllib.request

from mock_services import cs as mock_cs
from mock_services import orders as mock_orders
from mock_services import vehicle as mock_vehicle

ROOT = pathlib.Path(__file__).resolve().parents[2]

# ============ 失败注入注册表（评测用）============

_INJECT: dict[str, dict] = {}


def set_injection(spec: dict | None) -> None:
    """注册注入：{tool: {"mode": "error|timeout|empty", "times": n}}；None 清空。"""
    global _INJECT
    _INJECT = dict(spec or {})


def _consume_injection(tool: str) -> str:
    entry = _INJECT.get(tool)
    if not entry:
        return "off"
    entry["times"] = int(entry.get("times", 1)) - 1
    if entry["times"] <= 0:
        _INJECT.pop(tool, None)
    return entry.get("mode", "off")


def _apply_injection(tool: str, mode: str, result):
    """generic 注入：timeout 悬挂 / error 抛错 / empty 清空列表。"""
    if mode == "timeout":
        time.sleep(3.0)
    if mode == "error":
        raise RuntimeError(f"{tool}: simulated service error (HTTP 500)")
    if mode == "empty" and isinstance(result, list):
        return []
    return result


# ============ 规则库检索 ============

_RULES: list[dict] | None = None
_EMB_CACHE: dict = {"entries": None, "vectors": None}


def _load_rules() -> list[dict]:
    global _RULES
    if _RULES is None:
        _RULES = json.loads((ROOT / "data" / "rules" / "index.json").read_text(encoding="utf-8"))
    return _RULES


def _keyword_scores(query: str, entries: list[dict]) -> list[float]:
    tokens = [t for t in re.split(r"[\s，。？！?、,；;：:]+", query or "") if len(t) >= 2]
    scores = []
    for e in entries:
        hay = e["title"] + " " + " ".join(e.get("keywords", [])) + " " + e["text"]
        s = 0.0
        for t in tokens:
            if t in hay:
                s += 1.0
            elif len(t) >= 3 and t[:2] in hay:
                s += 0.4
        scores.append(s)
    return scores


def _embed_scores(query: str, entries: list[dict]) -> list[float] | None:
    """接自部署向量服务（可选）；任何失败返回 None（回落关键词）。"""
    base = os.getenv("EMBED_BASE_URL", "").rstrip("/")
    if not base:
        return None
    try:
        if _EMB_CACHE["entries"] is not _RULES or _EMB_CACHE["vectors"] is None:
            texts = [e["title"] + "。" + e["text"] for e in entries]
            _EMB_CACHE["vectors"] = _embed_call(base, texts)
            _EMB_CACHE["entries"] = _RULES
        qv = _embed_call(base, [query])[0]
        return [sum(a * b for a, b in zip(qv, ev)) for ev in _EMB_CACHE["vectors"]]
    except Exception:  # noqa: BLE001 —— 向量服务不可用时回落关键词
        return None


def _embed_call(base: str, texts: list[str]) -> list[list[float]]:
    req = urllib.request.Request(
        base + "/v1/embeddings",
        data=json.dumps({"model": "qwen3-embedding-4b", "input": texts}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    items = sorted(data["data"], key=lambda x: x.get("index", 0))
    return [it["embedding"] for it in items]


def search_safety_rules(query: str, top_k: int = 3, fail_mode: str = "off") -> list[dict]:
    mode = _consume_injection("search_safety_rules") or fail_mode
    if mode == "timeout":
        time.sleep(3.0)
    if mode == "error":
        raise RuntimeError("search_safety_rules: simulated service error (HTTP 500)")
    entries = _load_rules()
    scores = _embed_scores(query, entries)
    if scores is None:
        scores = _keyword_scores(query, entries)
    ranked = sorted(zip(scores, entries), key=lambda p: -p[0])
    hits = []
    for s, e in ranked[: int(top_k)]:
        if s <= 0:
            break
        hits.append(
            {
                "id": e["id"],
                "title": e["title"],
                "risk": e["risk"],
                "strategy": e["strategy"],
                "text": e["text"],
                "score": round(s, 3),
            }
        )
    return hits


def assess_risk(situation: str, fail_mode: str = "off") -> dict:
    """规则库匹配 → 风险等级与处置策略（确定性；可解释）。"""
    mode = _consume_injection("assess_risk") or fail_mode
    if mode == "timeout":
        time.sleep(3.0)
    if mode == "error":
        raise RuntimeError("assess_risk: simulated service error (HTTP 500)")
    entries = [e for e in _load_rules() if e["kind"] == "scene"]
    scores = _keyword_scores(situation, entries)
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    ranked = sorted(zip(scores, entries), key=lambda p: -p[0])
    matched = [(s, e) for s, e in ranked if s > 0]
    if not matched:
        return {
            "risk": "low",
            "scene": None,
            "strategy": [],
            "must_output": [],
            "handling": "未命中特定场景规则，按常规服务处理。",
            "matched": [],
        }
    top_score, top = matched[0]
    risk = max(
        (e["risk"] for s, e in matched if s >= max(1.0, top_score * 0.6)), key=lambda r: order[r]
    )
    return {
        "risk": risk,
        "scene": top["id"].split(":")[1],
        "strategy": top["strategy"],
        "must_output": top["must_output"],
        "handling": top["text"],
        "matched": [e["id"] for s, e in matched[:3]],
    }


# ============ mock 服务工具 ============


def get_vehicle_status(fail_mode: str = "off") -> dict:
    mode = _consume_injection("get_vehicle_status") or fail_mode
    return _apply_injection("get_vehicle_status", mode, mock_vehicle.get_status())


def control_climate(
    action: str, zone: str = "all", temp: int | None = None, fail_mode: str = "off"
) -> dict:
    mode = _consume_injection("control_climate") or fail_mode
    return _apply_injection(
        "control_climate", mode, mock_vehicle.control_climate(action, zone, temp)
    )


def control_seat(action: str, zone: str = "driver", fail_mode: str = "off") -> dict:
    mode = _consume_injection("control_seat") or fail_mode
    return _apply_injection("control_seat", mode, mock_vehicle.control_seat(action, zone))


def control_door(action: str, door: str = "fl", fail_mode: str = "off") -> dict:
    mode = _consume_injection("control_door") or fail_mode
    return _apply_injection("control_door", mode, mock_vehicle.control_door(action, door))


def control_safety(action: str, value: int | None = None, fail_mode: str = "off") -> dict:
    mode = _consume_injection("control_safety") or fail_mode
    return _apply_injection("control_safety", mode, mock_vehicle.control_safety(action, value))


def navigate(destination: str, fail_mode: str = "off") -> dict:
    mode = _consume_injection("navigate") or fail_mode
    return _apply_injection("navigate", mode, mock_vehicle.navigate(destination))


def find_parking(near: str = "", fail_mode: str = "off") -> list[dict]:
    mode = _consume_injection("find_parking") or fail_mode
    return _apply_injection("find_parking", mode, mock_vehicle.find_parking(near))


def find_charging(near: str = "", fail_mode: str = "off") -> list[dict]:
    mode = _consume_injection("find_charging") or fail_mode
    return _apply_injection("find_charging", mode, mock_vehicle.find_charging(near))


def play_media(category: str = "轻音乐", fail_mode: str = "off") -> dict:
    mode = _consume_injection("play_media") or fail_mode
    return _apply_injection("play_media", mode, mock_vehicle.play_media(category))


def query_ride_order(order_id: str = "", fail_mode: str = "off") -> dict:
    mode = _consume_injection("query_ride_order") or fail_mode
    return _apply_injection("query_ride_order", mode, mock_orders.query_order(order_id))


def modify_pickup_point(order_id: str, point: str, fail_mode: str = "off") -> dict:
    mode = _consume_injection("modify_pickup_point") or fail_mode
    return _apply_injection(
        "modify_pickup_point", mode, mock_orders.modify_pickup_point(order_id, point)
    )


def change_destination(order_id: str, destination: str, fail_mode: str = "off") -> dict:
    mode = _consume_injection("change_destination") or fail_mode
    return _apply_injection(
        "change_destination", mode, mock_orders.change_destination(order_id, destination)
    )


def escalate_human(reason: str, priority: str = "normal", fail_mode: str = "off") -> dict:
    mode = _consume_injection("escalate_human") or fail_mode
    return _apply_injection("escalate_human", mode, mock_cs.create_ticket(reason, priority))


# ============ 注册表 ============

DISPATCH = {
    "get_vehicle_status": get_vehicle_status,
    "assess_risk": assess_risk,
    "search_safety_rules": search_safety_rules,
    "control_climate": control_climate,
    "control_seat": control_seat,
    "control_door": control_door,
    "control_safety": control_safety,
    "navigate": navigate,
    "find_parking": find_parking,
    "find_charging": find_charging,
    "play_media": play_media,
    "query_ride_order": query_ride_order,
    "modify_pickup_point": modify_pickup_point,
    "change_destination": change_destination,
    "escalate_human": escalate_human,
}

REQUIRED = {
    "get_vehicle_status": [],
    "assess_risk": ["situation"],
    "search_safety_rules": ["query"],
    "control_climate": ["action"],
    "control_seat": ["action"],
    "control_door": ["action"],
    "control_safety": ["action"],
    "navigate": ["destination"],
    "find_parking": [],
    "find_charging": [],
    "play_media": ["category"],
    "query_ride_order": [],
    "modify_pickup_point": ["order_id", "point"],
    "change_destination": ["order_id", "destination"],
    "escalate_human": ["reason"],
}


def validate_args(name: str, args: dict) -> tuple[bool, str]:
    if name not in DISPATCH:
        return False, f"unknown tool: {name}"
    if not isinstance(args, dict):
        return False, "arguments must be an object"
    for req in REQUIRED.get(name, []):
        if req not in args or args[req] in ("", None, []):
            return False, f"missing required arg: {req}"
    return True, ""


def invoke(name: str, args: dict):
    """校验后调用工具（不含超时/重试——由可靠性层包装）。"""
    ok, err = validate_args(name, args)
    if not ok:
        raise ValueError(f"invalid tool call: {err}")
    return DISPATCH[name](**args)
