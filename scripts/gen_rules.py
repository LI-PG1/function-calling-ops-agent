"""场景规则库渲染：config/safety_rules.yaml → 可检索文档。

产出：
- data/rules/index.json   结构化条目（供 search_safety_rules 检索）
- data/rules/scenes.md    8 场景策略文档（人读）
- data/rules/guardrails.md 护栏规则文档（人读）

运行：python scripts/gen_rules.py
"""

from __future__ import annotations

import json
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "config" / "safety_rules.yaml"
OUT_DIR = ROOT / "data" / "rules"


def main() -> None:
    cfg = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []

    # ---- 场景条目 ----
    scene_lines = [
        f"# 场景规则库（v{cfg.get('version')}）",
        "",
        "> 合成体系，不对应任何真实厂商。",
        "",
    ]
    for s in cfg.get("scenes", []):
        text = (
            f"场景：{s['name']}（{s['id']}）。风险等级：{s['risk']}。"
            f"处置策略：{'、'.join(s.get('strategy', []))}。"
            f"处置要点：{s.get('handling', '')}"
        )
        entries.append(
            {
                "id": f"scene:{s['id']}",
                "kind": "scene",
                "title": f"{s['name']}（{s['id']}）",
                "risk": s["risk"],
                "strategy": s.get("strategy", []),
                "must_output": s.get("must_output", []),
                "keywords": s.get("keywords", []),
                "text": text,
            }
        )
        scene_lines += [
            f"## {s['name']}（{s['id']}）",
            f"- 关键词：{'、'.join(s.get('keywords', []))}",
            f"- 风险等级：{s['risk']}｜策略：{'、'.join(s.get('strategy', []))}",
            f"- 处置要点：{s.get('handling', '')}",
            "",
        ]

    # ---- 护栏条目 ----
    g_lines = [f"# 危险动作拦截规则（pre_check · v{cfg.get('version')}）", ""]
    for r in cfg.get("pre_check", []):
        checks = []
        for c in r.get("arg_checks", []):
            if "in" in c:
                checks.append(f"参数 {c['path']} ∈ {c['in']}")
            else:
                op = next((k for k in ("gt", "gte", "lt", "lte", "eq") if k in c), "")
                checks.append(f"参数 {c['path']} {op} {c.get(op)}")
        for c in r.get("state_checks", []):
            checks.append(f"状态 {c['source']}.{c['path']} == {c.get('eq')}")
        text = (
            f"拦截规则：{r['desc']}。触发条件：{'；'.join(checks)}。"
            f"策略：{r.get('strategy', 'refuse')}。提示：{r.get('message', '')}"
        )
        entries.append(
            {
                "id": f"guard:{r['id']}",
                "kind": "pre_check",
                "title": r["desc"],
                "risk": "high",
                "strategy": [r.get("strategy", "refuse")],
                "must_output": r.get("must_output", []),
                "keywords": [r["desc"], r["id"]],
                "text": text,
            }
        )
        g_lines += [
            f"## {r['desc']}（{r['id']}）",
            f"- 条件：{'；'.join(checks)}",
            f"- 提示：{r.get('message', '')}",
            "",
        ]

    (OUT_DIR / "index.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (OUT_DIR / "scenes.md").write_text("\n".join(scene_lines), encoding="utf-8")
    (OUT_DIR / "guardrails.md").write_text("\n".join(g_lines), encoding="utf-8")

    print(
        f"[gen_rules] v{cfg.get('version')} → {len(entries)} 条目（scenes={len(cfg.get('scenes', []))} / pre_check={len(cfg.get('pre_check', []))}）"
    )
    print(f"[gen_rules] 输出: {OUT_DIR / 'index.json'}, scenes.md, guardrails.md")


if __name__ == "__main__":
    main()
