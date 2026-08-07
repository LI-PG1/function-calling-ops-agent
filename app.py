# -*- coding: utf-8 -*-
"""车机 HUD Demo —— 出行服务编排 v0.2（Streamlit）

启动：
    .venv/Scripts/streamlit run app.py

界面结构：
- 顶栏：品牌 + 模式徽章 + 车辆状态胶囊（电量 / 里程 / 位置 / 行驶态 / 乘员，实时读 mock 状态）；
- 左栏：对话流 + 三组场景快选（车主自驾 / Robotaxi 乘客 / 安全演示）+ 故障注入；
- 右栏：禁止动作横幅（有拦截时升位）→ 风险条 → 四阶段流程时间轴（识别 / 规划 / 执行 / 处置）→ 输出四件套。

真实 LLM 编排（.env → 自部署 Qwen3-Coder-Next）；Mock 数据全部虚构。
"""

from __future__ import annotations

import html
import json
import pathlib

import streamlit as st
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from mock_services import cs as mock_cs  # noqa: E402
from mock_services import orders as mock_orders  # noqa: E402
from mock_services import vehicle as mock_vehicle  # noqa: E402
from src.agent.loop import run_scene_task  # noqa: E402
from src.llm import LLM  # noqa: E402
from src.router import route_task  # noqa: E402
from src.tools import impl  # noqa: E402

# ================================================================ 常量与设计 token

# 场景快选：三组（图标, 组名, [(图标, 标签, 任务 id)]）
SCENE_GROUPS: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "directions_car",
        "车主自驾",
        [
            ("dark_mode", "疲劳驾驶", "o-tired-1"),
            ("child_care", "儿童在车", "o-child-1"),
            ("thermostat", "通勤舒适", "o-commute-1"),
            ("battery_charging_full", "长途补能", "o-long-1"),
            ("sick", "乘客不适", "o-health-1"),
        ],
    ),
    (
        "hail",
        "Robotaxi 乘客",
        [
            ("receipt_long", "查找订单", "r-lost-1"),
            ("location_on", "上车点异常", "r-pa-1"),
            ("alt_route", "改目的地", "r-dc-1"),
        ],
    ),
    (
        "gpp_bad",
        "安全演示",
        [
            ("block", "危险请求 · 拦截演示", "d-door"),
        ],
    ),
]

SCENE_ZH = {
    "tired": "疲劳",
    "child": "儿童在车",
    "longtrip": "长途",
    "commute": "通勤",
    "passenger_help": "乘客不适",
    "robotaxi_lost": "查找订单",
    "pickup_abnormal": "上车点异常",
    "dest_change": "改目的地",
}
RISK_COLOR = {"low": "#22c55e", "medium": "#eab308", "high": "#f97316", "critical": "#ef4444"}
RISK_ZH = {"low": "低风险", "medium": "中风险", "high": "高风险", "critical": "严重风险"}
MODE_ZH = {"owner": "车主模式", "robotaxi": "Robotaxi 模式", "unknown": "未识别"}
PATH_ZH = {"fast_rule": "规则快路径", "llm": "LLM 场景判定", "fallback": "兜底"}

INJECT_TOOLS = [
    "control_climate",
    "get_vehicle_status",
    "search_safety_rules",
    "navigate",
    "control_seat",
]
INJECT_MODES = {"error": "服务 500（抛错）", "timeout": "请求悬挂（超时）", "empty": "空结果"}
STEP_STATUS = {
    "ok": ("成功", "#22c55e"),
    "blocked": ("已拦截", "#ef4444"),
    "fail": ("失败", "#f59e0b"),
    "pending": ("未执行", "#64748b"),
}

CSS = """
<style>
:root {
  --bg:#0a0f1a; --panel:#111a2c; --panel-2:#0d1424; --line:#22304e; --line-2:#33507f;
  --text:#e6edf7; --dim:#8ea2c0; --accent:#38bdf8;
  --fs-xs:11px; --fs-sm:12px; --fs-md:13px; --fs-lg:15px; --fs-xl:18px; --fs-2xl:24px;
  --r-sm:8px; --r-md:12px; --r-lg:16px;
}
.stApp { background: radial-gradient(1100px 520px at 18% -8%, #14233f 0%, #0a0f1a 58%) fixed, #0a0f1a; }
header[data-testid="stHeader"] { display:none; }
section[data-testid="stSidebar"] { display:none; }
.block-container { padding-top:1.1rem; padding-bottom:2rem; max-width:1500px; }
h1,h2,h3 { color:var(--text) !important; letter-spacing:.5px; }
p,span,div,li { color:var(--text); }

/* —— 顶栏 —— */
.topbar {
  display:flex; align-items:center; gap:12px; flex-wrap:wrap;
  background:linear-gradient(180deg,#121c30 0%, #0d1424 100%);
  border:1px solid var(--line); border-radius:var(--r-md);
  padding:10px 16px; margin-bottom:12px;
}
.topbar .brand { font-size:var(--fs-xl); font-weight:800; color:#f2f7ff; letter-spacing:1px; }
.topbar .mode-chip {
  font-size:var(--fs-xs); padding:3px 10px; border-radius:999px;
  color:#7dd3fc; border:1px solid #0ea5e9; background:rgba(14,165,233,.12);
}
.topbar .states { margin-left:auto; display:flex; gap:8px; flex-wrap:wrap; }
.state-pill {
  font-size:var(--fs-xs); color:var(--dim);
  border:1px solid var(--line); border-radius:999px; padding:3px 10px;
  background:rgba(13,20,36,.7); white-space:nowrap;
}
.state-pill b { color:#dbe8fa; font-weight:600; }
.state-pill.warn { color:#fbbf24; border-color:#b45309; background:rgba(180,83,9,.15); }

/* —— 卡片体系 —— */
.hud-card {
  background:linear-gradient(180deg, var(--panel) 0%, var(--panel-2) 100%);
  border:1px solid var(--line); border-radius:var(--r-md); padding:13px 15px; margin-bottom:10px;
}
.hud-card.accent { border-color:var(--line-2); }
.card-h { font-size:var(--fs-xs); color:var(--dim); text-transform:uppercase;
  letter-spacing:1.5px; margin-bottom:8px; }
.risk-strip { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
.risk-dot { width:15px; height:15px; border-radius:50%; display:inline-block; }
.badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:var(--fs-xs);
  border:1px solid var(--line); color:var(--dim); margin-right:6px; }
.badge.on { color:#7dd3fc; border-color:#0ea5e9; background:rgba(14,165,233,.12); }
.badge.warn { color:#fbbf24; border-color:#b45309; background:rgba(180,83,9,.15); }
.badge.ok { color:#86efac; border-color:#15803d; background:rgba(21,128,61,.14); }

/* —— 禁止动作横幅（升位）—— */
.forbidden-banner {
  display:flex; align-items:flex-start; gap:10px;
  border:1px solid #b91c1c; border-left:4px solid #ef4444; border-radius:var(--r-sm);
  background:rgba(185,28,28,.16); padding:10px 12px; margin-bottom:10px;
}
.forbidden-banner .fb-icon {
  width:20px; height:20px; border-radius:50%; flex:none; margin-top:2px;
  border:2px solid #ef4444; position:relative;
}
.forbidden-banner .fb-icon:after {
  content:""; position:absolute; left:4px; top:8px; width:8px; height:2px;
  background:#ef4444; transform:rotate(-45deg);
}
.forbidden-banner .fb-title { font-size:var(--fs-md); font-weight:700; color:#fca5a5; }
.forbidden-banner .fb-item { font-size:var(--fs-sm); color:#fecaca; margin-top:2px; }
.forbidden-banner .fb-item b { color:#fff; }
.forbidden-banner .fb-item .rule { font-family:Consolas,monospace; color:#f87171; font-size:var(--fs-xs); }

/* —— 流程时间轴 —— */
.timeline { position:relative; padding-left:30px; }
.timeline:before {
  content:""; position:absolute; left:9px; top:10px; bottom:14px;
  width:2px; background:var(--line-2); border-radius:2px;
}
.tl-node { position:relative; margin-bottom:14px; }
.tl-node:last-child { margin-bottom:2px; }
.tl-dot {
  position:absolute; left:-27px; top:3px; width:14px; height:14px; border-radius:50%;
  background:var(--panel); border:2px solid var(--dim);
}
.tl-dot.done { border-color:#22c55e; }
.tl-dot.run { border-color:var(--accent); box-shadow:0 0 8px rgba(56,189,248,.5); }
.tl-dot.alert { border-color:#ef4444; }
.tl-head { display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }
.tl-head .name { font-size:var(--fs-md); font-weight:700; color:#dbe8fa; }
.tl-head .ms { font-size:var(--fs-xs); color:var(--dim); }
.tl-body { font-size:var(--fs-sm); color:var(--dim); margin-top:3px; line-height:1.55; }
.tl-body b { color:#cfe6ff; font-weight:600; }
.tl-steps { margin-top:6px; }
.step {
  border:1px solid var(--line); border-left-width:4px; border-radius:var(--r-sm);
  padding:8px 11px; margin-bottom:7px; background:rgba(13,20,36,.75);
}
.step .head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.step .sid { font-size:var(--fs-xs); color:var(--dim); font-weight:700; }
.step .tool { font-weight:700; color:#cfe6ff; font-size:var(--fs-sm); }
.step .status { margin-left:auto; font-size:var(--fs-xs); font-weight:700; }
.step .args { font-family:Consolas,monospace; font-size:var(--fs-xs); color:#9fd1ff;
  margin-top:4px; word-break:break-all; }
.step .reason { font-size:var(--fs-xs); color:var(--dim); margin-top:3px; }
.step .detail { font-size:var(--fs-xs); margin-top:4px; word-break:break-all;
  font-family:Consolas,monospace; color:#b9c8e0; }

/* —— 提示条 —— */
.tip { font-size:var(--fs-sm); padding:7px 10px; border-radius:var(--r-sm); margin:4px 0;
  background:rgba(56,189,248,.08); border:1px solid rgba(56,189,248,.25); }
.tip.danger { background:rgba(239,68,68,.1); border-color:rgba(239,68,68,.4); }
.tip.ok { background:rgba(34,197,94,.09); border-color:rgba(34,197,94,.35); }
.tip.warn { background:rgba(234,179,8,.1); border-color:rgba(234,179,8,.4); }
.kv { font-size:var(--fs-sm); color:var(--dim); margin-top:6px; }
.empty { color:var(--dim); font-size:var(--fs-sm); padding:22px 8px; text-align:center;
  border:1px dashed var(--line); border-radius:var(--r-md); }
.empty .big { font-size:var(--fs-lg); color:#cfe6ff; margin-bottom:4px; }

/* —— 按钮 —— */
div.stButton > button {
  width:100%; border-radius:var(--r-sm); border:1px solid var(--line);
  background:linear-gradient(180deg,#16233c 0%, #101a2e 100%); color:#dbe8fa;
  font-size:var(--fs-sm); padding:.5rem .4rem;
}
div.stButton > button:hover { border-color:var(--accent); color:#fff; box-shadow:0 0 12px rgba(56,189,248,.25); }
div.stButton > button.danger-btn { border-color:#b91c1c; background:rgba(185,28,28,.2); color:#fecaca; }
div.stButton > button.danger-btn:hover { border-color:#ef4444; box-shadow:0 0 12px rgba(239,68,68,.3); }
.group-h { font-size:var(--fs-xs); color:var(--dim); margin:6px 0 5px; letter-spacing:1px; }
.group-h.alert { color:#f87171; }

[data-testid="stChatMessage"] { background:rgba(17,26,44,.65); border:1px solid var(--line);
  border-radius:var(--r-md); }
.stChatInput textarea { font-size:.95rem; }
.footnote { font-size:var(--fs-xs); color:#5b6f8f; margin-top:10px; }

@media (max-width: 1200px) {
  .topbar .states { margin-left:0; width:100%; }
  .block-container { max-width:100%; }
}
</style>
"""


# ================================================================ 数据与工具函数


@st.cache_data
def load_tasks() -> dict:
    tasks = {}
    for line in (ROOT / "eval" / "tasks.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        t = json.loads(line)
        tasks[t["id"]] = t
    return tasks


@st.cache_resource
def get_llm():
    return LLM()


def reset_envs(setup: dict | None) -> None:
    setup = setup or {}
    mock_vehicle.reset(setup.get("vehicle", "parked_home"))
    mock_orders.reset(setup.get("order", "none"))
    mock_cs.reset()
    impl.set_injection(None)


def apply_injection() -> str:
    """按当前开关设置故障注入。返回状态描述文本。"""
    if not st.session_state.get("inject_on"):
        impl.set_injection(None)
        return ""
    tool = st.session_state.get("inject_tool", INJECT_TOOLS[0])
    mode = st.session_state.get("inject_mode", "error")
    times = int(st.session_state.get("inject_times", 1))
    impl.set_injection({tool: {"mode": mode, "times": times}})
    return f"已注入 {tool} ×{times}（{INJECT_MODES.get(mode, mode)}）"


def vehicle_pills() -> list[tuple[str, str, bool]]:
    """从 mock 状态生成顶栏胶囊：(标签, 值, 是否告警)。"""
    v = mock_vehicle.get_state()
    o = mock_orders.active_order()
    driving = bool(v.get("driving"))
    speed = v.get("speed_kmh", 0)
    battery = v.get("battery_pct", 0)
    loc = v.get("location")
    loc = loc.get("name", "—") if isinstance(loc, dict) else (loc or "—")
    loc = str(loc)
    if len(loc) > 18:
        loc = loc[:17] + "…"
    child = bool(v.get("child_present"))
    adults = bool(v.get("adults_present"))
    pills = [
        (
            "行驶态",
            f"{'行驶中 ' + str(speed) + 'km/h' if driving else '驻车 ' + str(v.get('gear', 'P'))}",
            driving,
        ),
        (
            "电量",
            f"{battery}% / {v.get('range_km', '—')}km",
            isinstance(battery, (int, float)) and battery < 20,
        ),
        ("位置", loc, False),
        (
            "乘员",
            "儿童独留" if child and not adults else ("有儿童" if child else "无儿童"),
            child and not adults,
        ),
        (
            "订单",
            f"{(o or {}).get('order_id', '无')} · {(o or {}).get('status', '—')}"
            if o
            else "无进行中订单",
            False,
        ),
    ]
    return pills


def execute(user_text: str, task_obj: dict | None = None) -> None:
    """执行一轮：reset（快选场景）→ 注入 → route → 编排。分阶段反馈。"""
    llm = st.session_state.get("_llm")
    if llm is None:
        st.error("LLM 未就绪：请检查 .env（LLM_API_KEY / LLM_BASE_URL / LLM_MODEL）")
        return
    if task_obj is not None:
        reset_envs(task_obj.get("setup"))
    inj = apply_injection()
    try:
        with st.status("编排中：route → plan → execute → synthesize", expanded=True) as status:
            st.write("① 识别：场景 / 身份 / 风险 …")
            decision = route_task(user_text, llm)
            st.write(
                f"　识别完成：{decision.get('path')}｜风险 {decision.get('risk')}｜{decision.get('ms', '—')} ms"
            )
            st.write("② 规划并执行 …")
            result = run_scene_task(user_text, llm, decision, guardrails=True)
            n_steps = len(result.get("plan") or [])
            st.write(f"　完成：{n_steps} 步计划；{len(result.get('trace') or [])} 条执行 trace")
            status.update(label="编排完成", state="complete", expanded=False)
    except Exception as e:  # noqa: BLE001
        st.error(f"编排异常：{str(e)[:200]}")
        return
    result["_inject"] = inj
    st.session_state.messages.append({"role": "user", "content": user_text})
    reply = (result.get("output") or {}).get("reply") or "（无回复）"
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.session_state.result = result


# ================================================================ 渲染


def _esc(x) -> str:
    return html.escape(str(x))


def render_topbar() -> None:
    has_order = mock_orders.active_order() is not None
    mode = "Robotaxi 模式" if has_order else "车主模式"
    pills = "".join(
        f'<span class="state-pill{" warn" if warn else ""}">{_esc(k)} <b>{_esc(v)}</b></span>'
        for k, v, warn in vehicle_pills()
    )
    st.markdown(
        '<div class="topbar">'
        '<span class="brand">出行服务编排</span>'
        f'<span class="mode-chip">{mode}</span>'
        f'<span class="states">{pills}</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_forbidden_banner(result: dict) -> bool:
    """禁止动作横幅：有拦截时升位渲染。返回是否渲染过。"""
    out = result.get("output") or {}
    items = []
    for fa in out.get("forbidden_actions") or []:
        rule = fa.get("rule_id") or "安全规则"
        items.append(
            f'<div class="fb-item">动作 <b>{_esc(fa.get("tool"))}</b>'
            f'<span class="rule">　{_esc(json.dumps(fa.get("args") or {}, ensure_ascii=False))}</span>'
            f'　规则 <span class="rule">{_esc(rule)}</span>　— {_esc(fa.get("reason"))}</div>'
        )
    if result.get("escalated") and result.get("escalation"):
        esc = result["escalation"]
        items.append(
            f'<div class="fb-item">已转人工：{_esc(esc.get("ticket") or esc.get("reason") or esc)}</div>'
        )
    if not items:
        return False
    st.markdown(
        '<div class="forbidden-banner"><span class="fb-icon"></span><div>'
        '<div class="fb-title">已拦截的危险动作（未执行）</div>' + "".join(items) + "</div></div>",
        unsafe_allow_html=True,
    )
    return True


def render_risk_panel(result: dict) -> None:
    d = result.get("decision") or {}
    risk = d.get("risk", "low")
    color = RISK_COLOR.get(risk, "#8ea2c0")
    scenes = "、".join(SCENE_ZH.get(s, s) for s in (d.get("scenes") or [])) or "未识别"
    chips = [
        f'<span class="badge on">{_esc(MODE_ZH.get(d.get("mode"), d.get("mode", "?")))}</span>',
        f'<span class="badge">{_esc(PATH_ZH.get(d.get("path"), d.get("path", "?")))}</span>',
        f'<span class="badge">场景：{_esc(scenes)}</span>',
    ]
    if result.get("_inject"):
        chips.append(f'<span class="badge warn">{_esc(result["_inject"])}</span>')
    st.markdown(
        f'<div class="hud-card"><div class="card-h">风险标识</div>'
        f'<div class="risk-strip">'
        f'<span class="risk-dot" style="background:{color}; box-shadow:0 0 16px {color};"></span>'
        f'<b style="color:{color}; font-size:var(--fs-lg);">{_esc(RISK_ZH.get(risk, risk))}</b>'
        f"{''.join(chips)}"
        f"</div>"
        f'<div class="kv">判定依据：{_esc(d.get("reason", "—"))}（{d.get("ms", "—")} ms）</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _step_card(step: dict, rec: dict | None) -> str:
    if rec is None:
        status, color = STEP_STATUS["pending"]
    elif rec.get("blocked"):
        status, color = STEP_STATUS["blocked"]
    elif rec.get("ok"):
        status, color = STEP_STATUS["ok"]
    else:
        status, color = STEP_STATUS["fail"]
    args = json.dumps(step.get("args") or {}, ensure_ascii=False)
    detail = ""
    if rec:
        if rec.get("ok"):
            detail = json.dumps(rec.get("result"), ensure_ascii=False, default=str)[:200]
        elif rec.get("blocked"):
            detail = (rec.get("verdict") or {}).get("message", "")
        elif rec.get("error"):
            detail = rec["error"]
        if rec.get("attempts", 0) > 1:
            detail += f"　（重试 {rec['attempts']} 次）"
    detail_html = f'<div class="detail">{_esc(detail)}</div>' if detail else ""
    return (
        f'<div class="step" style="border-left-color:{color};">'
        f'<div class="head"><span class="sid">{_esc(step["id"])}</span>'
        f'<span class="tool">{_esc(step["tool"])}</span>'
        f'<span class="status" style="color:{color};">{status}</span></div>'
        f'<div class="args">{_esc(args)}</div>'
        f'<div class="reason">意图：{_esc(step.get("reason") or "—")}</div>'
        f"{detail_html}</div>"
    )


def render_timeline(result: dict) -> None:
    """四阶段竖向时间轴：识别 / 规划 / 执行 / 处置。"""
    d = result.get("decision") or {}
    plan = result.get("plan") or []
    trace = result.get("trace") or []
    out = result.get("output") or {}
    trace_map = {r["step_id"]: r for r in trace}
    n_ok = sum(1 for r in trace if r.get("ok"))
    n_blocked = sum(1 for r in trace if r.get("blocked"))
    n_fail = len(trace) - n_ok - n_blocked

    def dot(state: str) -> str:
        cls = {"done": "done", "run": "run", "alert": "alert"}.get(state, "")
        return f'<span class="tl-dot {cls}"></span>'

    # ① 识别
    risk = d.get("risk", "low")
    rec_state = "alert" if risk in ("high", "critical") else "done"
    body = (
        f"<b>{_esc(MODE_ZH.get(d.get('mode'), '?'))}</b>｜"
        f"{_esc(PATH_ZH.get(d.get('path'), '?'))}｜"
        f"场景 {_esc('、'.join(SCENE_ZH.get(s, s) for s in (d.get('scenes') or [])) or '未识别')}｜"
        f'风险 <b style="color:{RISK_COLOR.get(risk, "#8ea2c0")};">{_esc(RISK_ZH.get(risk, risk))}</b>'
    )
    h1 = (
        f'<div class="tl-node">{dot(rec_state)}'
        f'<div class="tl-head"><span class="name">识别</span>'
        f'<span class="ms">{_esc(d.get("ms", "—"))} ms</span></div>'
        f'<div class="tl-body">{body}</div></div>'
    )

    # ② 规划
    if result.get("plan_error"):
        p_state = "alert"
        p_body = f"计划校验未通过：{_esc(result['plan_error'])}（已回落兜底计划）"
    elif plan:
        dep = sum(1 for s in plan if s.get("depends_on"))
        p_state = "done"
        p_body = f"<b>{len(plan)} 步</b>｜依赖关系 {dep} 处｜工具名与必填参数校验通过"
    else:
        p_state = "done"
        p_body = "无工具步骤（请求被拒绝或无需工具）"

    # ③ 执行
    if trace:
        e_state = "alert" if n_fail else "done"
        e_body = f"<b>{len(trace)}</b> 步：成功 {n_ok}｜拦截 {n_blocked}｜失败 {n_fail}"
        if result.get("max_iter_hit"):
            e_body += "｜<b>已触发降级（max_iter）</b>"
        steps_html = (
            (
                '<div class="tl-steps">'
                + "".join(_step_card(s, trace_map.get(s["id"])) for s in plan)
                + "</div>"
            )
            if plan
            else ""
        )
    else:
        e_state, e_body, steps_html = "run", "（本轮无工具执行）", ""

    # ④ 处置
    missing = result.get("compliance_missing") or []
    has_forbidden = bool(out.get("forbidden_actions"))
    o_state = "alert" if (missing or has_forbidden or result.get("escalated")) else "done"
    kit_names = ["回复", "服务计划", "禁止动作", "安全提示"]
    kit_html = "｜".join(
        f"<b>{k}</b> {'✓' if (k != '禁止动作' or has_forbidden) else '—'}" for k in kit_names
    )
    o_body = kit_html + (f"｜合规缺口：{_esc('、'.join(missing))}" if missing else "｜要素齐备")
    if result.get("escalated"):
        o_body += "｜已转人工"

    st.markdown(
        '<div class="hud-card accent"><div class="card-h">编排过程</div><div class="timeline">'
        + h1
        + (
            f'<div class="tl-node">{dot(p_state)}<div class="tl-head"><span class="name">规划</span></div>'
            f'<div class="tl-body">{p_body}</div></div>'
        )
        + (
            f'<div class="tl-node">{dot(e_state)}<div class="tl-head"><span class="name">执行</span></div>'
            f'<div class="tl-body">{e_body}</div>{steps_html}</div>'
        )
        + (
            f'<div class="tl-node">{dot(o_state)}<div class="tl-head"><span class="name">处置</span></div>'
            f'<div class="tl-body">{o_body}</div></div>'
        )
        + "</div></div>",
        unsafe_allow_html=True,
    )

    parts = [f"步骤 {len(trace)}", f"成功 {n_ok}", f"拦截 {n_blocked}", f"失败 {n_fail}"]
    if result.get("plan_error"):
        parts.append(f"计划修复：{result['plan_error']}")
    st.caption("　".join(parts))


def render_kit_panel(result: dict) -> None:
    out = result.get("output") or {}
    items: list[str] = []
    for tip in out.get("safety_tips") or []:
        items.append(f'<div class="tip">安全提示：{_esc(tip)}</div>')
    if out.get("refusal_reason"):
        items.append(f'<div class="tip danger">拒绝原因：{_esc(out["refusal_reason"])}</div>')
    missing = result.get("compliance_missing") or []
    if missing:
        items.append(f'<div class="tip warn">合规缺口：{_esc("、".join(missing))}</div>')
    if not items:
        items.append('<div class="tip ok">本请求无拦截、无合规缺口</div>')
    st.markdown(
        '<div class="hud-card"><div class="card-h">输出四件套（其余要素）</div>'
        + "".join(items)
        + "</div>",
        unsafe_allow_html=True,
    )


# ================================================================ 页面

st.set_page_config(
    page_title="出行服务编排 · 车机 HUD", layout="wide", initial_sidebar_state="collapsed"
)

# ---- session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "result" not in st.session_state:
    st.session_state.result = None
if "_llm" not in st.session_state:
    try:
        st.session_state._llm = get_llm()
    except Exception:  # noqa: BLE001
        st.session_state._llm = None
if "inject_on" not in st.session_state:
    st.session_state.inject_on = False

st.markdown(CSS, unsafe_allow_html=True)

# ---- 执行待处理任务 / 聊天输入（先执行，后渲染）
tasks = load_tasks()
if st.session_state.get("pending_task"):
    tid = st.session_state.get("pending_task")
    st.session_state.pending_task = None
    task = tasks.get(tid)
    if task:
        execute(task["task"], task_obj=task)

prompt = st.chat_input("输入出行请求（自由文本；点左侧场景按钮可一键载入示例）")
if prompt:
    execute(prompt)
    st.rerun()

# ---- 顶栏
render_topbar()

left, right = st.columns([0.42, 0.58], gap="medium")

# ================= 左列 =================
with left:
    st.markdown('<div class="card-h">对话</div>', unsafe_allow_html=True)
    if not st.session_state.messages:
        st.markdown(
            '<div class="empty"><div class="big">选择下方场景开始体验</div>'
            "或直接输入出行请求；右侧将展示完整编排过程</div>",
            unsafe_allow_html=True,
        )
    for msg in st.session_state.messages:
        avatar = ":material/person:" if msg["role"] == "user" else ":material/directions_car:"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    st.markdown(
        '<div class="card-h" style="margin-top:12px;">场景快选</div>', unsafe_allow_html=True
    )
    for icon, group_name, scenes in SCENE_GROUPS:
        alert = "alert" if group_name == "安全演示" else ""
        st.markdown(f'<div class="group-h {alert}">{group_name}</div>', unsafe_allow_html=True)
        cols = st.columns(3 if len(scenes) > 1 else 1)
        for i, (sicon, label, tid) in enumerate(scenes):
            with cols[i % 3]:
                if st.button(label, icon=f":material/{sicon}:", key=f"sc_{tid}"):
                    st.session_state.pending_task = tid
                    st.rerun()

    with st.expander("故障注入（演示可靠性：重试恢复 / 降级）", expanded=False):
        st.session_state.inject_on = st.toggle(
            "启用注入（下一次执行生效）", value=st.session_state.inject_on
        )
        if st.session_state.inject_on:
            st.session_state.inject_tool = st.selectbox("目标工具", INJECT_TOOLS)
            st.session_state.inject_mode = st.selectbox(
                "故障模式", list(INJECT_MODES), format_func=lambda m: INJECT_MODES[m]
            )
            st.session_state.inject_times = st.radio(
                "注入次数",
                [1, 2],
                horizontal=True,
                format_func=lambda x: "1 次 → 重试恢复" if x == 1 else "2 次 → 触发降级",
            )
            st.caption("注入在每次执行前重新装载；建议搭配「通勤舒适」或「查找订单」场景演示。")

    st.divider()
    cc1, cc2 = st.columns(2)
    with cc1:
        if st.button("重置环境", icon=":material/reset_settings:"):
            reset_envs(None)
            st.toast("已重置：车辆 parked_home / 无订单 / 注入清除")
    with cc2:
        if st.button("清空对话", icon=":material/delete:"):
            st.session_state.messages = []
            st.session_state.result = None
            st.rerun()

# ================= 右列 =================
with right:
    result = st.session_state.result
    if result is None:
        st.markdown(
            '<div class="empty"><div class="big">编排过程将在此展示</div>'
            "风险判定 → 服务计划 → 逐步执行 → 合规处置，全程可回放</div>",
            unsafe_allow_html=True,
        )
    else:
        has_forbidden = render_forbidden_banner(result)
        render_risk_panel(result)
        render_timeline(result)
        if not has_forbidden:
            render_kit_panel(result)

st.markdown(
    '<div class="footnote">说明：车辆 / 订单 / 客服数据均为合成 Mock；服务计划与拦截由确定性护栏产生，'
    "可逐条回放（trace 落盘于评测链路）。</div>",
    unsafe_allow_html=True,
)
