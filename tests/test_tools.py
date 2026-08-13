# -*- coding: utf-8 -*-
"""工具注册表一致性：spec（给模型看的 schema）与 impl（真实实现）必须一一对应。

这类测试防的是「模型能看见但调不通」或「能调但模型不知道」的漂移——
工具集的完整性直接决定编排能不能成功。
"""

import inspect

import pytest

from src.tools import impl
from src.tools.spec import OWNER, ROBOTAXI, SHARED, TOOLS


def _names(group):
    return [t["function"]["name"] for t in group]


# ---------------- 分组与总量 ----------------


def test_tool_groups_cover_modes():
    assert len(SHARED) == 4
    assert len(OWNER) == 8
    assert len(ROBOTAXI) == 3
    assert len(TOOLS) == 15


def test_tool_names_unique():
    names = _names(TOOLS)
    assert len(names) == len(set(names))


# ---------------- schema 规范性 ----------------


@pytest.mark.parametrize("tool", TOOLS, ids=_names(TOOLS))
def test_schema_shape(tool):
    assert tool["type"] == "function"
    fn = tool["function"]
    assert fn["name"] and isinstance(fn["name"], str)
    assert len(fn["description"]) >= 10, "描述过短会导致模型误选"
    params = fn["parameters"]
    assert params["type"] == "object"
    assert isinstance(params["properties"], dict)
    assert isinstance(params["required"], list)
    for key in params["required"]:
        assert key in params["properties"], (
            f"{fn['name']}: required 里的 {key} 未在 properties 声明"
        )


# ---------------- 实现存在性 ----------------


@pytest.mark.parametrize("name", _names(TOOLS))
def test_impl_exists(name):
    assert hasattr(impl, name), f"spec 声明了 {name} 但 impl 中无同名函数"
    fn = getattr(impl, name)
    assert callable(fn)


@pytest.mark.parametrize("name", _names(TOOLS))
def test_impl_accepts_spec_params(name):
    """schema 声明的必填参数必须出现在实现签名的形参里（否则调用必失败）。"""
    spec = next(t["function"] for t in TOOLS if t["function"]["name"] == name)
    sig = inspect.signature(getattr(impl, name))
    accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    for req in spec["parameters"]["required"]:
        if accepts_kwargs:
            continue
        assert req in sig.parameters or any(p.name == req for p in sig.parameters.values())
    # 实现必须支持 fail_mode（失败注入入口）或显式不接受
    props = spec["parameters"]["properties"]
    if "fail_mode" in props:
        assert "fail_mode" in sig.parameters, f"{name} 未透传 fail_mode"


# ---------------- 失败注入覆盖 ----------------


def test_fail_mode_supported_by_stateful_tools():
    """有状态/外部依赖的工具必须支持失败注入（可靠性演示的入口）。"""
    for name in (
        "control_climate",
        "control_door",
        "navigate",
        "find_charging",
        "query_ride_order",
    ):
        assert "fail_mode" in inspect.signature(getattr(impl, name)).parameters


def test_injection_registry_api():
    assert callable(impl.set_injection)
    impl.set_injection(None)  # 清空注入，避免污染后续用例


# ---------------- 只读工具真返回数据 ----------------


def test_get_vehicle_status_returns_state(vehicle_parked):
    state = impl.get_vehicle_status()
    assert isinstance(state, dict)
    assert "driving" in state
    assert "battery_pct" in state


def test_find_charging_returns_list(vehicle_parked):
    stations = impl.find_charging(near="上海")
    assert isinstance(stations, list)
    assert stations and "name" in stations[0]


def test_search_safety_rules_returns_hits(vehicle_parked):
    hits = impl.search_safety_rules("疲劳驾驶", top_k=3)
    assert isinstance(hits, list)
    assert hits


# ---------------- 有状态工具真改状态 ----------------


def test_control_climate_changes_state(vehicle_parked):
    impl.control_climate("cool", temp=22)
    state = vehicle_parked.get_state()
    assert state["climate"]["ac"] == "on"
    assert state["climate"]["temp"] == 22


def test_control_door_changes_state(vehicle_parked):
    impl.control_door("unlock", door="fl")
    assert vehicle_parked.get_state()["doors"]["fl"] == "unlocked"
