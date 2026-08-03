# 外测报告（API-Bank · 对话 → API 请求生成）

- 日期：2026-08-07 21:05｜用例：779 条｜（离线重建）
- 定位：**公开基准自测**（多轮对话理解 → API 调用生成）；口径为**简化比对**，不对齐官方脚本数字
- 判分口径 v2：① `API-Request:` 提取 + AST 解析（含数据集/输出引号嵌套字面量修复）；② 日期归一（英文日期→ISO）；③ **ToolSearcher keywords 柔性匹配**——官方论文 §4.1：keywords 为开放检索式、无唯一正解（官方跑真实检索引擎判最终工具），本地以词袋交集近似「能否检索到目标工具」（含驼峰切分；翻转样本经抽样核查）
- 生成侧 v2：系统提示补格式纪律（禁模板占位符回显 / 单行输出 / ToolSearcher 输出自然语言短语）
- 覆盖：L1 对话→单请求（399）｜L2 ToolSearcher 请求（135）｜L3-batch 多步轨迹逐步作答（245，零样本版）

## 总指标

| 级别 | 条数 | 通过 | 通过率 |
|---|---|---|---|
| L1 对话→API 请求 | 399 | 349 | 87.5% |
| L2 ToolSearcher | 135 | 95 | 70.4% |
| L3 多步轨迹（逐步） | 245 | 104 | 42.4% |
| **总体** | 779 | 548 | 70.3% |

## 失败清单（共 231，前 20）

| 条目 | 级别 | 模型调用 | 期望 | 原因 |
|---|---|---|---|---|
| L1_ModifyRegistration-QueryHealthD | 1 | QueryHealthData | QueryHealthData(user_id=J46801, start_time=2023-03-05 00:00: | arg:end_time='2023-03-12 23:59:59'≠'2023-03-12 00: |
| L1_SymptomSearch-AppointmentRegist | 1 | AppointmentRegistration | AppointmentRegistration(patient_name=Emily Smith, date=2023- | arg:doctor_name='John'≠'Dr. John' |
| L1_AddAgenda-AddMeeting-GetUserTok | 1 | AddAgenda | GetUserToken(username=JohnDoe, password=pass123) | name:AddAgenda!=GetUserToken |
| L1_AddAgenda-AddMeeting-GetUserTok | 1 | AddAgenda | AddAgenda(token=a9s8d7f6g5h4j3k2l1, content=Meeting with cli | arg:content='Meeting with clients'≠'Meeting with c |
| L1_AddAgenda-AddMeeting-GetUserTok | 1 | AddAgenda | AddAgenda(token=a9s8d7f6g5h4j3k2l1, content=Meeting with cli | arg:content='Meeting with clients'≠'Meeting with c |
| L1_CancelRegistration-RecordHealth | 1 | QueryRegistration | QueryRegistration(patient_name=Jane Smith, date=2023-05-20) | arg:patient_name='Sarah Johnson'≠'Jane Smith' |
| L1_ForgotPassword-RegisterUser-Del | 1 | ForgotPassword | ForgotPassword(status=Verification Code, verification_code=9 | extra:username |
| L1_GetReminder-level-1-1.jsonl#2 | 1 | QueryReminder | QueryReminder(token=a9s8d7f6g5h4j3k2l1, content=Call mom, ti | arg:content='call my mom'≠'Call mom' |
| L1_ModifyPassword-ForgotPassword-D | 1 | ForgotPassword | ForgotPassword(status=Verification Code, verification_code=9 | extra:username |
| L1_ModifyPassword-ForgotPassword-D | 1 | GetUserToken | GetUserToken(username=user1, password=user1newpass) | arg:password='user1pass'≠'user1newpass' |
| L1_AddAgenda-level-1-2.jsonl#0 | 1 | AddAgenda | GetUserToken(username=foo, password=bar) | name:AddAgenda!=GetUserToken |
| L1_ModifyPassword-RegisterUser-Get | 1 | ModifyPassword | GetUserToken(username=admin, password=adminpass) | name:ModifyPassword!=GetUserToken |
| L1_CancelTimedSwitch-level-1-2.jso | 1 | CancelTimedSwitch | CancelTimedSwitch(device_id=10000025, time=2023-03-19 09:30: | missing:device_id |
| L1_ModifyRegistration-EmergencyKno | 1 | EmergencyKnowledge | EmergencyKnowledge(symptom=fatigue) | arg:symptom='general fatigue'≠'fatigue' |
| L1_AddAgenda-AddMeeting-GetUserTok | 1 | AddAgenda | GetUserToken(username=JohnDoe, password=pass123) | name:AddAgenda!=GetUserToken |
| L1_DeleteReminder-level-1-1.jsonl# | 1 | DeleteReminder | DeleteReminder(token=q9w8e7r6t5y4u3i2o1, content=Call dentis | arg:content='call the dentist'≠'Call dentist' |
| L1_CancelTimedSwitch-level-1-4.jso | 1 | CancelTimedSwitch | CancelTimedSwitch(device_id=10000025, time=2023-03-19 09:30: | missing:device_id |
| L1_CancelTimedSwitch-level-1-3.jso | 1 | CancelTimedSwitch | CancelTimedSwitch(device_id=10000025, time=2023-03-19 09:30: | missing:device_id |
| L1_CancelTimedSwitch-level-1-1.jso | 1 | CancelTimedSwitch | CancelTimedSwitch(device_id=10000025, time=2023-03-19 09:30: | missing:device_id |
| L1_DeleteAccount-ModifyPassword-Ge | 1 | DeleteAccount | GetUserToken(username=foo, password=bar) | name:DeleteAccount!=GetUserToken |