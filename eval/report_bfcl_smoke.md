# 外测报告（BFCL v3 子集 · 函数调用）

- 日期：2026-08-02 23:15｜用例：40 条｜总耗时：0.6 min
- 定位：**公开基准自测**（函数调用准确率）；口径为**简化比对**（见 `eval/run_bfcl.py` docstring），不对齐官方榜单数字

## 总指标

| 类别 | 条数 | 通过 | 通过率 |
|---|---|---|---|
| irrelevance | 10 | 9 | 90.0% |
| multiple | 10 | 9 | 90.0% |
| parallel | 10 | 7 | 70.0% |
| simple | 10 | 10 | 100.0% |
| **总体** | 40 | 35 | 87.5% |

## 失败清单（共 5，前 20）

| id | 类别 | 模型调用 | 期望 | 原因 |
|---|---|---|---|---|
| multiple_7 | multiple | wildlife_population.assess_growth,ecological_impact.analyze | wildlife_population.assess_growth | n_mismatch:pred=2 gold=1 |
| parallel_5 | parallel | streaming_services.shows_list_and_ratings,streaming_services.shows_list_and_ratings | streaming_services.shows_list_and_ratings,streaming_services.shows_list_and_ratings | set_no_match(g0~p0:arg:sort_by_rating=False∉[True]) |
| parallel_8 | parallel | database_us_census.get_population,database_us_census.get_population,database_us_census.get_population,database_us_census.get_population | database_us_census.get_population,database_us_census.get_population,database_us_census.get_population,database_us_census.get_population | set_no_match(g0~p0:arg:year=2020∉['', 2000]) |
| parallel_9 | parallel | find_movie_showing | find_movie_showing,find_movie_showing | n_mismatch:pred=1 gold=2 |
| irrelevance_7 | irrelevance | math.integral_calculator |  | 误调用:1 次 |