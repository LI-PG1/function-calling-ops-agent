"""A/B 对比：多轮轨 v1（baseline）vs v2（步数 24 + 纪律提示词）。

用法：
    python eval/_ab_compare_multi.py
输出：base/composite 子集（前 50）的整例通过率对比 + 变化明细。
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(p):
    recs = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["id"]: r for r in recs}


def main() -> None:
    v1 = load(ROOT / "eval" / "archive" / "bfcl_multi_details_v1_baseline.jsonl")
    v2_path = ROOT / "eval" / "bfcl_multi_details_v2_ab.jsonl"
    if not v2_path.exists():
        print("v2 明细不存在：", v2_path)
        return
    v2 = load(v2_path)

    print(f"v1 条目 {len(v1)}｜v2 条目 {len(v2)}")
    print()
    print("| 类别 | 子集 | v1 通过 | v2 通过 | 变化 |")
    print("|---|---|---|---|---|")

    for cat in ["base", "composite", "miss_func", "miss_param", "long_context"]:
        ids = [i for i, r in v2.items() if r.get("cat") == cat]
        if not ids:
            continue
        v1_ok = sum(1 for i in ids if v1.get(i, {}).get("valid"))
        v2_ok = sum(1 for i in ids if v2.get(i, {}).get("valid"))
        delta = v2_ok - v1_ok
        sign = f"+{delta}" if delta > 0 else str(delta)
        pct1 = v1_ok / len(ids) * 100
        pct2 = v2_ok / len(ids) * 100
        print(f"| {cat} | {len(ids)} | {v1_ok}（{pct1:.0f}%） | {v2_ok}（{pct2:.0f}%） | {sign} |")

    # 变化明细
    up = [i for i in v2 if v2[i].get("valid") and not v1.get(i, {}).get("valid")]
    dn = [i for i in v2 if not v2[i].get("valid") and v1.get(i, {}).get("valid")]
    print()
    print(f"v2 新通过（{len(up)}）:", ", ".join(sorted(up)[:12]) + ("…" if len(up) > 12 else ""))
    print(f"v2 新失败（{len(dn)}）:", ", ".join(sorted(dn)[:12]) + ("…" if len(dn) > 12 else ""))

    # 步数使用
    import statistics

    steps_v1 = []
    steps_v2 = []
    for i in v2:
        if i in v1:
            steps_v1.append(sum(t.get("steps", 0) for t in v1[i].get("turns", [])))
            steps_v2.append(sum(t.get("steps", 0) for t in v2[i].get("turns", [])))
    if steps_v1:
        print()
        print(f"平均总步数 v1={statistics.mean(steps_v1):.1f} → v2={statistics.mean(steps_v2):.1f}")
        print(
            "用满 24 步的轮（v2）: "
            + str(sum(1 for i in v2 for t in v2[i].get("turns", []) if t.get("steps", 0) >= 24))
        )
        print(
            "含 dup_call_loop 的条目（v2）: "
            + str(sum(1 for i in v2 if "dup_call_loop" in str(v2[i])))
        )


if __name__ == "__main__":
    main()
