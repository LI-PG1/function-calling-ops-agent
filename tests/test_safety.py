# -*- coding: utf-8 -*-
"""L2 护栏规则引擎：前置拦截的条件匹配、输出合规校验、风险等级合并。

这些用例只验证规则引擎本身（读 config/safety_rules.yaml + 实时车辆/订单状态），
不依赖 LLM 与 UI。
"""

import pytest

from src import safety

pytestmark = pytest.mark.usefixtures("vehicle_parked")


# ---------------- 规则库加载 ----------------


def test_rules_load_and_version():
    rules = safety.load_rules()
    assert isinstance(rules.get("version"), int)
    assert len(rules.get("pre_check", [])) >= 7
    assert len(rules.get("scenes", [])) >= 8


def test_rule_ids_unique():
    ids = [r["id"] for r in safety.load_rules()["pre_check"]]
    assert len(ids) == len(set(ids)), "规则 id 必须唯一"


# ---------------- 行驶中动作：应拦截 ----------------


def test_block_door_unlock_while_driving(vehicle_driving):
    verdict = safety.pre_check("control_door", {"action": "unlock", "door": "fl"})
    assert verdict["blocked"] is True
    assert verdict["rule_id"] == "moving_door_open"
    assert verdict["strategy"] == "refuse"
    assert "refusal_reason" in verdict["must_output"]


def test_block_seatbelt_release_while_driving(vehicle_driving):
    verdict = safety.pre_check("control_safety", {"action": "release_seatbelt"})
    assert verdict["blocked"] is True
    assert verdict["rule_id"] == "moving_seatbelt_release"


def test_block_overspeed_setting(vehicle_driving):
    verdict = safety.pre_check("control_safety", {"action": "set_cruise_speed", "value": 145})
    assert verdict["blocked"] is True
    assert verdict["rule_id"] == "overspeed_setting"
    assert "145" not in verdict["message"] or "120" in verdict["message"]


def test_block_seat_recline_while_driving(vehicle_driving):
    verdict = safety.pre_check("control_seat", {"action": "recline", "zone": "driver"})
    assert verdict["blocked"] is True
    assert verdict["rule_id"] == "driving_seat_recline"


# ---------------- 同一动作在驻车状态下不拦截 ----------------


def test_allow_door_unlock_when_parked(vehicle_parked):
    verdict = safety.pre_check("control_door", {"action": "unlock", "door": "fl"})
    assert verdict["blocked"] is False


def test_allow_reasonable_cruise_speed(vehicle_driving):
    verdict = safety.pre_check("control_safety", {"action": "set_cruise_speed", "value": 110})
    assert verdict["blocked"] is False


# ---------------- 状态型风险：文本无害也要拦 ----------------


def test_block_ac_off_when_child_alone(vehicle_child_alone):
    """危险信号只存在于车辆状态：请求"关空调省电"本身完全无害。"""
    verdict = safety.pre_check("control_climate", {"action": "off"})
    assert verdict["blocked"] is True
    assert verdict["rule_id"] == "child_unattended_climate_off"


def test_allow_ac_off_when_no_child(vehicle_parked):
    verdict = safety.pre_check("control_climate", {"action": "off"})
    assert verdict["blocked"] is False


# ---------------- 订单前置条件 ----------------


def test_block_pickup_change_without_order(orders_none):
    verdict = safety.pre_check("modify_pickup_point", {"order_id": "ORD-9999", "point": "南门"})
    assert verdict["blocked"] is True
    assert verdict["rule_id"] == "pickup_without_order"


def test_block_destination_change_without_order(orders_none):
    verdict = safety.pre_check(
        "change_destination", {"order_id": "ORD-9999", "destination": "机场"}
    )
    assert verdict["blocked"] is True
    assert verdict["rule_id"] == "dest_without_order"


# ---------------- 无关工具不受规则影响 ----------------


@pytest.mark.parametrize(
    "tool,args",
    [
        ("get_vehicle_status", {}),
        ("search_safety_rules", {"query": "疲劳"}),
        ("play_media", {"category": "提神"}),
        ("navigate", {"destination": "服务区"}),
    ],
)
def test_unrelated_tools_not_blocked(tool, args):
    assert safety.pre_check(tool, args)["blocked"] is False


# ---------------- 输出合规 ----------------


def test_required_outputs_for_high_risk():
    req = safety.required_outputs("high", [{"rule_id": "x"}])
    assert "refusal_reason" in req
    assert "safety_tip" in req


def test_post_review_detects_missing_elements():
    missing = safety.post_review({"reply": "好的"}, "high", [{"rule_id": "x"}], False)
    assert "refusal_reason" in missing
    assert "safety_tip" in missing


def test_post_review_passes_when_complete():
    out = {
        "reply": "已拒绝",
        "refusal_reason": "行驶中解锁有风险",
        "safety_tips": ["请靠边停车后再操作"],
    }
    assert safety.post_review(out, "high", [{"rule_id": "x"}], False) == []


def test_post_review_requires_escalate_when_configured():
    req = safety.required_outputs("critical", [{"rule_id": "x"}])
    if "escalate" in req:
        missing = safety.post_review(
            {"refusal_reason": "x", "safety_tips": ["y"]}, "critical", [{"rule_id": "x"}], False
        )
        assert "escalate" in missing


# ---------------- 风险等级合并 ----------------


@pytest.mark.parametrize(
    "risks,expect",
    [
        (("low", "high"), "high"),
        (("medium", "low"), "medium"),
        (("low", "low"), "low"),
        (("critical", "high"), "critical"),
    ],
)
def test_max_risk(risks, expect):
    assert safety.max_risk(*risks) == expect
