"""外测轨：API-Bank（公开基准）→ API 请求生成准确率报告。

定位：为 ops-agent 的「多轮对话 → API 调用」能力补一个公开基准外测（对话理解 +
API 选择 + 参数抽取/日期归一），见 docs/数据集说明.md §3。

数据：官方 API-Bank（Gorilla/Microsoft 系发布；本地 data/raw/api_bank/）。覆盖：
- level-1-api（399 条）：对话上下文 → 单 API 请求生成；
- level-2-api（135 条）：含 ToolSearcher 工具检索的请求生成；
- level-3-batch（245 条，零样本版）：多步轨迹逐步作答（指令 + API 盒 + 用户话术 → 该步请求）。

比对口径（**简化**，与 run_bfcl.py 同一血缘；不对齐官方脚本）：
- 从模型输出提取 `API-Request: [Name(args)]` → AST 解析；
- 单个预期调用：函数名精确匹配 + 参数值归一化匹配（数值/字符串/日期归一：常见英文日期
  → ISO；参数名对齐后多余参数判错、缺失必填判错——必填性按预期参数集推断）；
- 日期归一：'March 26, 2023' / 'Mar 26 2023' / '26 March 2023' → '2023-03-26'。

用法：
    python eval/run_api_bank.py --limit 10        # 冒烟
    python eval/run_api_bank.py --levels 1 2      # 子集
    python eval/run_api_bank.py                   # 全量（1+2+batch）
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
import time

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from run_bfcl import norm_val  # noqa: E402

from src.llm import LLM  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA = ROOT / "data" / "raw" / "api_bank"

_MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
MONTHS: dict[str, int] = {}
for _i, _m in enumerate(_MONTH_NAMES, 1):
    MONTHS[_m.lower()] = _i
    MONTHS[_m[:3].lower()] = _i

PLACEHOLDER = "User: User's utterence\nAI: AI's response"

# 系统提示：格式纪律（治"占位符回显 / 空输出 / 多余解释" 类不可解析）
SYS_PROMPT = (
    "You are a helpful AI assistant. Generate the single API request the AI should call "
    "next, based on the dialogue and API descriptions.\n"
    "Output format rules (strict):\n"
    "- Output exactly one line: `API-Request: [ApiName(key1='value1', key2='value2', ...)]`\n"
    "- Replace ApiName and every parameter with the ACTUAL names and values from the "
    "dialogue/documentation. Never output templates or placeholders such as "
    "`[ApiName(key1='value1')]`, `[token_value]`, or `{{token}}`.\n"
    "- Newlines inside a value are not allowed; keep every value on the same line.\n"
    "- For ToolSearcher, `keywords` should be a short natural-language search phrase that "
    "describes the intended task or the target API (e.g. 'delete agenda', 'query meeting')."
)


# ---------------------------------------------------------------- 归一化（含日期）
def norm_with_date(v):
    """norm_val + 日期归一：常见英文/斜杠/点格式 → ISO 'YYYY-MM-DD'（仅当完整匹配）。"""
    if isinstance(v, str):
        s = v.strip()
        m = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s)
        if m and m.group(1).lower() in MONTHS:
            return f"{int(m.group(3)):04d}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
        m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})", s)
        if m and m.group(2).lower() in MONTHS:
            return f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
        m = re.fullmatch(r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})", s)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return norm_val(v)


def flatten2(v):
    while isinstance(v, list) and len(v) == 1:
        v = v[0]
    if isinstance(v, dict):
        return tuple(sorted((k, flatten2(x)) for k, x in v.items()))
    if isinstance(v, list):
        return tuple(flatten2(x) for x in v)
    return norm_with_date(v)


def value_ok2(pred_v, vals) -> bool:
    if not isinstance(vals, list):
        vals = [vals]
    pf = flatten2(pred_v)
    for alt in vals:
        if flatten2(alt) == pf:
            return True
    return flatten2(vals) == pf


# ---------------------------------------------------------------- 提取与解析
def fix_broken_literals(s: str) -> str:
    """修复数据集/模型输出中常见的引号嵌套：`param='[..]'`（单引号把列表字面量整体裹住）
    → `param=[..]`；如 health_data='[{'name':...}]' / attendees='['a', 'b']'。"""
    return re.sub(r"='(\[.*?\])'(?=\s*[,)])", r"=\1", s or "")


def extract_api_request(text: str) -> str | None:
    """从模型输出提取 [Name(args)] 部分（含嵌套括号的正确截断）。"""
    if not text:
        return None
    m = re.search(r"API-Request:\s*(\[)", text)
    start = m.start(1) if m else text.find("[")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    return None


def parse_call_expr(s: str) -> dict | None:
    s = fix_broken_literals((s or "").strip())
    if not s:
        return None
    try:
        node = ast.parse(s, mode="eval").body
    except SyntaxError:
        return None
    if isinstance(node, ast.Tuple):  # 多调用序列：取首个调用（数据集参考均为单调用）
        node = node.elts[0] if node.elts else None
    if not isinstance(node, ast.Call):
        return None
    name = (
        node.func.id
        if isinstance(node.func, ast.Name)
        else (node.func.attr if isinstance(node.func, ast.Attribute) else None)
    )
    if not name:
        return None
    args = {}
    for i, a in enumerate(node.args):
        try:
            args[f"__pos{i}__"] = ast.literal_eval(a)
        except (ValueError, SyntaxError):
            args[f"__pos{i}__"] = None
    for kw in node.keywords:
        try:
            args[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError):
            args[kw.arg] = None
    return {"name": name, "args": args}


def parse_expected(eo: str) -> dict | None:
    inner = extract_api_request(eo)
    return parse_call_expr(inner) if inner else None


def parse_model_out(text: str) -> dict | None:
    inner = extract_api_request(text)
    return parse_call_expr(inner) if inner else None


# ---------------------------------------------------------------- keywords 柔性匹配
_STOP = {
    "the",
    "a",
    "an",
    "for",
    "of",
    "to",
    "in",
    "on",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "be",
    "with",
    "at",
    "by",
    "this",
    "that",
    "it",
    "i",
    "my",
    "me",
    "please",
    "can",
    "you",
    "do",
    "does",
    "did",
    "what",
    "when",
    "who",
    "how",
    "which",
    "get",
    "query",
    "data",
    "info",
    "information",
}


def _words(s: str) -> set[str]:
    """词袋：驼峰切分 + 小写 + 去停用词；保留数字 token。"""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(s))
    ws = re.findall(r"[a-z0-9]+", s.lower())
    return {w for w in ws if (len(w) > 1 or w.isdigit()) and w not in _STOP}


def keywords_overlap_ok(pred_v, gold_v) -> bool:
    """ToolSearcher keywords 柔性判分：开放语义文本，允许措辞差异——
    判定标准 = 双方实义词袋有交集（如 'meeting email reminder' ∩ 'QueryMeeting' = {meeting}）。
    依据：官方 L2 评测中 keywords 是自然语言检索式（见 API-Bank 论文 §4.1），
    本身无唯一正解；这里以词级语义相关性近似官方"能否检索到目标工具"。"""
    pw, gw = _words(pred_v), _words(gold_v)
    if not pw or not gw:
        return False
    return bool(pw & gw)


def call_ok2(pred: dict, gold: dict) -> tuple[bool, str]:
    if pred["name"] != gold["name"]:
        return False, f"name:{pred['name']}!={gold['name']}"
    pargs = dict(pred["args"])
    gargs = dict(gold["args"])
    # 位置参数兜底：pred 有 __posN__ 且 gold 无同名参数时，按出现顺序尝试对齐
    pos_keys = sorted(
        [k for k in pargs if k.startswith("__pos")], key=lambda x: int(x.strip("_")[3:])
    )
    if pos_keys:
        free = [k for k in gargs if k not in pargs]
        for pk, gk in zip(pos_keys, free):
            pargs[gk] = pargs.pop(pk)
    for gk, gv in gargs.items():
        if gk not in pargs:
            return False, f"missing:{gk}"
        # ToolSearcher 的 keywords 为开放语义检索式 → 柔性匹配（词袋交集）
        if pred["name"] == "ToolSearcher" and gk == "keywords":
            if not keywords_overlap_ok(pargs[gk], gv):
                return False, f"keywords:{pargs[gk]!r}≁{gv!r}"
            continue
        if not value_ok2(pargs[gk], [gv]):
            return False, f"arg:{gk}={pargs[gk]!r}≠{gv!r}"
    extra = [k for k in pargs if k not in gargs]
    if extra:
        return False, f"extra:{','.join(extra)}"
    return True, ""


# ---------------------------------------------------------------- 数据装载
def load_level(level: str, limit: int) -> list[dict]:
    """统一为 [{item_id, prompt, expected}]。"""
    out = []
    if level in ("1", "2"):
        f = DATA / f"level-{level}-api.json"
        for it in json.loads(f.read_text(encoding="utf-8")):
            instr = it["instruction"]
            prompt = (
                instr.replace(PLACEHOLDER, it["input"], 1)
                if PLACEHOLDER in instr
                else (instr + "\n" + it["input"])
            )
            out.append(
                {
                    "item_id": f"L{level}_{it['file']}#{it['id']}",
                    "prompt": prompt,
                    "expected": it["expected_output"],
                }
            )
    elif level == "batch":
        f = DATA / "level-3-batch-inf.json"
        for it in json.loads(f.read_text(encoding="utf-8")):
            prompt = it["instruction"] + "\n" + it["input"]
            out.append(
                {
                    "item_id": f"L3b_s{it['sample_id']}_a{it['api_id']}",
                    "prompt": prompt,
                    "expected": it["output"],
                }
            )
    if limit:
        out = out[:limit]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", nargs="+", default=["1", "2", "batch"], help="1 / 2 / batch")
    ap.add_argument("--limit", type=int, default=0, help="每级别最多 N 条")
    ap.add_argument("--out", default="eval/report_api_bank.md")
    ap.add_argument("--details", default="eval/api_bank_details.jsonl")
    ap.add_argument(
        "--from-details",
        action="store_true",
        help="不调模型：从既有 details 重建报告（口径/模板更新后离线刷新用）",
    )
    args = ap.parse_args()

    if args.from_details:
        det = pathlib.Path(args.details)
        if not det.is_absolute():
            det = ROOT / det
        all_results = [
            json.loads(line)
            for line in det.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        print(f"[api_bank] 从 details 重建报告：{len(all_results)} 条")
        _write_report(args, all_results, elapsed=0.0)
        n_ok = sum(r["ok"] for r in all_results)
        print(f"[api_bank] 总体 {n_ok}/{len(all_results)} = {n_ok / max(1, len(all_results)):.1%}")
        return

    llm = LLM()
    print(
        f"[api_bank] 模型 {llm.model}｜级别 {args.levels}"
        + (f"｜每级 {args.limit}" if args.limit else "")
    )

    all_results = []
    t_all0 = time.time()
    for level in args.levels:
        cases = load_level(level, args.limit)
        passed = 0
        for i, c in enumerate(cases, 1):
            t0 = time.perf_counter()
            err = ""
            try:
                resp = llm.chat(
                    [
                        {"role": "system", "content": SYS_PROMPT},
                        {"role": "user", "content": c["prompt"]},
                    ],
                    max_tokens=512,
                )
                raw = resp.get("content") or ""
                pred = parse_model_out(raw)
            except Exception as e:  # noqa: BLE001
                raw, pred, err = "", None, f"call_error:{str(e)[:80]}"
            ms = (time.perf_counter() - t0) * 1000
            gold = parse_expected(c["expected"])
            if err:
                ok, why = False, err
            elif pred is None:
                ok, why = False, "输出不可解析"
            elif gold is None:
                ok, why = False, "参考答案不可解析(数据集问题)"
            else:
                ok, why = call_ok2(pred, gold)
            passed += int(ok)
            rec = {
                "item_id": c["item_id"],
                "level": level,
                "ok": ok,
                "why": why,
                "ms": round(ms, 1),
                "pred": pred,
                "gold": gold,
                "raw": (raw or "")[:2000],
            }
            all_results.append(rec)
            mark = "PASS" if ok else "FAIL"
            print(
                f"[{level:<5s} {i:03d}/{len(cases)}] {mark} {ms:6.0f}ms "
                f"{(pred['name'] if pred else '∅')}" + ("" if ok else f"  ← {why[:60]}"),
                flush=True,
            )
        print(
            f"  -- level-{level}: {passed}/{len(cases)} = {passed / max(1, len(cases)):.1%}",
            flush=True,
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
        f"\n[api_bank] 总体 {n_ok}/{len(all_results)} = {n_ok / max(1, len(all_results)):.1%}"
        f"｜耗时 {elapsed / 60:.1f} min"
    )


def _write_report(args, results: list, elapsed: float) -> None:
    by_level: dict[str, list] = {}
    for r in results:
        by_level.setdefault(r["level"], []).append(r)

    lines = [
        "# 外测报告（API-Bank · 对话 → API 请求生成）",
        "",
        f"- 日期：{time.strftime('%Y-%m-%d %H:%M')}｜用例：{len(results)} 条"
        + (f"｜总耗时：{elapsed / 60:.1f} min" if elapsed > 0 else "｜（离线重建）"),
        "- 定位：**公开基准自测**（多轮对话理解 → API 调用生成）；口径为**简化比对**，不对齐官方脚本数字",
        "- 判分口径 v2：① `API-Request:` 提取 + AST 解析（含数据集/输出引号嵌套字面量修复）；② 日期归一（英文日期→ISO）；"
        "③ **ToolSearcher keywords 柔性匹配**——官方论文 §4.1：keywords 为开放检索式、无唯一正解（官方跑真实检索引擎判最终工具），"
        "本地以词袋交集近似「能否检索到目标工具」（含驼峰切分；翻转样本经抽样核查）",
        "- 生成侧 v2：系统提示补格式纪律（禁模板占位符回显 / 单行输出 / ToolSearcher 输出自然语言短语）",
        "- 覆盖：L1 对话→单请求（399）｜L2 ToolSearcher 请求（135）｜L3-batch 多步轨迹逐步作答（245，零样本版）",
        "",
        "## 总指标",
        "",
        "| 级别 | 条数 | 通过 | 通过率 |",
        "|---|---|---|---|",
    ]
    level_names = {"1": "L1 对话→API 请求", "2": "L2 ToolSearcher", "batch": "L3 多步轨迹（逐步）"}
    for lv in sorted(by_level, key=lambda x: {"1": 0, "2": 1, "batch": 2}[x]):
        rs = by_level[lv]
        p = sum(r["ok"] for r in rs)
        lines.append(f"| {level_names.get(lv, lv)} | {len(rs)} | {p} | {p / len(rs):.1%} |")
    n_ok = sum(r["ok"] for r in results)
    lines.append(f"| **总体** | {len(results)} | {n_ok} | {n_ok / max(1, len(results)):.1%} |")

    fails = [r for r in results if not r["ok"]]
    lines += ["", f"## 失败清单（共 {len(fails)}，前 20）", ""]
    if not fails:
        lines.append("（无失败）")
    else:
        lines += ["| 条目 | 级别 | 模型调用 | 期望 | 原因 |", "|---|---|---|---|---|"]
        for r in fails[:20]:
            pn = r["pred"]["name"] if r["pred"] else "∅"
            gn = "∅"
            if r["gold"]:
                ga = ", ".join(f"{k}={v}" for k, v in r["gold"]["args"].items())
                gn = f"{r['gold']['name']}({ga})"
            lines.append(
                f"| {r['item_id'][:34]} | {r['level']} | {pn} | {gn[:60]} | {r['why'][:50]} |"
            )
    out = pathlib.Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[api_bank] 报告 → {out}")


if __name__ == "__main__":
    main()
