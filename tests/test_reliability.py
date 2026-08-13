# -*- coding: utf-8 -*-
"""可靠性层：超时、重试、指数退避、并发闸。

纪律：失败必须显式返回（ok=False），不得静默吞掉。
"""

import time

import pytest

from src.reliability import ToolTimeoutError, call_tool, call_with_timeout


def test_success_first_attempt():
    ok, result, attempts = call_tool(lambda x: x * 2, {"x": 3})
    assert (ok, result, attempts) == (True, 6, 1)


def test_retry_then_success():
    """首次抛错，第二次成功——重试必须真的发生且记录尝试次数。"""
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("mock 服务暂不可用")
        return "ok"

    ok, result, attempts = call_tool(flaky, retries=2, backoff=0.01)
    assert ok is True
    assert result == "ok"
    assert attempts == 2
    assert calls["n"] == 2


def test_all_retries_fail_returns_error():
    def always_fail():
        raise RuntimeError("服务持续报错")

    ok, err, attempts = call_tool(always_fail, retries=2, backoff=0.01)
    assert ok is False
    assert "服务持续报错" in err
    assert attempts == 3  # 1 次初试 + 2 次重试


def test_no_retry_when_retries_zero():
    def always_fail():
        raise RuntimeError("x")

    ok, _, attempts = call_tool(always_fail, retries=0)
    assert ok is False
    assert attempts == 1


def test_timeout_raises_tool_timeout_error():
    def slow():
        time.sleep(1.0)
        return "done"

    with pytest.raises(ToolTimeoutError):
        call_with_timeout(slow, {}, timeout=0.1)


def test_timeout_triggers_retry():
    """超时也要走重试路径（与异常同等对待），最终如实返回失败。"""
    calls = {"n": 0}

    def slow_once():
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(0.5)
        return "done"

    ok, result, attempts = call_tool(slow_once, timeout=0.1, retries=1, backoff=0.01)
    assert ok is True and result == "done"
    assert attempts == 2


def test_backoff_is_exponential():
    """退避时间应递增：总耗时 ≥ backoff*(2^0 + 2^1)。"""

    def always_fail():
        raise RuntimeError("x")

    start = time.monotonic()
    call_tool(always_fail, retries=2, backoff=0.05)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.05 * (1 + 2) * 0.9  # 留 10% 计时误差
