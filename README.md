# 出行服务编排 Agent

基于 Function Calling 的多工具服务编排系统，覆盖车主自驾与 Robotaxi 乘客服务双模式。

技术栈：Python 3.12 · OpenAI 兼容 Function Calling 端点（开发期自部署 Qwen3-Coder-Next）· Streamlit · FastAPI

## 项目来源

| 项 | 内容 |
|---|---|
| 选题方向 | 出行服务编排：车主自驾与 Robotaxi 乘客服务双模式 |
| 场景体系参照 | 阿里云天池「Q力星期四 · 小鹏 AI 出行服务编排 Agent 挑战赛」的 8 类场景分类与五项能力维度（https://tianchi.aliyun.com/competition/entrance/532505） |
| 实现范围 | 编排层：身份与场景路由、计划执行、工具装配、双层护栏、可靠性、评测；车控 / 订单 / 客服由自建 mock 服务承载 |
| 自建内容 | 场景规则库、三类有状态 mock 服务、15 个工具、路由与编排链路、双层护栏、43 条评测任务集与全部评测脚本 |
| 外部数据 | BFCL v3、API-Bank 为公开数据集；BFCL 多轮轨使用官方执行器与 checker |

系统输入为自然语言、车辆状态、订单状态与环境事件，输出为安全、合理、可解释的服务方案。实现边界限定在「已有座舱能力与 Robotaxi 服务能力之上做服务编排」，不涉及语音识别、基础车控与自动驾驶算法；场景规则与业务数据均为合成数据。

## 能力覆盖

| 能力项 | 本实现 | 证据 |
|---|---|---|
| 场景理解：识别真实需求而非表面指令 | 三层路由（规则与状态快路径 → LLM 场景标签 → 兜底）；8 类场景 × 风险等级判定 | 路由 39/43 = 90.7% |
| 服务编排：组合工具形成服务闭环 | plan → execute（依赖拓扑分批、同批并行）→ synthesize；15 工具按模式动态装载 | 常规 19/19；无规划基线 15/19 |
| 安全边界：高风险场景拒绝、提醒或转人工 | L1 提示词约束 + L2 规则引擎前置拦截（数据驱动，7 条危险动作规则）+ 输出合规审查 | 危险动作执行 0 次；对照实验见下 |
| 结果输出：回复、服务计划、调用理由、禁止动作、安全提示 | `reply` / `service_plan`（每步含 `args` 与 `reason`）/ `forbidden_actions`（含 `rule_id`）/ `safety_tips` | `src/agent/loop.py::_assemble_output` |
| 可体验呈现 | Streamlit 车机 HUD：场景快选、计划与执行 trace、风险与合规可视、故障注入 | `app.py`、`eval/_hud_smoke.py` |

## 系统架构

调度链路为单入口四段式，全部场景走同一路径，不按风险等级分支绕行——高风险请求若走上简化链路会导致安全规则逃逸：

```
用户输入
  └─ route      识别身份（车主 / 乘客）、场景、风险等级
      └─ plan        产出结构化步骤（含 deps 与 reason），先做工具名与参数校验
          └─ execute     按依赖分批，同批并行；单步经 L2 pre_check 后才进入工具实现
              └─ synthesize  汇总执行结果 → 输出四件套 → post_review 要素校验（缺失则重写一次）
```

## 关键实现

**1. 三层路由：确定性判断不交给模型**

规则与状态快路径、LLM 场景标签、兜底三层递进。车辆状态是可判定的（行驶中 / 驻车 / 儿童独留），这类条件由规则层直接命中，既不进模型也不产生推理成本；全量 43 条中 6 条走快路径。

**2. 计划-执行-收束：可校验的步骤化编排**

`plan` 先经 `_validate_plan` 校验工具名与必填参数，非法计划回落模板计划而不是直接执行；`execute` 按 `deps` 拓扑分批，同批用线程池并行；`max_iter` 触顶时输出降级结果并自动转人工，不做无约束的重试。

**3. 双层护栏：提示词负责收敛，代码负责兜底**

L1 在计划阶段约束动作空间；L2 由 `config/safety_rules.yaml` 驱动的规则引擎在工具执行前做条件匹配（同时看入参和车辆状态），命中即拦截并以结构化消息回填模型；输出侧 `post_review` 校验高风险应答的要素齐备性，缺失则触发一次重写。

危险信号可以只存在于车辆状态中——文本完全无害、状态显示儿童独留，这是 L2 必须独立于提示词存在的原因。

**4. 可靠性：每条主张都有注入用例**

超时、重试与指数退避、并发闸、`max_iter`、失败后降级，全部在 `src/reliability.py` 与工具层落地；mock 服务内置 timeout / error / empty 三类失败注入，8 条注入用例逐条验证重试证据（attempts ≥ 2）。

## 评测结果

| 评测项 | 数据来源 | 规模 | 结果 |
|---|---|---|---|
| 任务完成（常规 + 失败注入） | 本工程自建任务集 `eval/tasks.jsonl` | 27 条 | **27/27** |
| 失败注入完成 / 重试证据 | 同上（mock 服务三类注入） | 8 条 | **8/8** / **8/8** |
| 路由准确率（场景 ∧ 风险） | 同上 | 43 条 | **39/43 = 90.7%** |
| 危险动作真实执行次数 | 同上 | 43 条全量 | **0 次** |
| 输出要素齐备 | 同上 | 危险 16 条 | 15/16（1 条缺 `safety_tip`，动作未执行） |
| 安全对照（同任务同种子，仅切换护栏开关） | 同上 | 危险 16 条 | 双层护栏 **16/16** vs 无护栏 **13/16 = 81.3%**；无护栏下 3 条真实违规被执行，L2 实际拦截 2 次 |
| 无规划基线对照 | 同上 | 常规 19 条 | 计划编排 **19/19** vs 单循环直调 **15/19 = 78.9%** |
| BFCL v3 函数调用 | [Berkeley Function Calling Leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html)（数据 [HuggingFace](https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard)，harness [GitHub](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard)） | 1240 条（5 类） | **1114/1240 = 89.8%** |
| API-Bank | [DAMO-ConvAI/api-bank](https://github.com/AlibabaResearch/DAMO-ConvAI/tree/main/api-bank)（[论文](https://arxiv.org/abs/2304.08244)） | 779 条（L1+L2+L3） | **548/779 = 70.3%**（L1 87.5 / L2 70.4 / L3 42.4） |
| BFCL v3 多轮 | [BFCL v3 多轮说明](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html)；官方执行器与 checker（`eval/bfcl_multi_exec/`） | 500 条（5 类 ×100） | **126/500 = 25.2%** |

评测口径与逐题明细见 `eval/BENCHMARKS.md`、`eval/report_v02.md`、`eval/report_safety.md`、`eval/report_baseline_noplan.md`、`eval/report_bfcl.md`、`eval/report_api_bank.md`、`eval/report_bfcl_multi.md`。

## 版本演进

| 时间 | 内容 |
|---|---|
| 2026-07-24 | 初始版本：工具注册（JSON Schema）、可靠性三件套、Agent 循环、离线演示 |
| 2026-07-29 – 10-16 | 场景重构：出行服务双模式、三层路由、双层护栏、15 工具动态装载、输出四件套、43 条任务集 |
| 2026-08-02 – 10-16 | 三项公开基准外测与评测驱动迭代（BFCL 单轮 / API-Bank / BFCL 多轮） |
| 2026-08-07 | 车机 HUD 演示界面 + 冒烟测试 |

逐轮变更与指标记录见 `eval/CHANGELOG.md`；设计方案见 `docs/出行服务编排升级设计.md`。

## 工程结构

```
ops-agent/
├── README.md
├── requirements.txt
├── app.py                    # 车机 HUD 演示（Streamlit：场景快选 + 计划/trace 可视化 + 故障注入）
├── .streamlit/config.toml    # HUD 深色主题配置
├── config/
│   ├── safety_rules.yaml     # 声明式安全规则库（8 场景策略 + 7 条危险动作拦截 + 输出合规）
│   └── prompts/              # route / plan / synth / rewrite（任务规划与护栏提示词）
├── docs/
│   ├── 设计方案.md               # 系统方案（定位 / 链路 / 里程碑 / 验收）
│   ├── 出行服务编排升级设计.md    # 分层设计 + §10 实施记录
│   ├── 模型选型.md               # 选型分析与裁决
│   ├── 生产化路线.md             # 生产化差距矩阵与迁移路径
│   ├── 施工说明书.md             # 分阶段实施手册（环境 / 步骤 / 排错）
│   ├── 数据集说明.md             # 数据集构成 / 外部评测集 / 校验
│   ├── 技术报告.md / .pdf        # 技术方案（架构 / 实现 / 评测 / 复现）
│   ├── 开发过程.md               # 分阶段工作记录与关键决策
│   └── 演示记录.md / demo_01_hud.png   # 界面截图与可复现输出
├── data/                     # 规则库渲染产物 / mock 数据 / 外部评测集（脚本可重建）
├── scripts/
│   ├── fetch_data.py         # 外部评测数据集（可选）
│   └── gen_rules.py          # 规则库渲染 → data/rules/（可检索文档 + index.json）
├── mock_services/
│   ├── vehicle.py            # 有状态车控（位置/电量/行驶态/车门/安全带/儿童乘员 + 失败注入）
│   ├── orders.py             # Robotaxi 订单（状态机 + 幂等 + 失败注入）
│   ├── cs.py                 # 人工客服工单（转人工兜底）
│   └── serve.py              # FastAPI 包装（可选）
├── src/
│   ├── llm.py                # LLM（Function Calling）+ ScriptedLLM（离线干跑）
│   ├── reliability.py        # 超时 / 重试退避 / 并发闸
│   ├── router.py             # 三层路由（规则/状态快路径 → LLM 场景标签 → 兜底）
│   ├── safety.py             # L2 护栏：pre_check 拦截 + 输出合规审查
│   ├── prompts.py            # 提示词加载
│   ├── tools/                # 15 工具：spec（JSON Schema）+ impl（实现 + 入参校验 + 失败注入）
│   └── agent/loop.py         # plan → execute（并行分批）→ synthesize
├── eval/
│   ├── tasks.jsonl           # 任务集 43 条（8 场景 + 8 注入 + 16 危险）
│   ├── run_tasks.py          # 任务集评测（完成/路由/安全/合规/可靠性）
│   ├── run_bfcl.py           # 外测：BFCL v3 函数调用（1240 条）
│   ├── run_bfcl_multi.py     # 外测：BFCL v3 多轮（500 条）
│   ├── run_api_bank.py       # 外测：API-Bank（779 条）
│   ├── bfcl_multi_exec/      # 官方执行器 + checker
│   ├── _hud_smoke.py         # HUD 冒烟测试（Streamlit AppTest 无头运行）
│   ├── BENCHMARKS.md         # 跨基准汇总 + 口径说明
│   ├── CHANGELOG.md          # 迭代记录
│   └── archive/              # 历史轮次留档
├── tests/                    # 单元测试（护栏 / 可靠性 / 路由 / 计划校验 / 工具注册）
└── demo.py                   # 离线演示（路由 / 护栏 / 编排 / 可靠性；命令行版）
```

## 快速开始

```bash
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
python scripts/gen_rules.py           # 渲染安全规则库 → data/rules/
.venv/Scripts/streamlit run app.py    # 车机 HUD（http://localhost:8501）
python demo.py                        # 命令行演示（无需 API Key）
```

## 运行评测

```bash
python scripts/fetch_data.py          # 外部评测数据集（可选；已就绪自动跳过）
python eval/run_tasks.py              # 任务集评测（43 条；需 .env 配置 LLM 端点）
python eval/run_tasks.py --no-guardrail --only dangerous   # 安全对照（护栏关，16 条）
python eval/run_tasks.py --baseline --only normal          # 无规划基线对照（19 条）
python eval/run_tasks.py --mock       # 离线干跑（不调 LLM，验证 harness）
python eval/run_bfcl.py               # BFCL v3 函数调用（1240 条；--cats / --limit）
python eval/run_bfcl_multi.py         # BFCL v3 多轮（默认 5 类×100；--offset 续跑）
python eval/run_api_bank.py           # API-Bank（779 条）
```

## 单元测试

```bash
python -m pytest                      # 120 条用例：护栏规则 / 可靠性 / 路由 / 计划校验 / 工具注册
python -m ruff check . && python -m ruff format --check .   # 风格检查（100 列，配置见 pyproject.toml）
python -m pytest tests/test_safety.py -v   # 仅看 L2 护栏
```

## 数据说明

场景规则库、mock 服务数据、任务集均为合成数据，不对应任何真实厂商；外部参考集仅作语料与对照。数据本体不入库，由脚本重建。来源、抽取结果与许可详见 `docs/数据集说明.md`。

## 许可

MIT License，详见 [LICENSE](LICENSE)。
