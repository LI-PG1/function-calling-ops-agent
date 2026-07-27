"""三层场景路由：① 规则快路径（高危关键词，毫秒级）→ ② LLM 场景标签 → ③ 宽表兜底。

输出 RouteDecision：{mode, scenes, risk, reason, path}
- path=fast_rule：高危请求被规则层即时识别（不进 LLM，走安全处置流）
- path=llm：常规请求由 LLM 判定身份/场景/风险
- path=fallback：LLM 判定失败 → 轻量应答（不装载工具）
"""

from __future__ import annotations

import json
import re
import time

from src.prompts import SYSTEM, load_prompt, render

KNOWN_SCENES = (
    "tired",
    "child",
    "longtrip",
    "commute",
    "robotaxi_lost",
    "pickup_abnormal",
    "dest_change",
    "passenger_help",
)

# ---- ① 规则快路径：高危模式（正则在原文匹配）----
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"(打开|开开|解锁|把.*(打开|解锁)).{0,6}(车门|门)|车门(打开|解锁)", "行驶相关：开门/解锁请求"),
    (r"(解开|松(开|掉)|脱).{0,4}安全带|安全带.{0,4}(解开|松)", "行驶相关：解开安全带请求"),
    (
        r"(速度|巡航).{0,6}(1[3-9]\d|[2-9]\d\d)|(设|调|定|开)(到|成)?.{0,4}(1[3-9]\d|[2-9]\d\d).{0,4}(码|迈|km|速度|巡航)",
        "超速设定请求",
    ),
    (r"座椅.{0,4}(放平|躺平|完全放)|(放平|躺平).{0,4}座椅", "行驶相关：座椅放平请求"),
]
CHILD_ALONE_PATTERN = (
    r"(孩子|儿童|宝宝|小朋友).{0,12}(一个人|单独|独自|自己|独留).{0,8}(车里|车上|车内)"
)
CHILD_KEYWORDS = ("孩子", "儿童", "宝宝", "小朋友", "安全椅")

MODE_HINTS_ROBOTAXI = (
    "订单",
    "上车点",
    "司机",
    "网约车",
    "叫的车",
    "打车",
    "乘客",
    "Robotaxi",
    "robotaxi",
)
MODE_HINTS_OWNER = ("我的车", "车主", "自己开", "自驾", "导航", "空调", "座椅", "巡航", "方向盘")


def _scan_scenes(task: str) -> list[str]:
    """按场景关键词做快速场景猜测（快路径用；不追求全，够用即可）。"""
    import yaml  # 局部导入：仅在快路径使用
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    scenes = yaml.safe_load(
        (root / "config" / "safety_rules.yaml").read_text(encoding="utf-8")
    ).get("scenes", [])
    hits = []
    for s in scenes:
        for kw in s.get("keywords", []):
            if kw in task:
                hits.append(s["id"])
                break
    return hits[:2]


def route_rules_only(task: str) -> dict | None:
    """① 规则快路径：命中高危模式 → 返回决策（否则 None，交 LLM）。"""
    for pattern, why in DANGEROUS_PATTERNS:
        if re.search(pattern, task):
            risk = "critical" if re.search(CHILD_ALONE_PATTERN, task) else "high"
            mode = "robotaxi" if any(k in task for k in MODE_HINTS_ROBOTAXI) else "owner"
            if "订单" in task or "上车点" in task:
                mode = "robotaxi"
            scenes = _scan_scenes(task)
            return {
                "mode": mode,
                "scenes": scenes,
                "risk": risk,
                "reason": f"规则快路径命中：{why}",
                "path": "fast_rule",
            }

    # 明确涉及儿童 + 独留 → 即时 critical
    if re.search(CHILD_ALONE_PATTERN, task):
        return {
            "mode": "owner",
            "scenes": ["child"],
            "risk": "critical",
            "reason": "规则快路径命中：儿童独留风险",
            "path": "fast_rule",
        }

    # 状态硬规则：任务提及儿童时，核对车内状态（儿童独留 → critical）
    if any(k in task for k in CHILD_KEYWORDS):
        try:
            from mock_services import vehicle as _mock_vehicle

            st = _mock_vehicle.get_state()
            if st.get("child_present") and not st.get("adults_present"):
                return {
                    "mode": "owner",
                    "scenes": ["child"],
                    "risk": "critical",
                    "reason": "状态硬规则命中：车内检测到儿童独留",
                    "path": "fast_rule",
                }
        except Exception:  # noqa: BLE001 —— 状态不可读时交 LLM 层
            pass
    return None


def route_llm(task: str, llm) -> dict | None:
    """② LLM 场景标签；解析失败返回 None（交兜底）。"""
    prompt = render(load_prompt("route"), task=task)
    try:
        raw = llm.chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            max_tokens=256,
        )
        data = _extract_json(raw.get("content", ""))
        if not isinstance(data, dict):
            return None
        mode = (
            data.get("mode") if data.get("mode") in ("owner", "robotaxi", "unknown") else "unknown"
        )
        scenes = [s for s in (data.get("scenes") or []) if s in KNOWN_SCENES][:2]
        risk = (
            data.get("risk") if data.get("risk") in ("low", "medium", "high", "critical") else "low"
        )
        return {
            "mode": mode,
            "scenes": scenes,
            "risk": risk,
            "reason": str(data.get("reason", ""))[:120],
            "path": "llm",
        }
    except Exception:  # noqa: BLE001 —— LLM 判定失败走兜底
        return None


def route_task(task: str, llm=None) -> dict:
    """完整三层：fast_rule → llm → fallback。llm=None 时跳过第二层（离线模式）。"""
    t0 = time.perf_counter()
    decision = route_rules_only(task)
    if decision is None and llm is not None:
        decision = route_llm(task, llm)
    if decision is None:
        decision = {
            "mode": "unknown",
            "scenes": [],
            "risk": "low",
            "reason": "无法归类（轻量应答）",
            "path": "fallback",
        }
    decision["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return decision


def _extract_json(text: str):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                return None
    return None


if __name__ == "__main__":
    for q in ["我在高速上，帮我把车门打开透透气", "我有点困了", "我叫的车到哪了"]:
        print(q, "→", route_rules_only(q) or "（未命中快路径）")
