# 外测报告（BFCL v3 Multi-Turn · 多轮函数调用）

- 日期：2026-08-07 18:29｜用例：50 条｜总耗时：9.3 min
- 定位：**公开基准自测**（多轮工具调用：状态跟踪 / 缺失函数识别 / 缺失参数追问）
- 判分：**官方 multi_turn_checker（vendored，与官方仓库同源）**——重放模型调用与参考调用（各自独立实例）、逐轮状态比对 + 执行结果比对；held-out 近似：miss_func / composite 按「空 gold 轮+其后空提问轮」自动检出缺失函数（200/200 条检出），episode 前从工具表移除、supply 轮起放回
- 执行：官方 func_source_code 有状态 mock 类（vendored）；轮内多步（上限 8 步/轮），执行结果原样回填对话；模型走 OpenAI 兼容 tool 协议（qwen3-coder-next 自部署端点）
- 判分可信度自检：**gold 轨迹经同一 checker 重放 5 类×20 条 = 100/100 valid**（判分实现无系统性偏差的证据）
- 与官方榜单的差异：本机解码（OpenAI tool_calls → 字面量调用串，无官方 handler）；提示词为通用 system prompt（非官方 per-model 模板）；结果供项目内横向对照，不与榜单数字直接对齐

## 总指标（官方 checker 判定）

| 类别 | 条数 | 通过（valid） | 通过率 |
|---|---|---|---|
| base | 50 | 22 | 44.0% |
| **总体** | 50 | 22 | 44.0% |

## 失分构成（按官方 error_type）

| error_type | 条数 |
|---|---|
| multi_turn:instance_state_mismatch | 16 |
| multi_turn:execution_response_mismatch | 8 |
| multi_turn:empty_turn_model_response | 4 |

## 关键行为归因（不该行动的轮）

- miss_param 轮**应追问却继续行动**：0 次（模型未识别缺失参数，直接执行）
- miss_func 轮**应质疑却继续行动**：0 次（函数被扣留时模型未提出疑虑）

## 失败清单（共 28，前 15）

| id | 类别 | error_type | 说明 |
|---|---|---|---|
| multi_turn_base_2 | base | multi_turn:instance_state_mismatch | Model instance for GorillaFileSystem does not match the state with gro |
| multi_turn_base_3 | base | multi_turn:instance_state_mismatch | Model instance for GorillaFileSystem does not match the state with gro |
| multi_turn_base_4 | base | multi_turn:instance_state_mismatch | Model instance for TwitterAPI does not match the state with ground tru |
| multi_turn_base_5 | base | multi_turn:empty_turn_model_response | Model response list is empty for turn 2 |
| multi_turn_base_6 | base | multi_turn:instance_state_mismatch | Model instance for GorillaFileSystem does not match the state with gro |
| multi_turn_base_7 | base | multi_turn:execution_response_mismatch | Model response execution results so far does not contain all the groun |
| multi_turn_base_8 | base | multi_turn:empty_turn_model_response | Model response list is empty for turn 2 |
| multi_turn_base_9 | base | multi_turn:instance_state_mismatch | Model instance for GorillaFileSystem does not match the state with gro |
| multi_turn_base_10 | base | multi_turn:instance_state_mismatch | Model instance for GorillaFileSystem does not match the state with gro |
| multi_turn_base_11 | base | multi_turn:empty_turn_model_response | Model response list is empty for turn 1 |
| multi_turn_base_15 | base | multi_turn:execution_response_mismatch | Model response execution results so far does not contain all the groun |
| multi_turn_base_16 | base | multi_turn:instance_state_mismatch | Model instance for GorillaFileSystem does not match the state with gro |
| multi_turn_base_18 | base | multi_turn:instance_state_mismatch | Model instance for GorillaFileSystem does not match the state with gro |
| multi_turn_base_20 | base | multi_turn:instance_state_mismatch | Model instance for GorillaFileSystem does not match the state with gro |
| multi_turn_base_21 | base | multi_turn:instance_state_mismatch | Model instance for GorillaFileSystem does not match the state with gro |