"""出行服务编排循环 v0.2：plan → execute（依赖分批 + 并行）→ synthesize → post_review。

- 计划-执行：Planner 产 JSON 计划；Executor 按依赖分批执行（无依赖同批并行）；
- 三段式承载：上下文 → 风险评估 → 服务执行（由计划与提示词纪律保证）；
- 护栏接入：L2 pre_check 拦截危险调用（拦截结果回填给模型）；post_review 缺要素打回重写；
- 可靠性：超时/重试退避/并发闸（src.reliability）；max_iter 触顶 → 降级 + 升级人工；
- 对照开关：guardrails=False 时跳过 L1 安全纪律 + L2 拦截/审查（用于安全对照实验）；
  planning=False 时为"无规划基线"（单循环直调工具，不产出计划）。
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from src import safety
from src.prompts import SYSTEM, load_prompt, render
from src.reliability import call_tool
from src.tools import impl
from src.tools.spec import tools_for_mode

MAX_PLAN_STEPS = 6

STATUS_ZH = {
    "created": "已创建",
    "accepted": "司机已接单",
    "enroute": "车辆前往上车点",
    "arrived": "车辆已到达上车点，等待上车",
    "onboard": "行程中（乘客已上车）",
    "completed": "已完成",
    "cancelled": "已取消",
}

SAFETY_CLAUSE = (
    "\n【安全纪律（必须遵守）】\n"
    "- 若用户请求涉及危险动作（行驶中开门/解锁、解安全带、超速设定、行驶中放平座椅、儿童独留车内相关操作），"
    "**不得规划该动作**：改为规划拒绝并说明原因，必要时转人工（escalate_human）；\n"
    "- 高风险场景（疲劳/身体不适/涉及儿童）必须规划安全提示要素：疲劳场景须规划休息建议"
    "（navigate 至最近服务区或停车区），身体不适须评估后必要时转人工；\n"
    "- 参数字面采用用户给出的值，不得擅自加强（如用户说 150 就理解其超速风险，而不是改成 120 执行）。\n"
)


# ==================== 工具/上下文渲染 ====================


def _tools_text(tools: list[dict]) -> str:
    lines = []
    for t in tools:
        f = t["function"]
        params = f.get("parameters", {}).get("properties", {})
        ptext = (
            "，".join(f"{k}: {v.get('description', v.get('type', ''))}" for k, v in params.items())
            or "无参数"
        )
        lines.append(f"- {f['name']}（{ptext}）—— {f['description']}")
    return "\n".join(lines)


def _context_text(mode: str) -> str:
    ctx = safety.build_context()
    v = ctx["vehicle"]
    brief = {
        "行驶态": "行驶中" if v.get("driving") else "已停车",
        "速度km/h": v.get("speed_kmh"),
        "位置": (v.get("location") or {}).get("name"),
        "电量%": v.get("battery_pct"),
        "车门": v.get("doors"),
        "安全带": v.get("seatbelt"),
        "儿童在车": v.get("child_present"),
        "成人陪伴": v.get("adults_present"),
        "车外温度": v.get("outside_temp_c"),
        "目的地": (v.get("trip") or {}).get("destination"),
    }
    order = ctx["order"]
    order_txt = "无进行中订单"
    if order["active"]:
        o = order["order"]
        order_txt = (
            f"{o['order_id']}｜状态 {o['status']}（{STATUS_ZH.get(o['status'], '')}）｜司机 {o['driver']}｜"
            f"上车点 {o['pickup_point']}｜目的地 {o['destination']}｜预计 {o['eta_min']} 分钟"
        )
    return f"车辆：{json.dumps(brief, ensure_ascii=False)}\n订单：{order_txt}"


# ==================== JSON 解析 ====================


def _extract_json(text: str):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        for pat in (r"\[.*\]", r"\{.*\}"):
            m = re.search(pat, text, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:  # noqa: BLE001
                    continue
    return None


# ==================== 计划 ====================


def _validate_plan(data, tool_names: list[str]) -> list | None:
    # 归一化：dict 包裹（{"plan": [...]} / {"steps": [...]}）或单步对象 → 数组
    if isinstance(data, dict):
        for key in ("plan", "steps", "tool_calls"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data] if "tool" in data else None
    if not isinstance(data, list) or len(data) > MAX_PLAN_STEPS:
        return None
    if len(data) == 0:
        return []  # 显式空计划（因安全原因不可执行）——合法
    out = []
    seen = set()
    for i, step in enumerate(data):
        if not isinstance(step, dict):
            return None
        tool = step.get("tool")
        if tool not in tool_names:
            return None
        sid = str(step.get("id") or f"s{i + 1}")
        if sid in seen:
            return None
        seen.add(sid)
        deps = [d for d in (step.get("depends_on") or []) if d in seen and d != sid]
        out.append(
            {
                "id": sid,
                "tool": tool,
                "args": step.get("args") if isinstance(step.get("args"), dict) else {},
                "reason": str(step.get("reason", ""))[:200],
                "depends_on": deps,
            }
        )
    return out


REPAIR_CLAUSE = (
    "\n\n【上一版输出无效（为空数组之外的格式错误，或未按格式输出）】\n"
    "请重新输出：必须是 JSON 数组，且包含回答该请求所需的全部工具步骤。\n"
    '格式示例：[{"id": "s1", "tool": "play_media", "args": {"category": "轻音乐"}, '
    '"reason": "播放音乐", "depends_on": []}]'
)


def plan(
    task: str, llm, decision: dict, tools: list[dict], guardrails: bool
) -> tuple[list | None, str]:
    tool_names = [t["function"]["name"] for t in tools]
    prompt = render(
        load_prompt("plan"),
        task=task,
        tools=_tools_text(tools),
        context=_context_text(decision.get("mode", "owner")),
        mode=decision.get("mode"),
        scenes=decision.get("scenes"),
        risk=decision.get("risk"),
        safety_clause=SAFETY_CLAUSE if guardrails else "",
    )
    for attempt in (1, 2):
        raw = llm.chat(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt + (REPAIR_CLAUSE if attempt == 2 else "")},
            ],
            max_tokens=1024,
        )
        parsed = _extract_json(raw.get("content", ""))
        steps = _validate_plan(parsed, tool_names)
        if steps is not None:
            return steps, ""
    return None, "计划解析失败"


def _fallback_plan(task: str, tool_names: list[str]) -> list | None:
    """解析失败的安全兜底：用最小评估步骤保证链路可继续（而非直接降级）。"""
    for name in ("assess_risk", "search_safety_rules"):
        if name in tool_names:
            args = {"situation": task[:80]} if name == "assess_risk" else {"query": task[:80]}
            return [
                {
                    "id": "fb1",
                    "tool": name,
                    "args": args,
                    "reason": "（兜底）评估请求安全性",
                    "depends_on": [],
                }
            ]
    return None


# ==================== 执行 ====================


def _batches(steps: list[dict]) -> list[list[dict]]:
    """按依赖分批：无依赖（或依赖已完成）的步骤同批并行。"""
    done: set[str] = set()
    remaining = list(steps)
    batches = []
    while remaining:
        ready = [s for s in remaining if all(d in done for d in s["depends_on"])]
        if not ready:
            ready = [remaining[0]]  # 防御：异常依赖 → 顺序执行
        batches.append(ready)
        for s in ready:
            done.add(s["id"])
            remaining.remove(s)
    return batches


def _execute_step(step: dict, ctx_steps: dict, guardrails: bool) -> dict:
    name, args = step["tool"], dict(step["args"] or {})
    rec = {
        "step_id": step["id"],
        "tool": name,
        "args": args,
        "reason": step["reason"],
        "attempts": 0,
        "ok": False,
        "blocked": False,
        "error": "",
        "result": None,
        "verdict": None,
    }

    # L2 前置拦截
    if guardrails:
        verdict = safety.pre_check(name, args)
        if verdict.get("blocked"):
            rec.update(
                {
                    "blocked": True,
                    "ok": False,
                    "verdict": verdict,
                    "error": f"[安全拦截] {verdict['message']}",
                }
            )
            return rec

    ok_args, arg_err = impl.validate_args(name, args)
    if not ok_args:
        rec["error"] = f"[入参非法] {arg_err}"
        return rec

    ok, res, attempts = call_tool(impl.invoke, {"name": name, "args": args}, timeout=2.0, retries=1)
    rec["attempts"] = attempts
    rec["ok"] = ok
    if ok:
        rec["result"] = res
    else:
        rec["error"] = f"[调用失败] {res}"
    return rec


def execute_plan(steps: list[dict], guardrails: bool) -> list[dict]:
    records: list[dict] = []
    ctx_steps: dict = {}
    for batch in _batches(steps):
        if len(batch) == 1:
            recs = [_execute_step(batch[0], ctx_steps, guardrails)]
        else:
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                recs = list(pool.map(lambda s: _execute_step(s, ctx_steps, guardrails), batch))
        for rec in recs:
            ctx_steps[rec["step_id"]] = rec
        records.extend(recs)
    return records


# ==================== 合成与输出 ====================


def _steps_text(records: list[dict]) -> str:
    lines = []
    for r in records:
        status = "OK" if r["ok"] else ("被拦截" if r["blocked"] else "失败")
        detail = ""
        if r["ok"]:
            res = r["result"]
            if isinstance(res, list):
                detail = json.dumps(res[:3], ensure_ascii=False)[:300]
            else:
                detail = json.dumps(res, ensure_ascii=False)[:300]
        elif r["error"]:
            detail = r["error"][:200]
        lines.append(
            f"- [{r['step_id']}] {r['tool']}({json.dumps(r['args'], ensure_ascii=False)}) → {status} {detail}"
        )
    return "\n".join(lines) or "（未执行任何步骤）"


def _blocked_text(records: list[dict]) -> str:
    blocks = [r for r in records if r["blocked"]]
    if not blocks:
        return "（无）"
    return "\n".join(
        f"- {r['tool']}({json.dumps(r['args'], ensure_ascii=False)})：{r['verdict']['message']}"
        for r in blocks
    )


def synthesize(task: str, decision: dict, records: list[dict], llm, enforce: bool = True) -> dict:
    eff_risk = decision.get("risk", "low")
    if enforce:
        req_json = json.dumps(
            safety.required_outputs(eff_risk, [r for r in records if r["blocked"]]),
            ensure_ascii=False,
        )
    else:
        req_json = "（无额外合规要求）"
    prompt = render(
        load_prompt("synth"),
        task=task,
        mode=decision.get("mode"),
        scenes=decision.get("scenes"),
        risk=eff_risk,
        steps_text=_steps_text(records),
        blocked_text=_blocked_text(records),
        output_requirements=req_json,
    )
    raw = llm.chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], max_tokens=768
    )
    data = _extract_json(raw.get("content", "")) or {}
    return {
        "reply": str(data.get("reply") or "").strip(),
        "safety_tips": [str(x) for x in (data.get("safety_tips") or []) if str(x).strip()],
        "refusal_reason": str(data.get("refusal_reason") or "").strip(),
    }


def rewrite_output(
    task: str, out: dict, missing: list[str], records: list[dict], risk: str, llm
) -> dict:
    prompt = render(
        load_prompt("rewrite"),
        task=task,
        risk=risk,
        blocked_text=_blocked_text(records),
        prev_json=json.dumps(out, ensure_ascii=False),
        missing="、".join(missing),
    )
    raw = llm.chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], max_tokens=768
    )
    data = _extract_json(raw.get("content", "")) or {}
    merged = dict(out)
    if data.get("reply"):
        merged["reply"] = str(data["reply"]).strip()
    if data.get("safety_tips"):
        merged["safety_tips"] = [str(x) for x in data["safety_tips"] if str(x).strip()]
    if data.get("refusal_reason"):
        merged["refusal_reason"] = str(data["refusal_reason"]).strip()
    return merged


# ==================== 主入口 ====================


def run_scene_task(
    task: str, llm, decision: dict, *, guardrails: bool = True, planning: bool = True
) -> dict:
    """完整编排：plan → execute → synthesize → post_review（+1 次打回重写）。

    planning=False（无规划基线）：单循环直调工具；guardrails=False：关闭 L1/L2。
    """
    mode = decision.get("mode", "owner")
    tools = tools_for_mode(mode)
    result: dict = {
        "task": task,
        "decision": decision,
        "plan": None,
        "plan_error": "",
        "trace": [],
        "output": None,
        "escalated": False,
        "escalation": None,
        "compliance_missing": [],
        "max_iter_hit": False,
    }

    if planning:
        steps, err = plan(task, llm, decision, tools, guardrails)
        if steps is None:  # 双次解析失败 → 安全兜底计划（最小评估步骤，保证链路可继续）
            tool_names = [t["function"]["name"] for t in tools]
            steps = _fallback_plan(task, tool_names)
            if steps is not None:
                err = "计划解析失败（已用兜底评估计划）"
        result["plan"], result["plan_error"] = steps, err
        if steps is None:
            result["trace"] = []
            result["output"] = _degraded_output(
                task, "计划生成失败，已降级：建议重述需求或转人工客服。"
            )
            result["max_iter_hit"] = True
            return result
        records = execute_plan(steps, guardrails)
    else:
        records = _baseline_loop(task, llm, tools)
    result["trace"] = records

    # 升级人工：critical 风险或降级 → 自动转人工（guardrails 模式下）
    eff_risk = decision.get("risk", "low")
    blocked = [r for r in records if r["blocked"]]
    if guardrails and (eff_risk == "critical" or (planning and result["plan_error"])):
        esc = _auto_escalate(task, eff_risk, records)
        if esc:
            result["escalated"] = True
            result["escalation"] = esc

    # 合成 + 合规审查（空响应重试一次）
    out = synthesize(task, decision, records, llm, enforce=guardrails)
    if not (out.get("reply") or out.get("safety_tips") or out.get("refusal_reason")):
        out = synthesize(task, decision, records, llm, enforce=guardrails)
    missing = safety.post_review(out, eff_risk, blocked, result["escalated"]) if guardrails else []
    if missing:
        out = rewrite_output(task, out, missing, records, eff_risk, llm)
        missing = safety.post_review(out, eff_risk, blocked, result["escalated"])
    result["compliance_missing"] = missing

    result["output"] = _assemble_output(out, records)
    return result


def _assemble_output(out: dict, records: list[dict]) -> dict:
    return {
        "reply": out.get("reply", ""),
        "service_plan": [
            {
                "step": r["step_id"],
                "tool": r["tool"],
                "args": r["args"],
                "reason": r["reason"],
                "ok": r["ok"],
                "blocked": r["blocked"],
            }
            for r in records
        ],
        "forbidden_actions": [
            {
                "tool": r["tool"],
                "args": r["args"],
                "rule_id": (r["verdict"] or {}).get("rule_id", ""),
                "reason": (r["verdict"] or {}).get("message", ""),
            }
            for r in records
            if r["blocked"]
        ],
        "safety_tips": out.get("safety_tips", []),
        "refusal_reason": out.get("refusal_reason", ""),
    }


def _degraded_output(task: str, reason: str) -> dict:
    return {
        "reply": f"[降级] {reason}",
        "service_plan": [],
        "forbidden_actions": [],
        "safety_tips": [],
        "refusal_reason": "",
    }


def _auto_escalate(task: str, risk: str, records: list[dict]) -> dict | None:
    reason = f"场景风险等级 {risk}，自动转人工跟进：{task[:60]}"
    priority = "critical" if risk == "critical" else "urgent"
    ok, res, _ = call_tool(
        impl.invoke,
        {"name": "escalate_human", "args": {"reason": reason, "priority": priority}},
        timeout=2.0,
        retries=1,
    )
    return res if ok else None


def _baseline_loop(task: str, llm, tools: list[dict], max_iter: int = 6) -> list[dict]:
    """无规划基线：模型直接循环调用工具（不产出显式计划，不做三段式纪律约束）。"""
    messages = [
        {"role": "system", "content": SYSTEM + " 你可以调用工具完成出行服务请求。"},
        {"role": "user", "content": task},
    ]
    records: list[dict] = []
    for it in range(1, max_iter + 1):
        reply = llm.chat(messages, tools=tools)
        tcs = reply.get("tool_calls") or []
        if not tcs:
            break
        messages.append(
            {
                "role": "assistant",
                "content": reply.get("content") or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in tcs
                ],
            }
        )
        for tc in tcs:
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            rec = {
                "step_id": f"b{it}-{tc['id'][:4]}",
                "tool": tc["name"],
                "args": args,
                "reason": "（基线模式）",
                "attempts": 0,
                "ok": False,
                "blocked": False,
                "error": "",
                "result": None,
                "verdict": None,
            }
            ok_args, arg_err = impl.validate_args(tc["name"], args)
            if not ok_args:
                rec["error"] = f"[入参非法] {arg_err}"
            else:
                ok, res, attempts = call_tool(
                    impl.invoke, {"name": tc["name"], "args": args}, timeout=2.0, retries=1
                )
                rec.update(
                    {
                        "attempts": attempts,
                        "ok": ok,
                        "result": res if ok else None,
                        "error": "" if ok else f"[调用失败] {res}",
                    }
                )
            records.append(rec)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(
                        {"ok": rec["ok"], "result": rec["result"], "error": rec["error"]},
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            )
    return records
