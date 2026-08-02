"""外测轨：BFCL v3 子集（公开基准）→ 函数调用准确率报告。

定位：为 ops-agent 的「Function Calling / 技能注册 / 测评」提供公开基准外测对照。
数据：HF `gorilla-llm/Berkeley-Function-Calling-Leaderboard`（Apache 2.0），见 docs/数据集说明.md §3。

比对口径（**简化**，与官方 AST 全套规则不完全等价；用于项目内部对照，不对齐官方榜单）：
- simple / multiple：预期恰好 1 次调用；函数名精确匹配；参数值对「可接受值列表」归一化匹配
  （数值按数值、字符串去空白小写；缺省参数在可接受值含空值或参数非必填时放行；多余参数判错）；
- parallel / parallel_multiple：预期 N 次调用，与标准答案一一配对（顺序无关）；
- irrelevance：预期零调用。

用法：
    python eval/run_bfcl.py --cats simple multiple --limit 20     # 冒烟
    python eval/run_bfcl.py                                       # 全量（simple+multiple+parallel+parallel_multiple+irrelevance）
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
from collections import Counter

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.llm import LLM  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA = ROOT / "data" / "raw" / "bfcl"
DEFAULT_CATS = ["simple", "multiple", "parallel", "parallel_multiple", "irrelevance"]
TYPE_MAP = {
    "dict": "object",
    "float": "number",
    "list": "array",
    "tuple": "array",
    "bool": "boolean",
    "any": "string",
}


def load_jsonl(p: pathlib.Path) -> list:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------- 工具 schema 转换
def _conv_schema(node):
    """BFCL 类型（dict/float/…）→ OpenAI JSON Schema 类型；递归。"""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "type" and isinstance(v, str):
                out[k] = TYPE_MAP.get(v, v)
            else:
                out[k] = _conv_schema(v)
        return out
    if isinstance(node, list):
        return [_conv_schema(x) for x in node]
    return node


def to_openai_tools(functions: list) -> list:
    tools = []
    for f in functions:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": f["name"],
                    "description": f.get("description", ""),
                    "parameters": _conv_schema(
                        f.get("parameters") or {"type": "object", "properties": {}}
                    ),
                },
            }
        )
    return tools


# ---------------------------------------------------------------- 归一化与比对
def norm_val(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    if isinstance(v, list):
        return tuple(norm_val(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, norm_val(x)) for k, x in v.items()))
    s = str(v).strip()
    try:
        return round(float(s.replace(",", "")), 6)
    except ValueError:
        return re.sub(r"\s+", " ", s).lower()


def _omit_ok(vals: list) -> bool:
    return any((isinstance(x, str) and x == "") or x is None for x in vals)


def _flatten(v):
    """归一化 + 递归解包单元素列表（BFCL 嵌套参数每层都可能包裹 list）。"""
    while isinstance(v, list) and len(v) == 1:
        v = v[0]
    if isinstance(v, dict):
        return tuple(sorted((k, _flatten(x)) for k, x in v.items()))
    if isinstance(v, list):
        return tuple(_flatten(x) for x in v)
    return norm_val(v)


def value_ok(pred_v, vals) -> bool:
    """可接受值匹配：① 任一备选等值（嵌套递归）；② 整个备选列表按单值数组语义比较。"""
    if not isinstance(vals, list):
        vals = [vals]
    pf = _flatten(pred_v)
    for alt in vals:
        if _flatten(alt) == pf:
            return True
    return _flatten(vals) == pf


def call_ok(pred: dict, accepted: dict, req_by_name: dict | None = None) -> tuple[bool, str]:
    name = next(iter(accepted))
    if pred.get("name") != name:
        return False, f"name:{pred.get('name')}!={name}"
    acc = accepted[name]
    required = (req_by_name or {}).get(pred.get("name")) or set()
    pargs = pred.get("args") if isinstance(pred.get("args"), dict) else {}
    for p, vals in acc.items():
        if p not in pargs:
            # 省略放行：可接受值含空值；或该参数非必填（省略即取默认值）
            if not _omit_ok(vals) and p in required:
                return False, f"missing:{p}"
            continue
        pv = pargs[p]
        if isinstance(pv, str) and pv.strip() == "" and _omit_ok(vals):
            continue
        if not value_ok(pv, vals):
            return False, f"arg:{p}={pv!r}∉{vals[:3]}"
    extra = [k for k in pargs if k not in acc]
    if extra:
        return False, f"extra:{','.join(extra)}"
    return True, ""


def match_set(preds: list, golds: list, req_by_name: dict | None = None) -> tuple[bool, str]:
    """N 对 N 一一配对（回溯，n≤4）。"""
    n = len(golds)
    if len(preds) != n:
        return False, f"n_mismatch:pred={len(preds)} gold={n}"
    used = [False] * n
    fails: list[str] = []

    def rec(i: int) -> bool:
        if i == n:
            return True
        for j in range(n):
            if used[j]:
                continue
            ok, why = call_ok(preds[j], golds[i], req_by_name)
            if ok:
                used[j] = True
                if rec(i + 1):
                    return True
                used[j] = False
            else:
                fails.append(f"g{i}~p{j}:{why}")
        return False

    if rec(0):
        return True, ""
    return False, "set_no_match(" + (fails[0] if fails else "?") + ")"


def parse_pred(tc: dict) -> dict:
    try:
        args = json.loads(tc.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {"__parse_error__": tc.get("arguments")}
    return {"name": tc.get("name"), "args": args}


# ---------------------------------------------------------------- 主流程
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cats", nargs="+", default=DEFAULT_CATS)
    ap.add_argument("--limit", type=int, default=0, help="每个类别最多跑 N 条")
    ap.add_argument("--out", default="eval/report_bfcl.md")
    ap.add_argument("--details", default="eval/bfcl_details.jsonl")
    args = ap.parse_args()

    llm = LLM()
    print(
        f"[run_bfcl] 模型 {llm.model}｜类别 {args.cats}"
        + (f"｜每类 {args.limit} 条" if args.limit else "")
    )

    # 各案例标准答案长度分布（口径自检：simple/multiple 应为 1；parallel 应为 N）
    all_results = []
    t_all0 = time.time()
    for cat in args.cats:
        cases = load_jsonl(DATA / f"BFCL_v3_{cat}.json")
        if args.limit:
            cases = cases[: args.limit]
        answers = {}
        ans_fp = DATA / "possible_answer" / f"BFCL_v3_{cat}.json"
        if ans_fp.exists():
            answers = {a["id"]: a["ground_truth"] for a in load_jsonl(ans_fp)}

        lens = Counter()
        passed = 0
        for i, c in enumerate(cases, 1):
            golds = answers.get(c["id"])
            if golds:
                lens[len(golds)] += 1
            t0 = time.perf_counter()
            try:
                resp = llm.chat(c["question"][0], tools=to_openai_tools(c["function"]))
                preds = [parse_pred(tc) for tc in resp.get("tool_calls", [])]
                err = ""
            except Exception as e:  # noqa: BLE001
                preds, err = [], f"call_error:{str(e)[:80]}"
            ms = (time.perf_counter() - t0) * 1000

            req_by_name = {
                f["name"]: set((f.get("parameters") or {}).get("required") or [])
                for f in c["function"]
            }
            if cat == "irrelevance":
                ok, why = (len(preds) == 0), ("" if not preds else f"误调用:{len(preds)} 次")
            elif err:
                ok, why = False, err
            elif golds and len(golds) == 1:
                if len(preds) != 1:
                    ok, why = False, f"n_mismatch:pred={len(preds)} gold=1"
                else:
                    ok, why = call_ok(preds[0], golds[0], req_by_name)
            else:
                ok, why = match_set(preds, golds or [], req_by_name)
            passed += int(ok)
            if golds and len(golds) == 1:
                neg = [list(golds[0])[0]]
            else:
                neg = [list(g)[0] for g in (golds or [])]
            rec = {
                "id": c["id"],
                "cat": cat,
                "ok": ok,
                "why": why,
                "ms": round(ms, 1),
                "pred": [p["name"] for p in preds],
                "p_args": [p["args"] for p in preds],
                "neg": neg,
                "gold": golds,
            }
            all_results.append(rec)
            mark = "PASS" if ok else "FAIL"
            q = c["question"][0][-1]["content"]
            print(
                f"[{cat[:8]:<8s} {i:03d}/{len(cases)}] {mark} {ms:6.0f}ms "
                f"{(q[:46] if isinstance(q, str) else str(q)[:46])}"
                + ("" if ok else f"  ← {why[:60]}")
            )

        print(
            f"  -- {cat}: {passed}/{len(cases)} = {passed / max(1, len(cases)):.1%}"
            f"（答案长度分布 {dict(lens)}）"
        )

    elapsed = time.time() - t_all0
    _write_report(args, all_results, elapsed)

    det = pathlib.Path(args.details)
    if not det.is_absolute():
        det = ROOT / det
    with open(det, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_ok = sum(r["ok"] for r in all_results)
    print(
        f"\n[run_bfcl] 总体 {n_ok}/{len(all_results)} = {n_ok / max(1, len(all_results)):.1%}"
        f"｜耗时 {elapsed / 60:.1f} min"
    )


def _write_report(args, results: list, elapsed: float) -> None:
    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["cat"], []).append(r)
    n_ok = sum(r["ok"] for r in results)

    lines = [
        "# 外测报告（BFCL v3 子集 · 函数调用）",
        "",
        f"- 日期：{time.strftime('%Y-%m-%d %H:%M')}｜用例：{len(results)} 条｜总耗时：{elapsed / 60:.1f} min",
        "- 定位：**公开基准自测**（函数调用准确率）；口径为**简化比对**（见 `eval/run_bfcl.py` docstring），"
        "不对齐官方榜单数字",
        "",
        "## 总指标",
        "",
        "| 类别 | 条数 | 通过 | 通过率 |",
        "|---|---|---|---|",
    ]
    for cat in sorted(by_cat):
        rs = by_cat[cat]
        p = sum(r["ok"] for r in rs)
        lines.append(f"| {cat} | {len(rs)} | {p} | {p / len(rs):.1%} |")
    total = f"| **总体** | {len(results)} | {n_ok} | {n_ok / max(1, len(results)):.1%} |"
    lines.append(total)

    fails = [r for r in results if not r["ok"]]
    lines += ["", f"## 失败清单（共 {len(fails)}，前 20）", ""]
    if not fails:
        lines.append("（无失败）")
    else:
        lines += ["| id | 类别 | 模型调用 | 期望 | 原因 |", "|---|---|---|---|---|"]
        for r in fails[:20]:
            lines.append(
                f"| {r['id']} | {r['cat']} | {','.join(r['pred']) or '∅'} | "
                f"{','.join(r['neg'])} | {r['why'][:56]} |"
            )
    out = pathlib.Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[run_bfcl] 报告 → {out}")


if __name__ == "__main__":
    main()
