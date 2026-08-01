"""拉取 ops-agent 使用的外部评测数据集（数据本体不入库；本脚本可完整重建）。

来源与用途：
1. Industrial Maintenance（Kaggle: jvachier，Apache 2.0）
   约 105 万条维护工单 + 105 万条测点标签，覆盖 37 类工业设备；抽取对应项目三个设备族的子集：
   - 压缩机 K-*    → compressor_work_orders.csv
   - 离心泵 P-*    → pump_work_orders.csv
   - 输送线 CV-*   → conveyor_work_orders.csv
   - 三类设备测点   → equipment_sensor_tags.csv
   用途：历史工单语料 / 故障描述与测点命名规范（手册与故障码体系为全虚构设计，不直接混用）。
   说明：源数据含约 10% 真实数据质量问题（大小写 / 空格 / NULL / 日期异常等）；
        本脚本对 Equipment_ID / Equipment_type 规范化后抽取；原始 zip 保留以便核对。
2. BFCL v3（HF: gorilla-llm/Berkeley-Function-Calling-Leaderboard，Apache 2.0）
   函数调用评测基准：多类别测试样例（simple / multiple / parallel / irrelevance / live / multi_turn / java /
   javascript / rest / sql）+ possible_answer 标准答案 + multi_turn_func_doc 工具文档。
   用途：技能 JSON Schema 与描述设计参照；外测子集对照函数调用准确率。
3. API-Bank（HF: liminghao1630/API-Bank，MIT）
   函数调用评测：Level-1 调用判断 / Level-2 工具检索 / Level-3 多步规划（仅测试三档，训练文件不拉取）。
   用途：技能选择 / 参数填充 / 多步规划指标对照。
4. MCPToolBench++（GitHub: mcp-tool-bench/MCPToolBenchPP，MIT）
   MCP 工具调用基准：6 类场景（browser / filesystem / search / map / pay / finance）数据 + 评测 runner + MCP 工具定义。
   用途：与"技能 JSON Schema 注册（MCP 风格）"呼应；pass^k 口径外测。

输出：data/raw/（不入库，见 .gitignore）

用法：
    python scripts/fetch_data.py                       # 拉取全部（已就绪自动跳过）
    python scripts/fetch_data.py bfcl api_bank         # 按需拉取指定数据集
    python scripts/fetch_data.py industrial --rebuild  # 强制重建工单子集
"""

from __future__ import annotations

import csv
import io
import pathlib
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import zipfile

csv.field_size_limit(1 << 20)

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"


# ================================================================ 通用工具


def _download(url: str, dest: pathlib.Path, tries: int = 3) -> pathlib.Path:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [跳过下载] {dest.name}（{dest.stat().st_size / 1e6:.1f}MB 已存在）")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    for i in range(tries):
        try:
            print(f"  [下载] {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, length=1024 * 256)
            tmp.replace(dest)
            print(f"  [完成] {dest.name}（{dest.stat().st_size / 1e6:.1f}MB）")
            return dest
        except Exception as e:  # 网络抖动重试
            print(f"  [重试 {i + 1}/{tries}] {e}")
            time.sleep(3 + i * 2)
    raise RuntimeError(f"下载失败: {url}")


def _extract(zip_path: pathlib.Path, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out_dir)


def _done(marker: pathlib.Path) -> bool:
    return marker.exists()


# ================================================================ 1) 工业维护工单子集

URL = "https://www.kaggle.com/api/v1/datasets/download/jvachier/industrial-maintenance-synthetic-dataset"
ZIP_PATH = RAW / "kaggle_industrial_maintenance.zip"
OUT = RAW / "industrial_maintenance"


def norm_id(value: str) -> str:
    """规范化设备 ID：去空白、转大写、清理首尾杂符（源数据含 ' k-01 '、'-K03' 等脏值）。"""
    s = re.sub(r"\s+", "", (value or "").strip()).upper()
    return s.strip("-_")


def is_compressor(nid: str) -> bool:
    return bool(re.match(r"^K-?\d", nid) or re.match(r"^K-+\d", nid))


def is_pump(nid: str) -> bool:
    return bool(re.match(r"^P-?\d", nid) or re.match(r"^P-+\d", nid))


def is_conveyor(nid: str) -> bool:
    return bool(re.match(r"^CV-?\d", nid) or re.match(r"^CV-+\d", nid))


WORK_ORDER_TARGETS = [
    ("compressor_work_orders.csv", is_compressor),
    ("pump_work_orders.csv", is_pump),
    ("conveyor_work_orders.csv", is_conveyor),
]

SENSOR_TYPE_CANON = {
    "compressor": "Compressor",
    "air compressor": "Air Compressor",
    "centrifugal pump": "Centrifugal Pump",
    "belt conveyor": "Belt Conveyor",
}


def canon_type(value: str) -> str | None:
    t = re.sub(r"\s+", " ", (value or "").strip().lower())
    return SENSOR_TYPE_CANON.get(t)


def extract_work_orders(zip_path: pathlib.Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    handles: dict[str, tuple] = {}
    for name, _ in WORK_ORDER_TARGETS:
        fh = open(OUT / name, "w", newline="", encoding="utf-8-sig")
        handles[name] = (fh, csv.writer(fh))
        counts[name] = 0
    with zipfile.ZipFile(zip_path) as z, z.open("maintenance.csv") as f:
        reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace"))
        header = next(reader)
        for name, _ in WORK_ORDER_TARGETS:
            handles[name][1].writerow(header)
        i_id = header.index("Equipment_ID")
        for row in reader:
            if len(row) <= i_id:
                continue
            nid = norm_id(row[i_id])
            for name, matcher in WORK_ORDER_TARGETS:
                if matcher(nid):
                    row[i_id] = nid
                    handles[name][1].writerow(row)
                    counts[name] += 1
                    break
    for name, _ in WORK_ORDER_TARGETS:
        handles[name][0].close()
    return counts


def extract_sensor_tags(zip_path: pathlib.Path) -> int:
    count = 0
    with (
        zipfile.ZipFile(zip_path) as z,
        z.open("sensor_tags.csv") as f,
        open(OUT / "equipment_sensor_tags.csv", "w", newline="", encoding="utf-8-sig") as fo,
    ):
        reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace"))
        writer = csv.writer(fo)
        header = next(reader)
        writer.writerow(header)
        i_type = header.index("Equipment_type")
        i_id = header.index("Equipment_ID")
        for row in reader:
            if len(row) <= max(i_type, i_id):
                continue
            ctype = canon_type(row[i_type])
            if not ctype:
                continue
            row[i_type] = ctype
            row[i_id] = norm_id(row[i_id])
            writer.writerow(row)
            count += 1
    return count


def fetch_industrial(rebuild: bool = False) -> None:
    done = (
        all((OUT / name).exists() for name, _ in WORK_ORDER_TARGETS)
        and (OUT / "equipment_sensor_tags.csv").exists()
    )
    if done and not rebuild:
        print("industrial: 已就绪，跳过（加 --rebuild 可强制重建）")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    zip_path = _download(URL, ZIP_PATH)
    print("  [抽取] maintenance.csv → 设备子集 ...")
    counts = extract_work_orders(zip_path)
    print("  [抽取] sensor_tags.csv → 测点标签 ...")
    n_tags = extract_sensor_tags(zip_path)
    print("  工单子集:")
    for name, _ in WORK_ORDER_TARGETS:
        print(f"    {name}: {counts[name]} 条")
    print(f"  equipment_sensor_tags.csv: {n_tags} 条")
    print(f"  输出目录: {OUT}")


# ================================================================ 2) BFCL v3（函数调用评测）

BFCL_BASE = (
    "https://hf-mirror.com/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard/resolve/main/"
)

BFCL_FILES = [
    "BFCL_v3_chatable.json",
    "BFCL_v3_exec_multiple.json",
    "BFCL_v3_exec_parallel.json",
    "BFCL_v3_exec_parallel_multiple.json",
    "BFCL_v3_exec_simple.json",
    "BFCL_v3_irrelevance.json",
    "BFCL_v3_java.json",
    "BFCL_v3_javascript.json",
    "BFCL_v3_live_irrelevance.json",
    "BFCL_v3_live_multiple.json",
    "BFCL_v3_live_parallel.json",
    "BFCL_v3_live_parallel_multiple.json",
    "BFCL_v3_live_relevance.json",
    "BFCL_v3_live_simple.json",
    "BFCL_v3_multi_turn_base.json",
    "BFCL_v3_multi_turn_composite.json",
    "BFCL_v3_multi_turn_long_context.json",
    "BFCL_v3_multi_turn_miss_func.json",
    "BFCL_v3_multi_turn_miss_param.json",
    "BFCL_v3_multiple.json",
    "BFCL_v3_parallel.json",
    "BFCL_v3_parallel_multiple.json",
    "BFCL_v3_rest.json",
    "BFCL_v3_simple.json",
    "BFCL_v3_sql.json",
    "README.md",
    "eval.yaml",
    "multi_turn_func_doc/gorilla_file_system.json",
    "multi_turn_func_doc/math_api.json",
    "multi_turn_func_doc/message_api.json",
    "multi_turn_func_doc/posting_api.json",
    "multi_turn_func_doc/ticket_api.json",
    "multi_turn_func_doc/trading_bot.json",
    "multi_turn_func_doc/travel_booking.json",
    "multi_turn_func_doc/vehicle_control.json",
    "possible_answer/BFCL_v3_java.json",
    "possible_answer/BFCL_v3_javascript.json",
    "possible_answer/BFCL_v3_live_multiple.json",
    "possible_answer/BFCL_v3_live_parallel.json",
    "possible_answer/BFCL_v3_live_parallel_multiple.json",
    "possible_answer/BFCL_v3_live_simple.json",
    "possible_answer/BFCL_v3_multi_turn_base.json",
    "possible_answer/BFCL_v3_multi_turn_composite.json",
    "possible_answer/BFCL_v3_multi_turn_long_context.json",
    "possible_answer/BFCL_v3_multi_turn_miss_func.json",
    "possible_answer/BFCL_v3_multi_turn_miss_param.json",
    "possible_answer/BFCL_v3_multiple.json",
    "possible_answer/BFCL_v3_parallel.json",
    "possible_answer/BFCL_v3_parallel_multiple.json",
    "possible_answer/BFCL_v3_simple.json",
    "possible_answer/BFCL_v3_sql.json",
]


def fetch_bfcl(rebuild: bool = False) -> None:
    """BFCL v3（Apache 2.0）：多类别函数调用测试样例 + 标准答案 + 工具文档。"""
    if _done(RAW / "bfcl" / "BFCL_v3_simple.json") and not rebuild:
        print("bfcl: 已就绪，跳过")
        return
    for rel in BFCL_FILES:
        dest = RAW / "bfcl" / rel
        if dest.exists() and dest.stat().st_size > 0:
            continue
        _download(BFCL_BASE + urllib.parse.quote(rel), dest)
    print("bfcl: 完成 ->", RAW / "bfcl")


# ================================================================ 3) API-Bank（函数调用评测）

AB_BASE = "https://hf-mirror.com/datasets/liminghao1630/API-Bank/resolve/main/"

AB_FILES = [
    "test-data/level-1-api.json",
    "test-data/level-1-response.json",
    "test-data/level-2-api.json",
    "test-data/level-2-response.json",
    "test-data/level-3.json",
    "test-data/level-3-batch-inf.json",
    "test-data/level-3-batch-inf-icl.json",
    "test-data/level-3-batch-inf-response.json",
]


def fetch_api_bank(rebuild: bool = False) -> None:
    """API-Bank 测试三档（MIT）：调用判断 / 工具检索 / 多步规划。"""
    if _done(RAW / "api_bank" / "level-1-api.json") and not rebuild:
        print("api_bank: 已就绪，跳过")
        return
    for rel in AB_FILES:
        _download(AB_BASE + rel, RAW / "api_bank" / pathlib.Path(rel).name)
    print("api_bank: 完成 ->", RAW / "api_bank")


# ================================================================ 4) MCPToolBench++（MCP 工具调用评测）


def fetch_mcptoolbench(rebuild: bool = False) -> None:
    """MCPToolBench++（MIT）：6 类 MCP 工具场景数据 + 评测 runner + 工具定义。"""
    root = RAW / "mcptoolbench" / "MCPToolBenchPP-main"
    if _done(root / "data") and not rebuild:
        print("mcptoolbench: 已就绪，跳过")
        return
    zip_path = _download(
        "https://codeload.github.com/mcp-tool-bench/MCPToolBenchPP/zip/refs/heads/main",
        RAW / "mcptoolbench" / "MCPToolBenchPP-main.zip",
    )
    _extract(zip_path, RAW / "mcptoolbench")
    print("mcptoolbench: 完成 ->", root)


# ================================================================ 入口

FETCHERS = {
    "industrial": fetch_industrial,
    "bfcl": fetch_bfcl,
    "api_bank": fetch_api_bank,
    "mcptoolbench": fetch_mcptoolbench,
}


def main() -> None:
    rebuild = "--rebuild" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or list(FETCHERS)
    unknown = [n for n in names if n not in FETCHERS]
    if unknown:
        print(f"未知数据集: {unknown}；可选: {list(FETCHERS)}")
        sys.exit(1)
    for name in names:
        print(f"\n[{name}]")
        FETCHERS[name](rebuild=rebuild)
    print("\n全部完成。数据位于 data/raw/（不入库）；用途与许可见 docs/数据集说明.md。")


if __name__ == "__main__":
    main()
