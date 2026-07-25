"""可靠性工程（原型）：超时 / 重试 + 指数退避 / 并发闸。

纪律第 1 条：异常向上传播——本模块不静默吞错；
失败只会被显式转换为"非结果"交回上层，由上层决定重试或降级。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError


class ToolTimeoutError(Exception):
    """工具调用超时。"""


_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool")
_SEMAPHORE = threading.Semaphore(4)  # 全局并发闸（原型值，可调）


def call_with_timeout(fn, kwargs: dict, timeout: float):
    future = _POOL.submit(fn, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as e:
        raise ToolTimeoutError(f"tool timeout > {timeout}s") from e


def call_tool(
    fn, args: dict | None = None, timeout: float = 2.0, retries: int = 1, backoff: float = 0.5
):
    """带超时/重试/退避/并发闸的工具调用。

    返回 (ok, result_or_error_message, attempts)。
    全部失败后返回 ok=False（由上层决定降级）。
    """
    args = args or {}
    attempts = 0
    last_err = ""
    for attempt in range(1, retries + 2):
        attempts = attempt
        with _SEMAPHORE:
            try:
                return True, call_with_timeout(fn, args, timeout), attempts
            except Exception as e:  # noqa: BLE001 —— 捕获后作为"非结果"重试，绝不静默吞掉
                last_err = f"{type(e).__name__}: {e}"
        if attempt <= retries:
            time.sleep(backoff * (2 ** (attempt - 1)))  # 指数退避
    return False, last_err, attempts
