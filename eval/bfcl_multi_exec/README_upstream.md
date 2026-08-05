# 多轮执行器与判分器（第三方代码）

本目录下的文件来自 **Berkeley Function Calling Leaderboard（BFCL）** 官方仓库，用于
BFCL v3 Multi-Turn 类别的有状态执行与判分。仅作为评测依赖使用，不参与本项目业务链路。

## 来源

| 项 | 内容 |
|---|---|
| 上游仓库 | https://github.com/ShishirPatil/gorilla |
| 上游路径 | `berkeley-function-call-leaderboard/bfcl_eval/eval_checker/multi_turn_eval/` |
| 官网 | https://gorilla.cs.berkeley.edu/leaderboard.html |
| 许可 | Apache License 2.0（见同目录 `LICENSE`） |
| 取用日期 | 2026-08-02 |

## 文件

| 文件 | 作用 |
|---|---|
| `executor.py` | 多轮执行入口：按工具名分发到对应的有状态实现 |
| `checker.py` | 官方判分逻辑：重放模型调用与参考调用，逐轮比对状态与执行结果 |
| `gorilla_file_system.py` | 文件系统类工具的有状态模拟 |
| `math_api.py` / `message_api.py` / `posting_api.py` / `ticket_api.py` / `trading_bot.py` / `travel_booking.py` / `vehicle_control.py` | 各类别的工具实现（有状态、可执行） |
| `long_context.py` | long-context 类别的扩展词表 |
| `__init__.py` | 包声明 |

## 本地改动

- `__init__.py`：为便于在 `eval/` 内导入而新增的包声明；
- 其余文件保持上游内容，未做逻辑修改（对本项目无业务耦合）。

## 引用

如引用本目录代码，请遵循上游仓库的许可条款，并保留本说明与 `LICENSE`。
