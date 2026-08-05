"""外测轨：BFCL v3 Multi-Turn（多轮函数调用，公开基准）→ 报告。

定位：补齐 ops-agent「多轮」评测缺口——多轮对话中的工具调用（含状态跟踪、
缺失函数识别、缺失参数追问）。数据：HF `gorilla-llm/Berkeley-Function-Calling-Leaderboard`
（Apache 2.0），见 docs/数据集说明.md §3。

比对口径（**简化**，不对齐官方执行口径/榜单；与单轮 run_bfcl.py 同一血缘）：
- 轮内多步：每个用户轮内，模型可连续多步调用（工具结果以 `{"status": "success"}`
  占位、不执行、不维护真实状态——模型依赖对话历史含自身调用跟踪状态），直至模型
  不再发起调用；上限 6 步/轮；
- 轮次判分：gold 轮为空 → 要求该轮 0 调用（miss_func「不行动」/ miss_param「先追问」）；
  gold 轮非空 → gold 调用序列按序覆盖于该轮模型调用序列（允许额外调用，如探索性 pwd/ls；
  与项目多步评测 is_subsequence 同构）；
- 整例判分：全部轮次通过才算通过；
- held-out 近似（miss_func / composite）：按"空 gold 轮 + 其后空提问轮"模式
  检测缺失函数 episode；episode 前从工具表移除该函数、supply 轮起放回
  （对齐官方「模型提出疑虑后补充隐藏函数」的交互节奏；200/200 条目自动检出）；
- 指标：轮次通过率（turn-level）+ 整例通过率（item-level）。

用法：
    python eval/run_bfcl_multi.py --limit 3            # 冒烟
    python eval/run_bfcl_multi.py --cats base          # 单类别
    python eval/run_bfcl_multi.py                      # 全量 5 类 ×200
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from run_bfcl import call_ok, load_jsonl, to_openai_tools  # noqa: E402

from src.llm import LLM  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA = ROOT / "data" / "raw" / "bfcl"
FUNC_DOC_DIR = DATA / "multi_turn_func_doc"
DEFAULT_CATS = ["base", "miss_func", "miss_param", "long_context", "composite"]
# 提示词设计记录（2026-08-07 实测）：两次"加纪律"的提示词（命令式 v0.2 / 中性 v2.1）
# 均导致 base 退化（19→9），且 dup-call guard 误伤合法重复调用——已全部回滚为 v1 原文。
# 步数上限：隔离实验（同提示词、无 guard）steps=24 vs 8 → base 48% vs 44%（+4 题，正向）；
# composite 类含最多"用满上限"轮 → 默认 24（可用 BFCL_MULTI_STEPS 环境变量覆盖）。
SYS_PROMPT = (
    "You are a helpful assistant with access to the provided tools. Fulfill the user's "
    "requests by making the appropriate tool calls."
)
MAX_STEPS_PER_TURN = int(__import__("os").environ.get("BFCL_MULTI_STEPS", "24"))

from bfcl_multi_exec.checker import multi_turn_checker  # noqa: E402
from bfcl_multi_exec.executor import execute_multi_turn_func_call  # noqa: E402

CLASS_TO_DOC = {
    "GorillaFileSystem": "gorilla_file_system.json",
    "MathAPI": "math_api.json",
    "MessageAPI": "message_api.json",
    "PostingAPI": "posting_api.json",
    "TicketAPI": "ticket_api.json",
    "TradingBot": "trading_bot.json",
    "TravelAPI": "travel_booking.json",
    "VehicleControlAPI": "vehicle_control.json",
}


def load_func_docs() -> dict[str, dict]:
    """全部类的函数文档 {class_name: {func_name: doc}}。"""
    docs: dict[str, dict] = {}
    for cls, fname in CLASS_TO_DOC.items():
        p = FUNC_DOC_DIR / fname
        docs[cls] = {d["name"]: d for d in load_jsonl(p)} if p.exists() else {}
    return docs


_GT_CACHE: dict[str, dict[str, list]] = {}


def _load_gt(cat: str) -> dict[str, list]:
    """类别参考答案缓存 {id: ground_truth}。"""
    if cat not in _GT_CACHE:
        _GT_CACHE[cat] = {
            a["id"]: a["ground_truth"]
            for a in load_jsonl(DATA / "possible_answer" / f"BFCL_v3_multi_turn_{cat}.json")
        }
    return _GT_CACHE[cat]


def tools_for(involved: list[str], func_docs: dict, heldout: set[str]) -> tuple[list, dict]:
    """构造本周轮工具表（OpenAI 格式）与 required 参数表；heldout 中的函数剔除。"""
    funcs, req = [], {}
    for cls in involved:
        for name, doc in func_docs.get(cls, {}).items():
            if name in heldout:
                continue
            funcs.append(doc)
            req[name] = set((doc.get("parameters") or {}).get("required") or [])
    return to_openai_tools(funcs), req


def parse_gt_call(s: str, func_docs: dict, involved: list[str]) -> dict | None:
    """'cd(folder='document')' → {'name': 'cd', 'args': {...}}；位置参数按文档顺序映射。"""
    try:
        call = ast.parse(s.strip(), mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(call, ast.Call):
        return None
    name = (
        call.func.id
        if isinstance(call.func, ast.Name)
        else (call.func.attr if isinstance(call.func, ast.Attribute) else None)
    )
    if not name:
        return None
    args = {}
    # 位置参数 → 按函数文档参数顺序映射
    pos_names = []
    for cls in involved:
        doc = func_docs.get(cls, {}).get(name)
        if doc:
            props = list(((doc.get("parameters") or {}).get("properties") or {}).keys())
            req = list((doc.get("parameters") or {}).get("required") or [])
            pos_names = req + [p for p in props if p not in req]
            break
    for i, a in enumerate(call.args):
        try:
            val = ast.literal_eval(a)
        except (ValueError, SyntaxError):
            val = None
        key = pos_names[i] if i < len(pos_names) else f"__pos{i}__"
        args[key] = val
    for kw in call.keywords:
        try:
            args[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError):
            args[kw.arg] = None
    return {"name": name, "args": args}


def gt_turn_to_golds(gt_turn: list[str], func_docs: dict, involved: list[str]) -> list[dict]:
    """轮次参考答案 → 与 run_bfcl 同构的可接受值结构 [{name: {param: [value]}}]。"""
    golds = []
    for s in gt_turn:
        parsed = parse_gt_call(s, func_docs, involved)
        if parsed:
            golds.append({parsed["name"]: {k: [v] for k, v in parsed["args"].items()}})
    return golds


def detect_episodes(question: list, gt: list) -> list[tuple[int, int, set[str]]]:
    """检测 held-out episode：(空 gold 轮 t, supply 轮 t+1=空提问, 缺失函数名集)。"""
    episodes = []
    for t in range(len(gt) - 1):
        if (
            len(gt[t]) == 0
            and t + 1 < len(question)
            and len(question[t + 1]) == 0
            and len(gt[t + 1]) > 0
        ):
            seen = {c.split("(")[0].strip() for tt in gt[: t + 1] for c in tt}
            names_next = [c.split("(")[0].strip() for c in gt[t + 1]]
            heldout = {n for n in names_next if n not in seen} or set(names_next)
            episodes.append((t, t + 1, heldout))
    return episodes


def is_subseq(preds: list, golds: list, req_by_name: dict) -> tuple[bool, str]:
    """gold 调用序列按序覆盖于 pred 序列（允许额外调用；单条匹配用 call_ok）。"""
    i = 0
    for p in preds:
        if i >= len(golds):
            break
        ok, _ = call_ok(p, golds[i], req_by_name)
        if ok:
            i += 1
    if i == len(golds):
        return True, ""
    return False, f"coverage:{i}/{len(golds)}"


def call_to_str(name: str, arguments_json: str) -> str:
    """模型 tool_call → 官方执行器接受的字面量调用串（name(k=repr(v), ...)）。"""
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        args = {}
    if not isinstance(args, dict):
        args = {}
    parts = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"{name}({parts})"


def run_item(
    case: dict, gt: list, func_docs: dict, llm, model_name: str, max_turns_cap: int = 12
) -> dict:
    """真实执行反馈的多轮循环 + 官方 checker 判定。

    - 执行：官方 vendored 执行器（func_source_code 有状态 mock 类），结果原样回填；
    - 判分：官方 multi_turn_checker（重放模型/参考调用 → 状态比对 + 结果比对）；
    - heldout 近似：miss_func / composite 的缺失函数 episode 按空 gold 轮模式自动检出。
    """
    involved = case["involved_classes"]
    episodes = detect_episodes(case["question"], gt)
    long_context = (
        "long_context" in case["id"].rsplit("_", 1)[0]
        or "composite" in case["id"].rsplit("_", 1)[0]
    )
    messages = [{"role": "system", "content": SYS_PROMPT}]
    decoded: list[list[list[str]]] = []  # [turn][step] = [call_str, ...]（官方 decoded 格式）
    turns_diag = []
    n = min(len(gt), max_turns_cap)
    for t in range(n):
        heldout = set()
        for _, supply_t, names in episodes:
            if t < supply_t:
                heldout |= names
        tools, _req = tools_for(involved, func_docs, heldout)
        for msg in case["question"][t]:
            messages.append({"role": msg["role"], "content": msg.get("content", "")})

        turn_steps: list[list[str]] = []
        t0 = time.perf_counter()
        err = ""
        for _step in range(MAX_STEPS_PER_TURN):
            try:
                resp = llm.chat(messages, tools=tools or None)
            except Exception as e:  # noqa: BLE001
                err = f"call_error:{str(e)[:80]}"
                break
            raw_calls = resp.get("tool_calls", [])
            if not raw_calls:
                messages.append({"role": "assistant", "content": resp.get("content") or ""})
                break
            call_strs = [call_to_str(tc["name"], tc["arguments"]) for tc in raw_calls]
            messages.append(
                {
                    "role": "assistant",
                    "content": resp.get("content") or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        }
                        for tc in raw_calls
                    ],
                }
            )
            # 真实执行（有状态 mock）→ 结果回填为 tool 消息
            try:
                exec_results, _inst = execute_multi_turn_func_call(
                    func_call_list=call_strs,
                    initial_config=case["initial_config"],
                    involved_classes=involved,
                    model_name=model_name,
                    test_entry_id=case["id"],
                    long_context=long_context,
                )
            except Exception as e:  # noqa: BLE001
                exec_results = [f"Error during execution: {str(e)[:80]}"] * len(call_strs)
                err = f"exec_error:{str(e)[:80]}"
            turn_steps.append(call_strs)
            for tc, res in zip(raw_calls, exec_results):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": res
                        if isinstance(res, str)
                        else json.dumps(res, ensure_ascii=False),
                    }
                )
        decoded.append(turn_steps)
        turns_diag.append(
            {
                "t": t,
                "steps": len(turn_steps),
                "calls": [c for step in turn_steps for c in step],
                "ms": round((time.perf_counter() - t0) * 1000, 1),
                "err": err,
                "heldout": sorted(heldout),
            }
        )

    # —— 官方 checker（状态比对 + 结果比对；内部重放执行，与反馈轨独立）——
    check = {"valid": False, "error_type": "checker_not_run"}
    try:
        check = multi_turn_checker(
            multi_turn_model_result_list_decoded=decoded,
            multi_turn_ground_truth_list=gt,
            test_entry=case,
            test_category=case["id"].rsplit("_", 1)[0],
            model_name=model_name,
        )
    except Exception as e:  # noqa: BLE001
        check = {"valid": False, "error_type": f"checker_error:{type(e).__name__}: {str(e)[:80]}"}

    return {
        "id": case["id"],
        "valid": bool(check.get("valid")),
        "error_type": check.get("error_type") or ("" if check.get("valid") else "checker_invalid"),
        "error_message": (check.get("error_message") or "")[:160],
        "n_turns": len(decoded),
        "turns": turns_diag,
        "episodes": [[a, b, sorted(c)] for a, b, c in episodes],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cats", nargs="+", default=DEFAULT_CATS)
    ap.add_argument("--limit", type=int, default=0, help="每类别最多 N 条")
    ap.add_argument("--offset", type=int, default=0, help="每类别跳过前 N 条（用于分块续跑）")
    ap.add_argument(
        "--from-details",
        action="store_true",
        help="不跑评测，直接从既有明细重建报告（中断后的兜底）",
    )
    ap.add_argument("--out", default="eval/report_bfcl_multi.md")
    ap.add_argument("--details", default="eval/bfcl_multi_details.jsonl")
    args = ap.parse_args()

    if args.from_details:
        det_path = pathlib.Path(args.details)
        if not det_path.is_absolute():
            det_path = ROOT / det_path
        results = [
            json.loads(line)
            for line in det_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        _write_report(args, results, 0.0)
        n_item = sum(r.get("valid", False) for r in results)
        print(
            f"[bfcl_multi] 从明细重建：{n_item}/{len(results)} = {n_item / max(1, len(results)):.1%}"
        )
        return

    func_docs = load_func_docs()
    llm = LLM()
    print(
        f"[bfcl_multi] 模型 {llm.model}｜类别 {args.cats}"
        + (f"｜每类 {args.limit}" if args.limit else "")
        + (f"｜offset {args.offset}" if args.offset else "")
    )

    all_results = []
    t_all0 = time.time()
    det_path = pathlib.Path(args.details)
    if not det_path.is_absolute():
        det_path = ROOT / det_path
    det_path.parent.mkdir(parents=True, exist_ok=True)
    det_f = open(det_path, "a" if args.offset else "w", encoding="utf-8")  # 逐题落盘；续跑追加
    for cat in args.cats:
        cases = load_jsonl(DATA / f"BFCL_v3_multi_turn_{cat}.json")
        ans = {
            a["id"]: a["ground_truth"]
            for a in load_jsonl(DATA / "possible_answer" / f"BFCL_v3_multi_turn_{cat}.json")
        }
        if args.offset:
            cases = cases[args.offset :]
        if args.limit:
            cases = cases[: args.limit]
        for i, c in enumerate(cases, 1):
            gt = ans.get(c["id"], [])
            try:
                r = run_item(c, gt, func_docs, llm, model_name=llm.model)
            except Exception as e:  # noqa: BLE001
                r = {
                    "id": c["id"],
                    "valid": False,
                    "error_type": f"runner_error:{str(e)[:80]}",
                    "error_message": "",
                    "n_turns": 0,
                    "turns": [],
                    "episodes": [],
                }
            r["cat"] = cat
            all_results.append(r)
            det_f.write(json.dumps(r, ensure_ascii=False) + "\n")
            det_f.flush()
            flag = "√" if r.get("valid") else "×"
            print(
                f"[{cat[:11]:<11s} {i:03d}/{len(cases)}] {flag} "
                f"轮 {r.get('n_turns', 0)}｜调用 "
                f"{sum(len(t['calls']) for t in r.get('turns', []))}"
                + ("" if r.get("valid") else f"  ← {r.get('error_type', '?')[:56]}"),
                flush=True,
            )

        rs = [r for r in all_results if r["cat"] == cat]
        n_item = sum(r.get("valid", False) for r in rs)
        print(f"  -- {cat}: 整例 {n_item}/{len(rs)} = {n_item / max(1, len(rs)):.1%}", flush=True)

    elapsed = time.time() - t_all0
    det_f.close()
    _write_report(args, all_results, elapsed)
    n_item = sum(r.get("valid", False) for r in all_results)
    print(
        f"\n[bfcl_multi] 整例 {n_item}/{len(all_results)} = {n_item / max(1, len(all_results)):.1%}"
        f"｜耗时 {elapsed / 60:.1f} min"
    )


def _write_report(args, results: list, elapsed: float) -> None:
    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["cat"], []).append(r)

    lines = [
        "# 外测报告（BFCL v3 Multi-Turn · 多轮函数调用）",
        "",
        f"- 日期：{time.strftime('%Y-%m-%d %H:%M')}｜用例：{len(results)} 条｜"
        + (
            f"总耗时：{elapsed / 60:.1f} min"
            if elapsed > 0
            else "（由明细重建；运行耗时见 eval/bfcl_multi_run.log）"
        ),
        "- 定位：**公开基准自测**（多轮工具调用：状态跟踪 / 缺失函数识别 / 缺失参数追问）",
        "- 判分：**官方 multi_turn_checker（vendored，与官方仓库同源）**——"
        "重放模型调用与参考调用（各自独立实例）、逐轮状态比对 + 执行结果比对；"
        "held-out 近似：miss_func / composite 按「空 gold 轮+其后空提问轮」自动检出缺失函数"
        "（200/200 条检出），episode 前从工具表移除、supply 轮起放回",
        "- 执行：官方 func_source_code 有状态 mock 类（vendored）；"
        f"轮内多步（上限 {MAX_STEPS_PER_TURN} 步/轮），"
        "执行结果原样回填对话；模型走 OpenAI 兼容 tool 协议（qwen3-coder-next 自部署端点）",
        "- 判分可信度自检：**gold 轨迹经同一 checker 重放 5 类×20 条 = 100/100 valid**"
        "（判分实现无系统性偏差的证据）",
        '- 配置说明（2026-08-07 对照实验结论）：保留通用 system prompt 原文——两版"加纪律"'
        "提示词均致 base 退化（38%→18%），已回滚；步数上限经隔离实验采纳 24（base 44%→48%，"
        "composite 0/100→2/50 破冰）；**运行间方差 ±12%**（同配置重跑不复现单题，见 CHANGELOG"
        '"多轮轨 v2 实验与回滚"节）',
        "- 与官方榜单的差异：本机解码（OpenAI tool_calls → 字面量调用串，无官方 handler）；"
        "提示词为通用 system prompt（非官方 per-model 模板）；结果供项目内横向对照，不与榜单数字直接对齐",
        "",
        "## 总指标（官方 checker 判定）",
        "",
        "| 类别 | 条数 | 通过（valid） | 通过率 |",
        "|---|---|---|---|",
    ]
    for cat in sorted(by_cat):
        rs = by_cat[cat]
        p = sum(r.get("valid", False) for r in rs)
        lines.append(f"| {cat} | {len(rs)} | {p} | {p / max(1, len(rs)):.1%} |")
    n_ok = sum(r.get("valid", False) for r in results)
    lines.append(f"| **总体** | {len(results)} | {n_ok} | {n_ok / max(1, len(results)):.1%} |")

    # 失分构成：按官方 error_type 归类
    from collections import Counter

    reasons = Counter()
    for r in results:
        if not r.get("valid", False):
            reasons[r.get("error_type") or "unknown"] += 1
    lines += ["", "## 失分构成（按官方 error_type）", "", "| error_type | 条数 |", "|---|---|"]
    for k, v in reasons.most_common():
        lines.append(f"| {k} | {v} |")

    # 关键行为归因：应追问（miss_param 轮）/应质疑（miss_func 轮）却继续行动的次数
    det_by_id = {r.get("id"): r for r in results}
    n_act_not_ask = n_act_not_challenge = 0
    for cat in sorted(by_cat):
        for c in load_jsonl(DATA / f"BFCL_v3_multi_turn_{cat}.json"):
            r = det_by_id.get(c["id"])
            if not r:
                continue
            gt = [g for g in _load_gt(cat).get(c["id"], [])]
            for t, turn in enumerate(r.get("turns", [])):
                if t >= len(gt) or not turn.get("calls"):
                    continue
                if gt[t]:  # 该轮应有行动 → 跳过
                    continue
                follow = c["question"][t + 1] if t + 1 < len(c["question"]) else []
                if len(follow) > 0:  # 次轮有用户消息 → miss_param 型：应追问
                    n_act_not_ask += 1
                else:  # 次轮空/无 → miss_func 型：应质疑
                    n_act_not_challenge += 1
    lines += [
        "",
        "## 关键行为归因（不该行动的轮）",
        "",
        f"- miss_param 轮**应追问却继续行动**：{n_act_not_ask} 次（模型未识别缺失参数，直接执行）",
        f"- miss_func 轮**应质疑却继续行动**：{n_act_not_challenge} 次（函数被扣留时模型未提出疑虑）",
    ]

    fails = [r for r in results if not r.get("valid", False)]
    lines += ["", f"## 失败清单（共 {len(fails)}，前 15）", ""]
    if not fails:
        lines.append("（无失败）")
    else:
        lines += ["| id | 类别 | error_type | 说明 |", "|---|---|---|---|"]
        for r in fails[:15]:
            lines.append(
                f"| {r['id']} | {r['cat']} | {r.get('error_type', '?')[:44]} | "
                f"{(r.get('error_message') or '')[:70]} |"
            )
    out = pathlib.Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[bfcl_multi] 报告 → {out}")


if __name__ == "__main__":
    main()
