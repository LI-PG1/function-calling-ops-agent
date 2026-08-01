"""离线演示（无需 API Key）v0.2：三层路由 / 双层护栏 / 计划-执行编排 / 输出四件套 / 失败注入。

运行：python demo.py
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from mock_services import cs as mock_cs
from mock_services import orders as mock_orders
from mock_services import vehicle as mock_vehicle
from src import safety
from src.agent.loop import run_scene_task
from src.llm import ScriptedLLM
from src.reliability import call_tool
from src.router import route_rules_only, route_task
from src.tools import impl


def _reply(content: str) -> dict:
    return {"content": content, "tool_calls": []}


def demo_routing() -> None:
    print("\n=== ① 三层路由：规则快路径（毫秒级）/ LLM 场景标签 / 兜底 ===")
    fast = "我在高速上有点闷，把车门打开透透气"
    d = route_rules_only(fast)
    print(f"[快路径] {fast}\n  → path={d['path']}｜risk={d['risk']}｜{d['reason']}")

    llm = ScriptedLLM(
        [_reply('{"mode":"owner","scenes":["tired"],"risk":"high","reason":"疲劳信号"}')]
    )
    d = route_task("我有点困了", llm)
    print(
        f"[LLM 标签] 我有点困了\n  → path={d['path']}｜mode={d['mode']}｜scenes={d['scenes']}｜risk={d['risk']}"
    )

    d = route_task("今天天气怎么样", None)
    print(
        f"[兜底] 今天天气怎么样（无 LLM）\n  → path={d['path']}｜mode={d['mode']}（轻量应答，不装载工具）"
    )


def demo_guardrails() -> None:
    print("\n=== ② 双层护栏 L2：危险动作前置拦截（状态感知）===")
    cases = [
        ("highway_driving", "control_door", {"action": "open"}, "行驶中开门"),
        ("highway_driving", "control_safety", {"action": "release_seatbelt"}, "行驶中解安全带"),
        (
            "highway_driving",
            "control_safety",
            {"action": "set_cruise_speed", "value": 140},
            "巡航设到 140",
        ),
        ("child_alone", "control_climate", {"action": "off"}, "儿童独留关空调"),
        ("parked_home", "control_door", {"action": "open"}, "停车状态开门（对照）"),
    ]
    for preset, tool, args, desc in cases:
        mock_vehicle.reset(preset)
        mock_orders.reset("none")
        v = safety.pre_check(tool, args)
        tag = f"BLOCK({v['rule_id']})" if v["blocked"] else "放行"
        print(f"  [{tag:26s}] {desc}")
    mock_vehicle.reset("highway_driving")


def demo_orchestration() -> None:
    print("\n=== ③ 完整编排（ScriptedLLM 干跑）：plan → execute → synthesize → 四件套 ===")
    mock_vehicle.reset("highway_driving")  # 行驶中，电量 58%，目的地杭州
    mock_orders.reset("none")
    mock_cs.reset()
    impl.set_injection(None)

    task = "开了四个多小时了，眼皮开始打架，帮我处理一下"
    decision = {
        "mode": "owner",
        "scenes": ["tired"],
        "risk": "high",
        "reason": "疲劳驾驶信号",
        "path": "llm",
        "ms": 0.0,
    }
    plan_json = json.dumps(
        [
            {
                "id": "s1",
                "tool": "assess_risk",
                "args": {"situation": "高速行驶四小时后犯困"},
                "reason": "评估疲劳风险",
                "depends_on": [],
            },
            {
                "id": "s2",
                "tool": "navigate",
                "args": {"destination": "最近的服务区"},
                "reason": "导航至休息点",
                "depends_on": [],
            },
        ],
        ensure_ascii=False,
    )
    synth_json = json.dumps(
        {
            "reply": "检测到疲劳驾驶风险，已为您规划前往最近服务区休息；路上先帮您开点窗透透气。请务必尽快休息，安全第一。",
            "safety_tips": [
                "连续驾驶超过 4 小时属疲劳驾驶高发区间，请尽快到服务区休息 20 分钟以上"
            ],
            "refusal_reason": "",
        },
        ensure_ascii=False,
    )
    llm = ScriptedLLM([_reply(plan_json), _reply(synth_json)])

    run = run_scene_task(task, llm, decision, guardrails=True)
    print(f"任务：{task}")
    print(
        "服务计划："
        + " → ".join(f"{s['step']}·{s['tool']}" for s in (run["output"]["service_plan"] or []))
    )
    for s in run["output"]["service_plan"]:
        print(f"  [{s['step']}] {s['tool']} ok={s['ok']}｜reason: {s['reason'][:40]}")
    print(f"安全提示：{run['output']['safety_tips']}")
    print(f"回复：{run['output']['reply'][:80]}……")


def demo_guardrail_block() -> None:
    print("\n=== ④ 危险请求贯穿：L2 拦截 + 输出拒绝（要害演示）===")
    mock_vehicle.reset("highway_driving")
    mock_orders.reset("none")
    impl.set_injection(None)

    task = "我赶时间，把巡航速度设到 140"
    decision = route_rules_only(task) or {
        "mode": "owner",
        "scenes": [],
        "risk": "low",
        "reason": "",
        "path": "llm",
        "ms": 0.0,
    }
    plan_json = json.dumps(
        [
            {
                "id": "s1",
                "tool": "control_safety",
                "args": {"action": "set_cruise_speed", "value": 140},
                "reason": "按用户要求设定巡航速度",
                "depends_on": [],
            },
        ],
        ensure_ascii=False,
    )
    synth_json = json.dumps(
        {
            "reply": "抱歉，140 km/h 超过法定限速，我不能为您设定这个巡航速度。当前路况建议保持 100-120 之间。",
            "safety_tips": ["超速行驶显著增加事故风险，请遵守限速规定"],
            "refusal_reason": "请求的巡航速度（140）超过安全上限（120），已拒绝设定",
        },
        ensure_ascii=False,
    )
    llm = ScriptedLLM([_reply(plan_json), _reply(synth_json)])

    run = run_scene_task(task, llm, decision, guardrails=True)
    tr = run["trace"][0]
    print(f"任务：{task}")
    print(f"路由：path={decision['path']}｜risk={decision['risk']}")
    print("计划：control_safety(set_cruise_speed=140)")
    print(
        f"执行：blocked={tr['blocked']}｜拦截规则={tr['verdict']['rule_id']}｜{tr['verdict']['message']}"
    )
    print(f"禁止动作列表：{run['output']['forbidden_actions']}")
    print(f"回复：{run['output']['reply'][:90]}……")


def demo_reliability() -> None:
    print("\n=== ⑤ 失败注入 + 重试退避（可靠性层）===")
    impl.set_injection({"find_charging": {"mode": "error", "times": 1}})
    ok, res, attempts = call_tool(
        impl.invoke, {"name": "find_charging", "args": {}}, timeout=2.0, retries=1
    )
    print(
        f"[注入 error×1] find_charging → ok={ok}｜attempts={attempts}｜首批结果 {len(res or [])} 条"
    )
    impl.set_injection({"find_charging": {"mode": "timeout", "times": 1}})
    ok, res, attempts = call_tool(
        impl.invoke, {"name": "find_charging", "args": {}}, timeout=1.0, retries=1
    )
    print(f"[注入 timeout×1] find_charging → ok={ok}｜attempts={attempts}")
    impl.set_injection(None)

    print("\n--- 订单修改幂等（同请求重放返回首次结果）---")
    mock_orders.reset("arrived")
    r1 = impl.modify_pickup_point("ORD-2102", "南门")
    r2 = impl.modify_pickup_point("ORD-2102", "南门")
    print(f"首次：{ {k: v for k, v in r1.items() if k != 'message'} }")
    print(f"重放：{ {k: v for k, v in r2.items() if k != 'message'} }")


if __name__ == "__main__":
    print("=" * 72)
    print("出行服务编排 Agent · v0.2 离线演示（规则库 / 护栏 / 编排 / 可靠性）")
    print("=" * 72)
    demo_routing()
    demo_guardrails()
    demo_orchestration()
    demo_guardrail_block()
    demo_reliability()
    print("\n全部演示完成。真实 LLM 运行：python eval/run_tasks.py；外测：python eval/run_bfcl.py")
