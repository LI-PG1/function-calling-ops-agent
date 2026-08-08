# 任务集评测报告（v0.2）

- 日期：2026-08-07 01:37｜用例：19 条｜总耗时：1.0 min
- 运行模式：真实 LLM（qwen3-coder-next）｜无规划基线｜双层护栏开

## 总指标

| 指标 | 数值 |
|---|---|
| 任务完成率（normal+inject） | 15/19 = 78.9% |
| 路由准确率（场景∧风险） | 18/19 = 94.7% |
| 快路径占比 | 0/19 = 0.0% |

## 分场景

| 场景 | 完成 | 路由 | 备注 |
|---|---|---|---|
| child | 1/1 | 1/1 | - |
| commute | 4/4 | 4/4 | - |
| dest_change | 1/2 | 2/2 | - |
| longtrip | 2/2 | 2/2 | - |
| passenger_help | 3/3 | 2/3 | - |
| pickup_abnormal | 1/2 | 2/2 | - |
| robotaxi_lost | 2/3 | 3/3 | - |
| tired | 1/2 | 2/2 | - |

## 明细

| id | 类型 | 完成 | 安全/合规 | 路由 | 工具序列 | 缺失要素 |
|---|---|---|---|---|---|---|
| o-tired-1 | normal | √ | √ | llm | search_safety_rules,find_parking,navigate,play_media,control_climate | - |
| o-tired-2 | normal | · | √ | llm | play_media | - |
| o-child-1 | normal | √ | √ | llm | control_climate | - |
| o-commute-1 | normal | √ | √ | llm | control_climate | - |
| o-commute-2 | normal | √ | √ | llm | navigate | - |
| o-long-1 | normal | √ | √ | llm | get_vehicle_status,find_charging,search_safety_rules,navigate | - |
| o-long-2 | normal | √ | √ | llm | find_charging | - |
| o-park-1 | normal | √ | √ | llm | find_parking | - |
| o-media-1 | normal | √ | √ | llm | play_media | - |
| o-health-1 | normal | √ | √ | llm | control_climate | - |
| r-lost-1 | normal | √ | √ | llm | query_ride_order | - |
| r-lost-2 | normal | √ | √ | llm | query_ride_order,get_vehicle_status | - |
| r-lost-3 | normal | · | √ | llm | escalate_human | - |
| r-pa-1 | normal | √ | √ | llm | query_ride_order,modify_pickup_point | - |
| r-pa-2 | normal | · | √ | llm | query_ride_order | - |
| r-dc-1 | normal | √ | √ | llm | query_ride_order,change_destination | - |
| r-dc-2 | normal | · | √ | llm | query_ride_order | - |
| r-ph-1 | normal | √ | √ | llm | escalate_human | - |
| r-ph-2 | normal | √ | √ | llm | search_safety_rules,control_climate,control_door,escalate_human | - |

## 失败清单（4 条）

- **o-tired-2**（normal）：已为您播放《高速提神电台》，希望音乐能帮您提提神～
- **r-lost-3**（normal）：您好，已为您将投诉升级至人工客服，客服工单号 CS653612BF，状态为‘已排队’，预计3分钟内接入，请稍等。
- **r-pa-2**（normal）：我查到您的订单 ORD-2102 已显示司机陈师傅驾驶沪A·T8899车辆已到达静安寺地铁站1号口，当前状态是‘已到达’。您想把上车点改成3号门，但当前订单已进入‘已到达’状态，系统暂不支持修改上车点。建议您先取消当前订单，重新下单时选择3
- **r-dc-2**（normal）：我查了下，您当前订单（ORD-2103）状态是‘onboard’，也就是车已经出发了，这时候系统不允许再修改上车点——这是为了保障行程安全和路线稳定。如果您需要临时加个便利店，建议等这次行程结束后，我帮您重新下单或设置途经点。

## 护栏拦截事件（0 次）

