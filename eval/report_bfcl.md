# 外测报告（BFCL v3 子集 · 函数调用）

- 日期：2026-08-07 14:27｜用例：1240 条｜总耗时：28.6 min
- 定位：**公开基准自测**（函数调用准确率）；口径为**简化比对**（见 `eval/run_bfcl.py` docstring），不对齐官方榜单数字

## 总指标

| 类别 | 条数 | 通过 | 通过率 |
|---|---|---|---|
| irrelevance | 240 | 208 | 86.7% |
| multiple | 200 | 183 | 91.5% |
| parallel | 200 | 176 | 88.0% |
| parallel_multiple | 200 | 167 | 83.5% |
| simple | 400 | 380 | 95.0% |
| **总体** | 1240 | 1114 | 89.8% |

## 失败清单（共 126，前 20）

| id | 类别 | 模型调用 | 期望 | 原因 |
|---|---|---|---|---|
| simple_13 | simple | calculate_area_under_curve | calculate_area_under_curve | arg:function='x^2'∉['x**2', 'lambda x: x**2', 'y=x**2'] |
| simple_14 | simple | calculate_derivative | calculate_derivative | arg:function='3x^2 + 2x - 1'∉['3x**2 + 2x - 1', 'lambda  |
| simple_15 | simple | integrate | integrate | arg:function='x^3'∉['x**3', 'lambda x: x**3'] |
| simple_16 | simple | calculus.derivative | calculus.derivative | arg:function='2*x**2'∉['2x**2', 'lambda x: 2x**2'] |
| simple_17 | simple | get_prime_factors | get_prime_factors | arg:formatted=False∉[True, ''] |
| simple_35 | simple | vegan_restaurant.find_nearby | vegan_restaurant.find_nearby | arg:operating_hours=11∉[23] |
| simple_51 | simple | calculate_entropy_change | calculate_entropy_change | arg:isothermal=False∉['', True] |
| simple_55 | simple | biology.get_cell_info | biology.get_cell_info | arg:cell_type='human cell'∉['human'] |
| simple_89 | simple | db_fetch_records | db_fetch_records | arg:conditions={'department': 'Science', 'school': 'Blue |
| simple_172 | simple | ∅ | legal_case.fetch | n_mismatch:pred=0 gold=1 |
| simple_200 | simple | calculate_emissions | calculate_emissions | arg:fuel_type='gasoline'∉['gas'] |
| simple_234 | simple | history_eu.fetch_events | history_eu.fetch_events | arg:region='Europe'∉['Northern', 'Southern', 'Eastern'] |
| simple_247 | simple | historical_contrib.get_contrib | historical_contrib.get_contrib | arg:category='Physics'∉['', 'all'] |
| simple_267 | simple | find_exhibition | find_exhibition | arg:location='New York, NY'∉['New York City, NY'] |
| simple_363 | simple | restaurant_search.find_closest | find_closest | name:restaurant_search.find_closest!=find_closest |
| simple_367 | simple | find_recipe | find_recipe | arg:recipe_type='brownies'∉['dessert'] |
| simple_370 | simple | safeway.order | safeway.order | arg:quantity=[3, 5]∉[[3, 1]] |
| simple_375 | simple | walmart.check_price | walmart.check_price | arg:items=['pumpkin', 'egg']∉[['pumpkins', 'eggs'], ['pu |
| simple_382 | simple | book_hotel | book_hotel | arg:room_type='single room'∉['single'] |
| simple_394 | simple | maps.get_distance_duration | maps.get_distance_duration | arg:start_location='Eiffel Tower, Paris'∉['Eiffel Tower' |