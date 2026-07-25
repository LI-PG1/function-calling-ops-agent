"""提示词加载与渲染（config/prompts/*.md）。"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "config" / "prompts"

SYSTEM = "你是智能出行助手（车主自驾 + Robotaxi 双模式），负责安全、可解释地完成出行服务编排。"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def render(template: str, **kwargs) -> str:
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", str(v))
    return out
