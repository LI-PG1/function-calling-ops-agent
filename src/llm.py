"""LLM 客户端（支持 Function Calling）与离线 ScriptedLLM。"""

from __future__ import annotations

import json
import os


class LLM:
    """OpenAI 兼容 Chat 客户端（支持 tools）。环境变量：LLM_API_KEY / LLM_BASE_URL / LLM_MODEL"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 180.0,
    ):
        from openai import OpenAI

        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        self.model = model or os.getenv("LLM_MODEL", "deepseek-chat")
        if not self.api_key:
            raise RuntimeError("未配置 LLM_API_KEY（可在 .env 中设置，或用 ScriptedLLM 干跑）")
        # timeout：单请求上限 180s（防止单条失控请求挂起整轮评测）
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=timeout)

    def chat(
        self,
        messages: list,
        tools: list | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict:
        """返回 {"content": str, "tool_calls": [{"id", "name", "arguments"}]}"""
        kwargs = dict(model=self.model, messages=messages, temperature=temperature)
        if tools:
            kwargs["tools"] = tools
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        resp = self.client.chat.completions.create(**kwargs)
        m = resp.choices[0].message
        tool_calls = [
            {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
            for tc in (m.tool_calls or [])
        ]
        return {"content": m.content or "", "tool_calls": tool_calls}


class ScriptedLLM:
    """离线干跑：按预设脚本依次返回助手消息（用于链路自测）。"""

    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.calls = 0

    def chat(
        self,
        messages: list,
        tools: list | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict:
        self.calls += 1
        if self.script:
            return self.script.pop(0)
        return {"content": "[dry-run] 任务已处理完成。", "tool_calls": []}


def tool_call(call_id: str, name: str, args: dict) -> dict:
    """构造一个工具调用项的便捷函数。"""
    return {"id": call_id, "name": name, "arguments": json.dumps(args, ensure_ascii=False)}
