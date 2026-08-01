"""合成设备手册生成器：产出 data/manual/*.md + index.json + parts_catalog.json。

说明：全虚构设备型号与故障码体系（原型版 3 个设备族 × 4-5 条故障）。
M2 可扩展条目规模，或改为"模板 + LLM 批量起草 + 人工修"。
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "manual"

FAMILIES = [
    {
        "family": "ZX 系列螺杆式空压机",
        "models": ["ZX-75A", "ZX-110A", "ZX-160A"],
        "parts": [
            {"part_code": "ZX-AF-01", "name": "空气滤芯"},
            {"part_code": "ZX-OS-02", "name": "油分离器"},
            {"part_code": "ZX-IV-03", "name": "进气阀"},
            {"part_code": "ZX-PS-04", "name": "压力传感器"},
            {"part_code": "ZX-BL-05", "name": "传动皮带"},
            {"part_code": "ZX-OC-06", "name": "压缩机油"},
        ],
        "faults": [
            {
                "code": "E-ZX-01",
                "symptom": "按下启动按钮无反应，控制面板无显示",
                "causes": ["电源缺相", "急停按钮未复位"],
                "steps": [
                    "检查并复位所有急停按钮",
                    "检查配电柜断路器是否跳闸",
                    "检查相序保护器指示灯",
                    "逐项复位后重新启动",
                ],
                "parts": [],
                "keywords": ["无法启动", "启动无反应", "无显示", "断电", "没反应"],
            },
            {
                "code": "E-ZX-02",
                "symptom": "面板显示排气温度超过 105℃，触发高温报警并停机",
                "causes": ["冷却器堵塞", "润滑油位过低", "环境温度过高或通风不良"],
                "steps": [
                    "检查油位，低于下限则补充压缩机油 ZX-OC-06",
                    "清洁后部冷却器芯",
                    "确认冷却风扇运转正常",
                    "检查机房通风与环境温度",
                    "复位报警后试运行 30 分钟并观察温度",
                ],
                "parts": ["ZX-OC-06"],
                "keywords": ["高温", "排气温度", "温度报警", "过热", "跳机"],
            },
            {
                "code": "E-ZX-03",
                "symptom": "油气分离器压差报警，机组能耗升高",
                "causes": ["油分离器滤芯堵塞"],
                "steps": ["停机泄压", "更换油分离器 ZX-OS-02", "更换后试运行并记录压差"],
                "parts": ["ZX-OS-02"],
                "keywords": ["压差", "分离器", "能耗高", "堵塞"],
            },
            {
                "code": "E-ZX-04",
                "symptom": "运行中出现尖锐异响，转速波动",
                "causes": ["传动皮带松弛", "皮带磨损"],
                "steps": [
                    "停机断电挂牌",
                    "检查皮带张紧度并调整",
                    "磨损严重则更换皮带 ZX-BL-05",
                    "试运行观察",
                ],
                "parts": ["ZX-BL-05"],
                "keywords": ["异响", "皮带", "打滑", "尖锐声"],
            },
            {
                "code": "E-ZX-05",
                "symptom": "加载状态下压力仍低于 0.4MPa 且不上升",
                "causes": ["进气阀未动作", "压力传感器读数异常", "管路泄漏"],
                "steps": [
                    "检查进气阀动作是否到位",
                    "核对压力传感器读数与机械表",
                    "排查管路泄漏点",
                    "视结果更换 ZX-IV-03 或 ZX-PS-04",
                ],
                "parts": ["ZX-IV-03", "ZX-PS-04"],
                "keywords": ["压力不上升", "加载", "压力低", "泄压"],
            },
        ],
    },
    {
        "family": "QS 系列输送线驱动单元",
        "models": ["QS-300", "QS-450"],
        "parts": [
            {"part_code": "QS-MT-01", "name": "驱动电机"},
            {"part_code": "QS-RD-02", "name": "减速机"},
            {"part_code": "QS-BT-03", "name": "输送带"},
            {"part_code": "QS-BR-04", "name": "制动器"},
            {"part_code": "QS-SN-05", "name": "速度传感器"},
        ],
        "faults": [
            {
                "code": "E-QS-01",
                "symptom": "急停复位后输送线仍无法运行",
                "causes": ["安全回路未闭合", "现场急停按钮未全部复位"],
                "steps": [
                    "沿线逐段检查并复位急停按钮",
                    "复位安全继电器",
                    "确认控制柜指示灯恢复",
                    "重新启动输送线",
                ],
                "parts": [],
                "keywords": ["急停", "无法复位", "不运行", "安全回路"],
            },
            {
                "code": "E-QS-02",
                "symptom": "输送带跑偏，边缘摩擦机架并出现焦味",
                "causes": ["托辊不正", "尾轮张紧不均"],
                "steps": [
                    "停机挂牌",
                    "调整尾轮张紧螺栓使两侧均衡",
                    "校正偏斜托辊",
                    "空载试运行观察跑偏消除",
                ],
                "parts": [],
                "keywords": ["跑偏", "皮带摩擦", "焦味", "偏移"],
            },
            {
                "code": "E-QS-03",
                "symptom": "减速机运行时周期性异响，底部渗油",
                "causes": ["油封老化", "齿轮磨损"],
                "steps": [
                    "停机检查油位并补油",
                    "更换油封",
                    "清理并复检漏点",
                    "异响持续则报修评估减速机",
                ],
                "parts": ["QS-RD-02"],
                "keywords": ["减速机", "异响", "漏油", "渗油"],
            },
            {
                "code": "E-QS-04",
                "symptom": "HMI 显示速度为 0，但输送带实际在运行",
                "causes": ["速度传感器松动", "检测间隙超限"],
                "steps": [
                    "检查传感器安装间隙（应为 2-4mm）",
                    "清洁探头表面",
                    "无效则更换速度传感器 QS-SN-05",
                ],
                "parts": ["QS-SN-05"],
                "keywords": ["速度传感器", "无信号", "速度为零", "显示异常"],
            },
        ],
    },
    {
        "family": "KL 系列离心冷却泵",
        "models": ["KL-11", "KL-22"],
        "parts": [
            {"part_code": "KL-SL-01", "name": "机械密封"},
            {"part_code": "KL-BR-02", "name": "轴承"},
            {"part_code": "KL-IP-03", "name": "叶轮"},
            {"part_code": "KL-CC-04", "name": "联轴器弹性块"},
            {"part_code": "KL-VL-05", "name": "出口阀"},
        ],
        "faults": [
            {
                "code": "E-KL-01",
                "symptom": "泵启动后出口无流量，压力表读数低",
                "causes": ["泵腔未灌满（气蚀）", "入口阀未开启"],
                "steps": ["确认入口阀完全开启", "排气并灌泵", "检查底阀密封", "重新启动观察流量"],
                "parts": [],
                "keywords": ["不出水", "无流量", "气蚀", "灌泵"],
            },
            {
                "code": "E-KL-02",
                "symptom": "轴封处持续滴漏",
                "causes": ["机械密封磨损"],
                "steps": [
                    "停泵并隔离",
                    "拆卸泵壳取出旧密封",
                    "更换机械密封 KL-SL-01",
                    "复装打压测试",
                ],
                "parts": ["KL-SL-01"],
                "keywords": ["漏水", "机械密封", "滴漏", "轴封"],
            },
            {
                "code": "E-KL-03",
                "symptom": "泵体振动值超限，伴有明显噪声",
                "causes": ["联轴器弹性块老化", "轴承磨损", "对中不良"],
                "steps": [
                    "停机检查联轴器弹性块",
                    "检查轴承温升与异响",
                    "重新对中并紧固",
                    "试运行复测振动",
                ],
                "parts": ["KL-CC-04", "KL-BR-02"],
                "keywords": ["振动", "噪声", "联轴器", "轴承"],
            },
            {
                "code": "E-KL-04",
                "symptom": "出口压力表指针大幅摆动",
                "causes": ["出口阀开度过小", "系统内进入空气"],
                "steps": ["适当调整出口阀开度", "对系统进行排气", "稳定后记录运行压力"],
                "parts": [],
                "keywords": ["压力波动", "摆动", "出口压力"],
            },
        ],
    },
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    parts_catalog = []
    for fam in FAMILIES:
        family = fam["family"]
        models = fam["models"]
        parts = fam["parts"]
        parts_catalog.extend([{**p, "family": family, "models": models} for p in parts])

        lines = [f"# {family} · 故障处置手册（合成数据）", ""]
        lines.append(f"适用型号：{' / '.join(models)}")
        lines.append("备件清单：" + "；".join(f"{p['part_code']} {p['name']}" for p in parts))
        lines.append("")
        for f in fam["faults"]:
            lines.append(f"## {f['code']}　{f['symptom'][:18]}")
            lines.append(f"- 现象：{f['symptom']}")
            lines.append(f"- 可能原因：{'；'.join(f['causes'])}")
            lines.append(f"- 处置步骤：{' → '.join(f['steps'])}")
            if f["parts"]:
                lines.append(f"- 所需备件：{'、'.join(f['parts'])}")
            lines.append("")
            index.append(
                {
                    "code": f["code"],
                    "family": family,
                    "models": models,
                    "symptom": f["symptom"],
                    "causes": f["causes"],
                    "steps": f["steps"],
                    "parts": f["parts"],
                    "keywords": f["keywords"],
                }
            )
        md_path = OUT / (family.split()[0] + "_manual.md")
        md_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"[gen_manual] {md_path.name}")

    (OUT / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "parts_catalog.json").write_text(
        json.dumps(parts_catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[gen_manual] index.json: {len(index)} 条故障｜parts_catalog.json: {len(parts_catalog)} 个备件"
    )
    print(f"[gen_manual] done -> {OUT}")


if __name__ == "__main__":
    main()
