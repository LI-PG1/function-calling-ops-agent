"""安全护栏（双层中的 L2 代码硬规则层 + 输出合规校验）。

- pre_check：危险动作前置拦截（数据驱动，规则来自 config/safety_rules.yaml）；
- post_review：高风险/被拦截场景的输出合规校验（缺要素 → 打回重写，由编排层执行）；
- 规则版本化：YAML 的 version 字段随迭代 +1，CHANGELOG 记录。

设计口径：L1 是提示词层（由提示词承载）；本模块 = L2 代码兜底层——"模型失误仍有代码兜底"。
"""

from __future__ import annotations

import pathlib

import yaml

from mock_services import orders as mock_orders
from mock_services import vehicle as mock_vehicle

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES_FILE = ROOT / "config" / "safety_rules.yaml"

_RULES: dict | None = None
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def load_rules() -> dict:
    global _RULES
    if _RULES is None:
        _RULES = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    return _RULES


def rules_version() -> int:
    return int(load_rules().get("version", 0))


def build_context() -> dict:
    """实时上下文（供规则的状态条件判定）：车辆状态 + 订单活跃态。"""
    order = mock_orders.active_order()
    return {
        "vehicle": mock_vehicle.get_state(),
        "order": {"active": order is not None, "order": order},
    }


# ==================== L2 pre_check ====================


def _get_path(data: dict, path: str):
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _cond_ok(cond: dict, arg_vals: dict, ctx: dict) -> bool:
    if "path" in cond and "source" not in cond:
        val = _get_path(arg_vals, cond["path"])
    else:
        src = ctx.get(cond.get("source", ""), {})
        val = _get_path(src, cond["path"]) if "path" in cond else src
    if "in" in cond:
        return val in cond["in"]
    if "eq" in cond:
        return val == cond["eq"]
    if "gt" in cond:
        return isinstance(val, (int, float)) and val > cond["gt"]
    if "gte" in cond:
        return isinstance(val, (int, float)) and val >= cond["gte"]
    if "lt" in cond:
        return isinstance(val, (int, float)) and val < cond["lt"]
    if "contains" in cond:
        return isinstance(val, str) and cond["contains"] in val
    return False


def pre_check(tool: str, args: dict, ctx: dict | None = None) -> dict:
    """危险动作前置拦截。返回 {"blocked": bool, ...}。"""
    ctx = ctx or build_context()
    args = args or {}
    for rule in load_rules().get("pre_check", []):
        if rule.get("tool") != tool:
            continue
        arg_ok = all(_cond_ok(c, args, ctx) for c in rule.get("arg_checks", []))
        if not arg_ok:
            continue
        state_ok = all(_cond_ok(c, args, ctx) for c in rule.get("state_checks", []))
        if not state_ok:
            continue
        return {
            "blocked": True,
            "rule_id": rule["id"],
            "rule_desc": rule.get("desc", ""),
            "strategy": rule.get("strategy", "refuse"),
            "must_output": rule.get("must_output", []),
            "message": rule.get("message", "该动作已被安全规则拦截。"),
        }
    return {"blocked": False}


# ==================== 输出合规（post_review）====================


def required_outputs(risk: str, blocked: list) -> list[str]:
    """按配置推导本次应答必须包含的要素：safety_tip / refusal_reason / escalate。"""
    req: set[str] = set()
    for item in load_rules().get("post_review", []):
        when = item.get("when", {})
        ok = False
        if "risk_in" in when:
            ok = risk in when["risk_in"]
        if "blocked_count_gt" in when:
            ok = ok or len(blocked) > int(when["blocked_count_gt"])
        # 若同一规则同时含两个条件：任一满足即触发（保守从严）
        if ok:
            req.update(item.get("require", []))
    return sorted(req)


def post_review(output: dict, risk: str, blocked: list, escalated: bool) -> list[str]:
    """校验输出四件套合规性，返回缺失要素列表（空 = 合规）。"""
    req = required_outputs(risk, blocked)
    missing = []
    if "safety_tip" in req and not (output.get("safety_tips") or []):
        missing.append("safety_tip")
    if "refusal_reason" in req and not (output.get("refusal_reason") or "").strip():
        missing.append("refusal_reason")
    if "escalate" in req and not escalated:
        missing.append("escalate")
    return missing


def max_risk(*risks: str) -> str:
    best = "low"
    for r in risks:
        if RISK_ORDER.get(r, 0) > RISK_ORDER.get(best, 0):
            best = r
    return best
