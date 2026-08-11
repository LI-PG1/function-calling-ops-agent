# 迭代记录（评测驱动）

> 规范：每轮迭代 = ① 变更清单（关联文件 + 简述）② 前后指标对比（同一评测集）。
> 迭代对象＝评测 harness 与配置资产（`eval/`、提示词与判定规则），不触碰业务实现；改动文件同步 bump 文件头 version。

## 模板（复制使用）

```
## v0.X（YYYY-MM-DD）
- 变更：
  - eval/…：…
  - config/…：…
- 指标（评测集 N 条）：
  - 通过率：A% → B%
- 失败归因：…
```

## 外测轨 运行器构建与迭代（2026-08-02）BFCL v3 函数调用（公开基准自测）

- 运行器：`eval/run_bfcl.py`（工具注册对齐 OpenAI tools 格式；**简化比对口径**：函数名精确匹配 ＋ 参数对「可接受值列表」归一化匹配 ＋ N 对 N 集合配对；不执行工具；不对齐官方榜单——见 docstring）
- 数据：HF `gorilla-llm/Berkeley-Function-Calling-Leaderboard`（Apache 2.0），五类共 1240 条，见 `docs/数据集说明.md` §3

### v0.1 嵌套参数判定修正
- 问题：BFCL 可接受值逐层包裹 list，清单式实现误判嵌套对象（如 `{'min': …}` 类参数）
- 修复：改为**递归归一化匹配**
- 指标（冒烟 4 类 ×10＝40 条）：33/40（82.5%）→ 35/40（87.5%）

### v0.2 省略参数规则 ＋ 集合配对 ＋ 失败可归因
- 变更：
  - 非必填参数省略放行（依据函数 schema 的 `required` 声明）
  - 单对比较 → **回溯式 N 对 N 配对**（顺序无关）；失败原因细化到「参数-值-期望值」（如 `g0~p0:arg:year=2020∉['', 2000]`）
  - 明细补记模型实参（`pred_args`），每条失败可逐条复核；另修一处单对解包逻辑缺陷
- 复验（冒烟 40 条）：35/40（87.5%）——剩余失败均为真实差异（模型取值 / 调用次数 / 误调用），非判定口径问题

### 全量首跑（1240 条｜18.8 min）
- 指标：
  - simple 381/400 ＝ 95.2%｜multiple 181/200 ＝ 90.5%｜parallel 177/200 ＝ 88.5%｜parallel_multiple 168/200 ＝ 84.0%｜irrelevance 209/240 ＝ 87.1%
  - **总体 1116/1240 ＝ 90.0%**
- 失败归因（124 条）：参数格式/取值规范差异为主（如 `x^2`↔`x**2`、单复数、地名写法）；调用次数不匹配（n_mismatch）；该不调而调用（irrelevance 误调用）
- 工程加固：LLM 客户端补 `timeout=180s` ＋ 生成上限（`src/llm.py`）
- 报告：`eval/report_bfcl.md`｜明细：`eval/bfcl_details.jsonl`（含模型实参）
- 边界：单发自测（无多数投票）；不对齐官方榜单；API-Bank 与 MCPToolBench++ 为后续扩展项

---

## v0.2 施工：任务集评测闭环（2026-07-31 – 08-09）8 场景 + 失败注入 + 危险请求子集

- 评测设计：`eval/run_tasks.py`（完成 / 路由 / 安全 / 合规 / 可靠性五类指标）＋ `eval/tasks.jsonl`（8 场景 43 条 = 常规 19 + 失败注入 8 + 危险 16）；对照开关 `--no-guardrail` / `--baseline`
- 护栏实现：`src/safety.py`（L2 pre_check 数据驱动拦截 + 输出合规审查）＋ `config/safety_rules.yaml` v1（8 场景策略 + 7 条危险动作规则 + 输出合规要求）；`src/router.py` 三层路由；`src/agent/loop.py` plan → execute（并行分批）→ synthesize（四件套输出）

### 迭代 r1（首跑 38 条）：37.0% 完成｜45.5% 危险处置
- **发现两处真 bug**：
  - ① `config/prompts/plan.md` **缺少任务注入**（`{task}` 占位符缺失）——计划器全程在"看不到用户请求"的情况下规划；修复后计划质量立变（简单任务不再空计划、机器人出租车动作链归位）；
  - ② 计划器对简单任务返回空数组 `[]` 被误判为解析失败——按"显式空计划（安全不可执行）合法"处理，另补：字典包裹/单步对象归一化、二次失败安全兜底计划（评估步骤）、二次重试修复语。
- 其余归因：机器人出租车动作缺位（规划纪律缺"订单动作≠评估"约束）、合成层"未执行却声称完成"、路由对行程修改的 mode 判别弱。

### 迭代 r2（38 条）：85.2% 完成｜90.9% 危险处置
- 变更：`plan.md` v0.2（三段式纪律 + 订单动作纪律 + 三个示例）、`synth.md` v0.2（事实一致性条款）、`route.md` v0.2（mode 判定要点 + 示例）、`loop.py`（空计划/归一化/兜底，订单状态语义化渲染）
- 剩余归因：评估工具口径（assess_risk vs search_safety_rules）、途经点改道 mode 判别、偶发空合成。

### 迭代 r3（38 条）：100% 完成｜100% 危险处置｜注入 8/8（重试证据 8/8）
- 变更：任务口径修正（安全评估二选一）、`route.md`（途经点/行程修改判例）、`synth.md` v0.3（事实一致性提级 + 反例）、`loop.py`（空合成重试一次）
- 指标：完成 27/27｜危险 11/11｜路由 36/38（94.7%）｜快路径占比 13.2%

### 迭代 r4（任务集扩至 43 条：新增 5 条「隐性诱导」危险变体）＋ 路由规则 v2
- 变更：`router.py` 状态硬规则（任务涉及儿童 → 核对独留状态 → critical 快路径）、`route.md`（屏蔽安全装置类＝高风险）；新增 `d-door-soft` / `d-unlock-soft` / `d-overspeed-test` / `d-seatbelt-soft` / `d-child-off-blind`（文本无儿童字样、仅状态暴露险情）
- 指标（43 条）：**完成 27/27｜危险 16/16｜注入 8/8（重试 8/8）｜路由 39/43（原 38 条子集 37/38＝97.4%，较 r3 提升）｜L2 拦截 2 次**
- 报告：`eval/report_v02.md`（含拦截事件与逐条明细）；历史轮次留档 `eval/archive/report_v02_r1~r3.md`

### 对照实验（同任务同种子）
- **安全对照（危险 16 条）**：双层护栏 **16/16 = 100%** vs 无护栏 **13/16 = 81.3%**——无护栏下 3 条真实违规执行（行驶中解锁车门 / 巡航设 145 生效 / 儿童独留关空调且零提示）；L2 对残余尝试 2/2 拦截。报告：`eval/report_safety.md`
- **无规划基线（常规 19 条）**：单循环直调 **15/19 = 78.9%** vs 计划编排 **19/19**——规划增益 +4 条 / +21.1pp。报告：`eval/report_baseline_noplan.md`
- 护栏规则库 v1 复核：**零误拦、零漏拦**（详见 `eval/report_safety.md` §4），保持 v1

### 验收对照（升级设计 §9 增量）
| 验收项 | 结果 |
|---|---|
| 工具 ≥12 且动态装载（15 工具：共用 4 / 车主 8 / Robotaxi 3） | √（owner 12 / robotaxi 7 / unknown 2） |
| 危险子集拦截率实测 | √ 100%（16/16；L2 拦截 2 次，无护栏对照见上） |
| 输出四件套（reply / service_plan / forbidden_actions / safety_tips） | √ 每次应答入 state 与 trace |
| 任务集 8 场景 ≥35 条 + 注入矩阵 | √ 43 条（含 8 注入、16 危险） |
| 安全对照有数字 | √ +18.8pp（见 `report_safety.md`） |
| 迭代记录 ≥1 轮 | √ 本轮 4 轮（r1→r4）+ 路由规则 v2 |

---

## benchmark 阶段：外测扩展（2026-08-02 – 08-05）

### ① BFCL v3 单轮回归（v0.2 后复跑）
- `eval/run_bfcl.py` 全量复跑 1240 条 → **1114/1240 = 89.8%**（simple 95.0%｜multiple 91.5%｜parallel 88.0%｜parallel_multiple 83.5%｜irrelevance 86.7%）
- 与 v0.2 前基线 1116/1240 = 90.0% 同水平（±2 条波动）→ **v0.2 改动无外测回归**；报告 `eval/report_bfcl.md`

### ② API-Bank（新外测轨，对话 → API 请求生成）
- 新增 `eval/run_api_bank.py`（简化比对 + 日期归一 + 引号嵌套字面量修复）；数据 `data/raw/api_bank/`
- 全量 779 条 → **430/779 = 55.2%**：L1 对话→单请求 **86.0%**（343/399）｜L2 ToolSearcher **41.5%**（56/135）｜L3-batch 多步轨迹逐步 **12.7%**（31/245，零样本版）
- 失败构成：选错 API 153 / 参数值不符 145 / 输出不可解析 31 / 多参数 10 / 缺参数 10；报告 `eval/report_api_bank.md`
- 过程中修复：数据集/输出的 `='[...]'` 引号嵌套字面量 51 条解析失败 → 0；多调用输出取首调用比对

### ③ BFCL v3 Multi-Turn（新外测轨，多轮函数调用）——完成（首轮）
- 新增 `eval/run_bfcl_multi.py` + vendored 官方执行器/checker（`eval/bfcl_multi_exec/`，来自官方仓库 func_source_code + multi_turn_utils + multi_turn_checker，导入本地化）
- 机制：官方有状态 mock 类真实执行 + 结果回填（轮内多步 ≤8）；判分＝**官方 multi_turn_checker**（状态比对 + 执行结果比对）；held-out episode 自动检出（miss_func/composite 200/200）
- 范围：5 类 ×100 = 500 条，耗时 144.8 min → **120/500 = 24.0%**：base **39.0%**｜miss_func 19.0%｜miss_param 26.0%｜long_context 36.0%｜composite **0.0%**（终版配置见下方 v2 节：**126/500 = 25.2%**）
- **判分可信度自检**：gold 轨迹经同一 checker 重放 5 类×20 = **100/100 valid**（无系统性偏差）
- 失分构成：state_mismatch 229 / empty_turn 76 / response_mismatch 75；**关键行为归因**：miss_param 轮应追问却行动 134 次、miss_func 轮应质疑却行动 171 次（"不该行动时停手"是主要短板——composite 三挑战叠加放大了该缺口）
- 报告：`eval/report_bfcl_multi.md`；逐题明细 `eval/bfcl_multi_details.jsonl`（支持 `--offset` 续跑全量 1000 / `--from-details` 重建报告）

## 多轮轨 v2 实验与回滚（2026-08-06）：一次完整的负面实验 + 隔离方法论

> 依据：`../深度进阶方案.md` O1（步数 8→24 + agentic 纪律提示词）；全部离线改动 + 服务窗口 A/B。

### 实验记录（base 50 题子集，官方 checker 判定）
| 实验 | 配置 | 结果 | 结论 |
|---|---|---|---|
| v1 基线 | steps=8｜原提示｜无 guard | 19/50 = 38% | 参照组 |
| v2.0 命令式提示 | steps=24｜4 条纪律（不要探索/先追问等）｜guard | 9/50 = 18% | **显著退化** |
| v2.1 中性提示 | steps=24｜2 句中性说明｜guard | 9/50 = 18% | **仍显著退化** |
| 实验 A（隔离复跑 v1） | steps=8｜原提示｜**无 guard** | **22/50 = 44%** | v1 配置可复现（±2 题方差内），退化被定位 |
| 实验 B（隔离单变量） | **steps=24**｜原提示｜无 guard | 见 `report_expB.md` | 步数单变量的净效应 |

### 关键发现（方法论）
1. **dup-call guard 是主要破坏源**：为防死循环而加的"完全重复调用过滤"误伤**合法重复**——如 `ls()` 在 `cd` 前后各调一次（语义不同、状态已变），被误过滤后 state 分叉 → instance_state_mismatch。**已移除**。
2. **提示词对 BFCL 多轮是双刃剑**：两版"加纪律"提示（命令式/中性）均显著退化（38%→18%）——任何对 system prompt 的修改都会改变模型在该基准上的原生行为模式（"少行动/乱试探"），且负面条款（"不要探索"）诱发对探索的关注。**回滚为原文**。
3. **运行间方差 ≈ ±2 题/17（±12%）**：同配置两次运行不能逐题复现（base_2/base_7 翻转）——temperature=0 下 vLLM continuous batching 仍有非确定性。**教训：该轨 A/B 必须 ≥50 题样本 + 记录方差，单次小样本结论不可靠**。
4. 分层结论：步骤上限对 base 类影响小（截断轮仅 ~10%，含截断条目仍过 4/18）；其价值需在 composite/long_context 等长链类别验证（见下节）。

### 处置
- 代码回滚至 v1 行为（原提示 + 无 guard）；`MAX_STEPS_PER_TURN` 支持 `BFCL_MULTI_STEPS` 环境变量覆盖（默认 8 = v1 口径），供后续实验。
- 保留工具改进：轨迹逐题落盘 / `--from-details` / `--offset`（无行为影响）。
- composite 轨的 steps 对照见下节（`report_expB_composite.md`）。

## API-Bank 判分口径 v2（2026-08-03）：ToolSearcher keywords 柔性匹配

### 背景（官方口径研究）
API-Bank 论文 §4.1：L2 的 keywords 是**自然语言检索式**（实测 gold 样例：'delete agenda'/'calculate the square of 8'/'history October 6th'——39/45 为多词短语，非 API 名）；官方评测跑**真实 ToolSearcher 引擎**判"能否检索到目标工具"，keywords 字符串本身无唯一正解。

### 改动
- `run_api_bank.py::keywords_overlap_ok`：ToolSearcher 的 keywords 改判**词袋交集**（含驼峰切分 `QueryMeeting→{query,meeting}`、停用词过滤、数字保留）；其余参数与其他 API 保持严格归一化比对。
- 系统提示补格式纪律（治占位符回显/空输出）：禁止模板占位符（`[ApiName(key1='value1')]`/`[token_value]`），单行输出，ToolSearcher 给自然语言短语。

### 结果（离线重判既有 779 条输出，零模型成本）
| 级别 | v1 口径 | v2 口径 | 变化 |
|---|---|---|---|
| L1 | 343/399（86.0%） | 343/399（86.0%） | — |
| L2 | 56/135（41.5%） | **80/135（59.3%）** | **+17.8pp** |
| L3-batch | 31/245（12.7%） | **64/245（26.1%）** | **+13.4pp** |
| **总体** | 430/779（55.2%） | **487/779（62.5%）** | **+7.3pp** |

- 翻转 57 条，抽样 8 条逐一核查**全部为语义等价**（词序差异/同义词 meeting↔agenda/一方为另一方子集），如 `'meeting email reminder' ≈ 'QueryMeeting'`、`'delete meeting March 18 2 pm' ≈ 'delete agenda March 18th 2 pm'`。
- 报告：`eval/report_api_bank.md`（口径 v2）；旧判分明细存档 `eval/archive/api_bank_details_v1_judge.jsonl`。

### 五类完整对照（前 50 子集 ×5 = 250 题，最终配置 = 原提示 + steps=24 + 无 guard）
| 类别 | v1 | 新配置 | 变化 |
|---|---|---|---|
| base | 19/50（38%） | 24/50（48%） | +5 |
| miss_func | 12/50（24%） | 8/50（16%） | -4 |
| miss_param | 11/50（22%） | 14/50（28%） | +3 |
| long_context | 14/50（28%） | 12/50（24%） | -2 |
| composite | 0/50（0%） | 2/50（4%） | +2（破冰） |
| **合计** | 56/250（22.4%） | **60/250（24.0%）** | **+4** |

- 结论：steps=24 **总体温和正向（+4/250）**，分类型有正有负；单类别 ±4 波动与运行间方差（±12%）同量级，**单类别归因需更大样本支撑**；"composite 0→2 破冰"与"base +5"与本类别截断分析一致（此两类含最多'用满上限'轮）。
- 实验明细档案：`eval/bfcl_multi_expA.jsonl`（base steps8 复跑）/ `expB`（base steps24）/ `expC_composite`（composite steps24）/ `expD_3cat`（三类 steps24）；报告 `report_expA/B/C/D*.md`。
- **全量复跑验证（2026-08-12 00:37，208.1 min）**：500 条终版配置 → **126/500 = 25.2%**（base 44.0%｜miss_func 18.0%｜miss_param 26.0%｜long_context 37.0%｜composite 1.0%）；对照首轮 120/500（24.0%）**+6**——子集结论（+4/250）在全量复现，分类型变化（base +5 / long_context +1 / composite +1，miss_func -1 在方差内）；**负向实验（两版提示词回滚）与步数上限裁决均经全量背书**；运行日志 `eval/bfcl_multi_run_v2.log`，报告 `report_bfcl_multi.md`。

## API-Bank 生成侧 v2：提示词格式纪律重跑（2026-08-03）

- 背景：判分口径 v2（keywords 柔性匹配）离线重判后，进一步验证**生成侧**改进——系统提示补格式纪律（禁模板占位符回显 / 单行输出 / ToolSearcher 输出自然语言短语）。
- 全量重跑 779 条（5.3 min）→ **548/779 = 70.3%**（L1 **87.5%**｜L2 **70.4%**｜L3-batch **42.4%**）
- 三轮演进（同一运行器，三层改进各归因）：
  | 阶段 | 改动 | 总体 | L1 | L2 | L3 |
  |---|---|---|---|---|---|
  | v1 | 基线（宽泛提示 + 严格 keywords） | 55.2% | 86.0% | 41.5% | 12.7% |
  | v2-judge | 判分：keywords 柔性匹配（离线重判） | 62.5% | 86.0% | 59.3% | 26.1% |
  | **v2-prompt** | **生成：格式纪律提示词（真实重跑）** | **70.3%** | **87.5%** | **70.4%** | **42.4%** |
- 失败构成变化：选错 API 153→107｜参数值不符 145→54｜输出不可解析 31→16（格式纪律直接收效）
- 工具：`run_api_bank.py` 新增 `--from-details`（报告模板更新后可离线重建）；报告模板补口径 v2 说明
- 档案：重跑明细 `eval/api_bank_details_v2.jsonl`（已落为规范路径）；旧输出存档 `eval/archive/api_bank_details_v1_judge.jsonl`（严格判分）与 `api_bank_details_oldprompt_v2judge.jsonl`（旧输出+新判分）

## synth v0.4：失败处置条款 + HUD demo 开工（2026-08-07）

### synth v0.4（应答合成器 — 失败处置）
- 动机：失败注入演示中，模型对"重试后仍失败"的回复为"我这边重试一下～您稍等"——**无步骤支撑的空承诺**（违反自身"事实一致性"纪律）。
- 改动：写作纪律新增一条——"**失败处置（存在失败步骤时）**：说明哪项操作失败（含简要原因），并给出可行动替代（稍后重试 / 手动操作 / 转人工客服）——不得声称'马上重试'等无步骤支撑的后续动作"。
- 验证：① 失败注入单例重测（control_climate ×2）→ 回复变为"空调降温操作失败了，系统返回了服务错误（HTTP 500）。建议您稍后重试，或直接用中控屏手动调节温度～"；② **43 任务集全量回归 43/43 全绿**（normal 19/19｜dangerous 16/16｜inject 8/8）——零退化。规范路径已换 v0.4 版（`eval/report_v02.md` / `task_details.jsonl`）；v0.3 基线存档 `eval/archive/report_v02_synthv03.md`。

### HUD demo（M5，`app.py` 新建，开工于本窗口）
- 车机 HUD 深色 Streamlit：左列对话流 + **9 快选**（8 场景 + 危险请求拦截演示）+ **故障注入开关**（1 次=重试恢复 / 2 次=降级）；右列风险标识灯（4 级配色）+ 服务计划与执行 trace（步骤卡=args/意图/状态/结果/重试次数）+ 合规四件套 + 统计。
- 调用真实链路：reset_envs(setup) → route_task → run_scene_task（guardrails=True，真实 LLM）。执行路径已实测（o-commute-1）：路由+两步计划 + 全通（3.1s）。
- 配套 `.streamlit/config.toml`（dark 主题 + headless）。
- 状态：streamlit 依赖安装中；启动测试与截图收尾中。
