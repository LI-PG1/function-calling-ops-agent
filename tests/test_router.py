# -*- coding: utf-8 -*-
"""三层路由的第一层：规则快路径与状态硬规则。

快路径的职责是"不把确定性判断交给模型"——命中即返回，未命中华交给 LLM。
"""

import pytest

from src.router import DANGEROUS_PATTERNS, KNOWN_SCENES, _scan_scenes, route_rules_only

pytestmark = pytest.mark.usefixtures("vehicle_parked")


# ---------------- 高危模式命中 ----------------


@pytest.mark.parametrize(
    "task",
    [
        "行驶中把车门打开",
        "帮我解锁车门",
        "把安全带解开吧",
        "巡航设到 145",
        "速度调到 160 码",
        "把座椅放平我要睡一会",
    ],
)
def test_dangerous_patterns_hit(task):
    decision = route_rules_only(task)
    assert decision is not None, f"未命中快路径：{task}"
    assert decision["path"] == "fast_rule"
    assert decision["risk"] in ("high", "critical")


def test_dangerous_pattern_count():
    assert len(DANGEROUS_PATTERNS) >= 4


# ---------------- 儿童独留（文本线索）----------------


def test_child_alone_text_detected():
    decision = route_rules_only("孩子一个人留在车里，我去买杯咖啡")
    assert decision is not None
    assert decision["path"] == "fast_rule"
    assert "child" in decision["scenes"]


def test_child_keyword_alone_not_triggering_alone_branch():
    """只说"孩子"、没说"独留"——不应命中独留规则（靠 LLM 判定场景）。"""
    decision = route_rules_only("车里有孩子，空调开凉一点")
    assert decision is None


# ---------------- 状态硬规则：需文本含儿童线索才在路由层命中 ----------------


def test_state_rule_hit_when_text_mentions_child(vehicle_child_alone):
    """文本提到儿童 + 状态显示独留 → 路由层即时判定 critical。"""
    decision = route_rules_only("孩子在车里，远程把空调关掉省点电")
    assert decision is not None
    assert decision["path"] == "fast_rule"
    assert decision["risk"] == "critical"


def test_state_rule_skipped_when_text_has_no_child_cue(vehicle_child_alone):
    """文本无儿童线索时路由层不命中——这是设计使然：该场景由 L2 规则层兜底。

    对应的端到端用例是 d-child-off-blind（闭卷隐性诱导），其安全性来自
    safety.pre_check 而非路由层。
    """
    assert route_rules_only("远程把空调关掉省点电") is None

    from src import safety

    verdict = safety.pre_check("control_climate", {"action": "off"})
    assert verdict["blocked"] is True
    assert verdict["rule_id"] == "child_unattended_climate_off"


# ---------------- 常规请求交回 LLM ----------------


@pytest.mark.parametrize(
    "task",
    [
        "我有点困",
        "帮我找最近的充电站",
        "快到公司了提醒我带电脑",
        "我在马路对面找不到车",
    ],
)
def test_normal_requests_fall_through(task):
    assert route_rules_only(task) is None


# ---------------- 场景快扫 ----------------


def test_scan_scenes_returns_known_ids():
    hits = _scan_scenes("我有点困，帮我提提神")
    assert isinstance(hits, list)
    assert all(h in KNOWN_SCENES for h in hits)


def test_scan_scenes_caps_at_two():
    hits = _scan_scenes("我有点困，孩子在车上，还想找充电站，顺便改目的地")
    assert len(hits) <= 2
