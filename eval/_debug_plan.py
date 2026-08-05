# ruff: noqa: E402 —— sys.path 注入先于导入，脚本专用
"""计划诊断：对指定任务重放路由 + 计划，打印原始 LLM 输出（定位解析/规划问题）。

用法：python eval/_debug_plan.py o-commute-1 [o-park-1 ...]
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parents[1] / ".env")

from mock_services import orders as mock_orders
from mock_services import vehicle as mock_vehicle
from src.agent import loop as agent_loop
from src.llm import LLM
from src.prompts import SYSTEM, load_prompt, render
from src.router import route_task
from src.tools import impl
from src.tools.spec import tools_for_mode

ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKS = {
    json.loads(line)["id"]: json.loads(line)
    for line in (ROOT / "eval" / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
}


def probe(tid: str, llm: LLM) -> None:
    task = TASKS[tid]
    setup = task.get("setup") or {}
    mock_vehicle.reset(setup.get("vehicle", "parked_home"))
    mock_orders.reset(setup.get("order", "none"))
    impl.set_injection(None)
    print("=" * 100)
    print(f"[{tid}] {task['task']}")
    decision = route_task(task["task"], llm)
    print("  route:", json.dumps(decision, ensure_ascii=False))
    tools = tools_for_mode(decision.get("mode", "owner"))
    tool_names = [t["function"]["name"] for t in tools]
    print("  tools:", tool_names)
    prompt = render(
        load_prompt("plan"),
        task=task["task"],
        tools=agent_loop._tools_text(tools),
        context=agent_loop._context_text(decision.get("mode", "owner")),
        mode=decision.get("mode"),
        scenes=decision.get("scenes"),
        risk=decision.get("risk"),
        safety_clause=agent_loop.SAFETY_CLAUSE,
    )
    raw = llm.chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        max_tokens=1024,
    )
    content = raw.get("content", "")
    print(f"  RAW({len(content)} chars):", repr(content[:700]))
    parsed = agent_loop._extract_json(content)
    print("  parsed type:", type(parsed).__name__)
    steps = agent_loop._validate_plan(parsed, tool_names)
    print(
        "  validated:",
        "None（解析失败）" if steps is None else json.dumps(steps, ensure_ascii=False)[:300],
    )


if __name__ == "__main__":
    llm = LLM()
    for tid in sys.argv[1:]:
        probe(tid, llm)
