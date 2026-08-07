# -*- coding: utf-8 -*-
"""HUD demo 冒烟测试（Streamlit AppTest 无头运行）。

用法：
    .venv/Scripts/python.exe eval/_hud_smoke.py            # 渲染冒烟（不触模型）
    .venv/Scripts/python.exe eval/_hud_smoke.py --run-task # 额外：点击「通勤舒适」触发真实编排
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-task", action="store_true", help="点击场景按钮跑一轮真实编排")
    args = ap.parse_args()

    print("[1] 初始渲染（无交互）…")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    if at.exception:
        print("  × 异常:", [e.value for e in at.exception])
        sys.exit(1)
    n_btn = len(at.button)
    n_cols = len(at.columns)
    print(f"  √ 无异常｜按钮 {n_btn} 个｜列 {n_cols}｜markdown 块 {len(at.markdown)}")
    # 快选按钮 key 校验
    keys = [b.key for b in at.button]
    expect = {
        "sc_o-tired-1",
        "sc_o-child-1",
        "sc_o-commute-1",
        "sc_o-long-1",
        "sc_o-health-1",
        "sc_r-lost-1",
        "sc_r-pa-1",
        "sc_r-dc-1",
        "sc_d-door",
    }
    missing = expect - set(keys)
    print(
        f"  快选按钮：{len(expect & set(keys))}/{len(expect)}"
        + (f"（缺 {missing}）" if missing else "")
    )

    if not args.run_task:
        print("[2] 跳过真实编排（--run-task 开启）")
        return

    print("[2] 点击「通勤舒适」→ 真实编排（route → plan → execute → synthesize）…")
    at.button(key="sc_o-commute-1").click().run(timeout=180)
    if at.exception:
        print("  × 异常:", [e.value for e in at.exception])
        sys.exit(1)
    result = at.session_state.get("result")
    msgs = at.session_state.get("messages") or []
    assert result is not None, "result 未写入 session_state"
    plan = result.get("plan") or []
    trace = result.get("trace") or []
    out = result.get("output") or {}
    print(f"  √ 本轮完整：消息 {len(msgs)} 条｜计划 {len(plan)} 步｜执行 {len(trace)} 条")
    print(
        f"    决策：mode={result['decision'].get('mode')} risk={result['decision'].get('risk')} "
        f"path={result['decision'].get('path')}"
    )
    print(f"    reply：{(out.get('reply') or '')[:80]}")
    ok_steps = [(t["step_id"], t["tool"], t["ok"], t["blocked"]) for t in trace]
    print(f"    执行明细：{ok_steps}")

    print("[3] 危险请求演示（d-door）…")
    at.button(key="sc_d-door").click().run(timeout=180)
    if at.exception:
        print("  × 异常:", [e.value for e in at.exception])
        sys.exit(1)
    result2 = at.session_state.get("result")
    out2 = result2.get("output") or {}
    print(
        f"    决策：risk={result2['decision'].get('risk')} path={result2['decision'].get('path')}"
    )
    print(f"    reply：{(out2.get('reply') or '')[:80]}")
    print(f"    拦截：{out2.get('forbidden_actions')}")
    print(f"    安全提示：{out2.get('safety_tips')}")
    print("完成。")


if __name__ == "__main__":
    main()
