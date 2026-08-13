# -*- coding: utf-8 -*-
"""计划校验与依赖分批：非法计划必须被拒，依赖关系必须决定执行顺序与并行度。

这两处是把「模型输出」变成「可执行步骤」的关卡，出错会直接导致危险动作被放行
或合法任务被误杀，因此单独立测。
"""

import pytest

from src.agent.loop import MAX_PLAN_STEPS, _batches, _validate_plan

TOOLS = [
    "get_vehicle_status",
    "control_climate",
    "navigate",
    "play_media",
    "find_charging",
    "search_safety_rules",
]


# ---------------- 结构归一化 ----------------


def test_accepts_bare_array():
    plan = _validate_plan([{"tool": "get_vehicle_status"}], TOOLS)
    assert plan is not None and len(plan) == 1
    assert plan[0]["id"] == "s1"


@pytest.mark.parametrize("wrapper", ["plan", "steps", "tool_calls"])
def test_accepts_wrapped_array(wrapper):
    plan = _validate_plan(
        {wrapper: [{"tool": "navigate", "args": {"destination": "服务区"}}]}, TOOLS
    )
    assert plan is not None and len(plan) == 1
    assert plan[0]["args"]["destination"] == "服务区"


def test_accepts_single_object():
    plan = _validate_plan({"tool": "play_media", "args": {"category": "提神"}}, TOOLS)
    assert plan is not None and len(plan) == 1


# ---------------- 拒绝非法计划 ----------------


def test_rejects_unknown_tool():
    assert _validate_plan([{"tool": "launch_missile"}], TOOLS) is None


def test_rejects_non_dict_step():
    assert _validate_plan([["get_vehicle_status"]], TOOLS) is None


def test_rejects_duplicate_ids():
    plan = [
        {"id": "s1", "tool": "get_vehicle_status"},
        {"id": "s1", "tool": "navigate", "args": {"destination": "x"}},
    ]
    assert _validate_plan(plan, TOOLS) is None


def test_rejects_over_max_steps():
    steps = [{"tool": "get_vehicle_status"} for _ in range(MAX_PLAN_STEPS + 1)]
    assert _validate_plan(steps, TOOLS) is None


def test_rejects_garbage_type():
    assert _validate_plan("这不是计划", TOOLS) is None
    assert _validate_plan(42, TOOLS) is None


# ---------------- 空计划是合法的 ----------------


def test_empty_plan_allowed():
    """显式空计划代表"因安全原因不执行任何动作"，属合法输出。"""
    assert _validate_plan([], TOOLS) == []


# ---------------- 参数与依赖归一化 ----------------


def test_non_dict_args_becomes_empty_dict():
    plan = _validate_plan([{"tool": "navigate", "args": "去机场"}], TOOLS)
    assert plan[0]["args"] == {}


def test_forward_dependency_dropped():
    """依赖指向尚未出现的步骤时丢弃该依赖（防死锁），该步骤归入首批。"""
    plan = _validate_plan(
        [
            {"id": "s1", "tool": "get_vehicle_status", "depends_on": ["s2"]},
            {"id": "s2", "tool": "navigate", "args": {"destination": "x"}},
        ],
        TOOLS,
    )
    assert plan[0]["depends_on"] == []


def test_reason_truncated():
    plan = _validate_plan([{"tool": "play_media", "reason": "理由" * 200}], TOOLS)
    assert len(plan[0]["reason"]) <= 200


# ---------------- 依赖分批 ----------------


def test_independent_steps_share_one_batch():
    steps = [
        {"id": "s1", "tool": "a", "depends_on": []},
        {"id": "s2", "tool": "b", "depends_on": []},
        {"id": "s3", "tool": "c", "depends_on": []},
    ]
    batches = _batches(steps)
    assert len(batches) == 1
    assert len(batches[0]) == 3


def test_dependent_steps_split_into_sequence():
    steps = [
        {"id": "s1", "tool": "a", "depends_on": []},
        {"id": "s2", "tool": "b", "depends_on": ["s1"]},
        {"id": "s3", "tool": "c", "depends_on": ["s2"]},
    ]
    batches = _batches(steps)
    assert [len(b) for b in batches] == [1, 1, 1]
    assert [b[0]["id"] for b in batches] == ["s1", "s2", "s3"]


def test_mixed_dependencies():
    """s1 独立；s2、s3 依赖 s1（同批并行）；s4 依赖 s3。"""
    steps = [
        {"id": "s1", "tool": "a", "depends_on": []},
        {"id": "s2", "tool": "b", "depends_on": ["s1"]},
        {"id": "s3", "tool": "c", "depends_on": ["s1"]},
        {"id": "s4", "tool": "d", "depends_on": ["s3"]},
    ]
    batches = _batches(steps)
    assert [sorted(x["id"] for x in b) for b in batches] == [["s1"], ["s2", "s3"], ["s4"]]


def test_empty_steps_returns_no_batch():
    assert _batches([]) == []
