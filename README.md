# 标签使用统计 · #3273

对应工单 **S2-TAX-013**。范围限定在「每日统计任务 → taxonomy_tag_stats → 两个只读接口」，
标签本体与引用来源的写入（S2-TAX-002、S2-CRM）不在本单内，用样例引用事实代替。

## 1. 目录

```
taxonomy_stats/models.py     TagRef（引用事实）、TagStat（结果行）、SOURCES、30 天窗口
taxonomy_stats/aggregate.py  统计口径（纯函数）+ top_tags / zero_ref_tags
taxonomy_stats/store.py      存储边界：结果按 (tag_id, stat_date) 唯一，按日替换
taxonomy_stats/service.py    每日任务 run_daily，返回可逐字比对的 digest
taxonomy_stats/handlers.py   用例层（框架无关）：(status, body)
taxonomy_stats/routes.py     FastAPI 适配层（两个只读接口）
tests/test_acceptance.py     三条验收标准 + 口径边界
tests/test_http.py           HTTP 层（缺 fastapi 时整类跳过）
alembic/versions/0001_taxonomy_tag_stats.py
```

## 2. 口径（容易写反的两处）

| 指标 | 定义 | 陷阱 |
|---|---|---|
| `counts` / `total` | 四个来源的引用次数与总和，**全量**，不受时间窗口影响 | 把窗口套到 total 上，会让老标签的引用凭空消失 |
| `new_30d` | `created_at >= stat_date - 29 天` 的引用次数 | 窗口是 30 天含当天，不是 31 天；用 `-30` 会多算一天 |
| `zero_reference` | `total == 0` 的标签，按 tag_id 升序 | 用 `new_30d == 0` 筛会把"老标签"误判成"零引用"，清理时误停用 |
| `top_referenced` | 按 `total` 降序，**同分按 tag_id 升序** | 同分不定序 → 两次调用顺序不同，前端展示抖动 |

## 3. 幂等怎么保证（AC-3）

不是「先查有没有再插」，而是**按日整批替换**：`replace_day()` 先删该 `stat_date` 的全部行，再整批写入。
配合表上的 `uq_tag_stats_tag_day (tag_id, stat_date)`，重跑同一天只可能覆盖，不可能插重。
`run_daily()` 返回对当日全部行做 sha256 得到的 `digest`，两次运行 digest 相同即为幂等证据。

## 4. 运行与测试

```bash
python -m unittest discover -s tests -t . -v        # 9 passed（零第三方依赖）
python -m pip install fastapi httpx                 # 可选：跑 HTTP 层 3 个用例
DATABASE_URL='postgresql+psycopg://u:p@localhost:5432/tax' alembic upgrade head --sql
DATABASE_URL='postgresql+psycopg://u:p@localhost:5432/tax' alembic downgrade 0001_taxonomy_tag_stats:base --sql
```

## 5. 验收对照

| # | 验收原文 | 用例 | 实测 |
|---|---|---|---|
| 1 | 统计结果与样例数据的手工计数一致（测试通过） | `test_ac1_stats_equal_hand_count`、`test_ac1_refs_outside_window_still_count_in_total` | 6 个标签 × 4 来源 × (total, new_30d) 逐格等于手算表；总数 10 == 样例引用条数；窗口外引用计入 total 但不计入 new_30d |
| 2 | 零引用标签列表正确（测试通过） | `test_ac2_zero_reference_tags`、`test_ac2_top_referenced_is_stable_on_ties` | 返回 `["T5"]`（T5 无任何引用）；top 列表同分时按 tag_id 升序稳定 |
| 3 | 统计任务重复运行结果不变（测试通过） | `test_ac3_second_run_changes_nothing`、`test_ac3_new_day_does_not_touch_old_day` | 两次 digest 相同、行数不变、表内 6 行；跑新的一天不影响旧日结果 |

## 6. 边界与取舍

- **脏数据不放大**：引用里出现未知 `tag_id` 直接忽略，不新建统计行 —— 否则清理零引用时会被幽灵标签干扰。
- **无引用不删行**：`total=0` 的标签照样写一行，前端才能展示"零引用"；缺行与零值是两种语义。
- **统计日期来自调用方**：`run_daily(store, stat_date)` 显式传入，不在函数里取 `today()`，补跑与回放才能重现。
- **只读接口无权限码**：与知识管理员角色一致；写入口（标签 CRUD）属于别的工单。

## 7. 不在本单范围

标签 CRUD 与字典层级（S2-TAX-001/002）、引用来源的写入与去重（S2-CRM）、
定时调度器实现（用 cron / 平台调度调用 `run_daily` 即可）、前端页面。
