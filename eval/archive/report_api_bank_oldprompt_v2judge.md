# 外测报告（API-Bank · 对话 → API 请求生成）

- 日期：2026-08-07 18:43｜用例：779 条｜（判分口径 v2：keywords 柔性匹配）
- 定位：**公开基准自测**（多轮对话理解 → API 调用生成）；口径为**简化比对**，不对齐官方脚本数字
- 口径 v2 说明：① `API-Request:` 提取 + AST 解析（含引号嵌套字面量修复）；② 日期归一（英文日期→ISO）；
  ③ **ToolSearcher keywords 柔性匹配**——开放语义检索式（官方论文 §4.1：其本身无唯一正解，官方跑真实检索引擎判最终工具），
  以词袋交集近似'能否检索到目标工具'（含驼峰切分；抽查 8/8 语义等价样本确认合理）
- 覆盖：L1 对话→单请求（399）｜L2 ToolSearcher 请求（135）｜L3-batch 多步轨迹逐步作答（245，零样本版）

## 总指标（判分 v2）

| 级别 | 条数 | 通过 | 通过率 |
|---|---|---|---|
| L1 对话→API 请求 | 399 | 343 | 86.0% |
| L2 ToolSearcher | 135 | 80 | 59.3% |
| L3 多步轨迹（逐步） | 245 | 64 | 26.1% |
| **总体** | 779 | 487 | 62.5% |

> 对照：判分 v1（keywords 严格等值）= 430/779 = 55.2%；v2 修正 57 条语义等价样本（55.2%→62.5%，+7.3pp）；口径修正的合理性论证（官方语义 + 抽样核查）见 CHANGELOG。

## 失败清单（共 292，前 20）

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
| L1_RecordHealthData-AppointmentReg | 1 | AppointmentRegistration | AppointmentRegistration(patient_name=John, date=2023-09-03,  | arg:doctor_name='Dr. Smith'≠'Smith' |
| L1_ModifyPassword-RegisterUser-Get | 1 | ModifyPassword | GetUserToken(username=admin, password=adminpass) | name:ModifyPassword!=GetUserToken |
| L1_CancelTimedSwitch-level-1-2.jso | 1 | CancelTimedSwitch | CancelTimedSwitch(device_id=10000025, time=2023-03-19 09:30: | missing:device_id |
| L1_Calculator-level-1-3.jsonl#2 | 1 | Calculator | Calculator(formula=5*10) | arg:formula='5 * 10'≠'5*10' |
| L1_ModifyRegistration-EmergencyKno | 1 | EmergencyKnowledge | EmergencyKnowledge(symptom=fatigue) | arg:symptom='general fatigue'≠'fatigue' |
| L1_GetToday-ModifyMeeting-ModifyAl | 1 | ModifyMeeting | GetUserToken(username=JaneSmith, password=password) | name:ModifyMeeting!=GetUserToken |
| L1_AddAgenda-AddMeeting-GetUserTok | 1 | AddAgenda | GetUserToken(username=JohnDoe, password=pass123) | name:AddAgenda!=GetUserToken |
| L1_DeleteReminder-level-1-1.jsonl# | 1 | DeleteReminder | DeleteReminder(token=q9w8e7r6t5y4u3i2o1, content=Call dentis | arg:content='call the dentist'≠'Call dentist' |
| L1_CancelTimedSwitch-level-1-4.jso | 1 | CancelTimedSwitch | CancelTimedSwitch(device_id=10000025, time=2023-03-19 09:30: | missing:device_id |