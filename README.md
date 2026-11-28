# 标签使用统计 · #3273（v2：SQLAlchemy 2 持久化）

对应工单 **S2-TAX-013**。范围：每日统计任务 → `taxonomy_tag_stats` → 两个只读接口。
标签本体与引用来源的写入（S2-TAX-002、S2-CRM）不在本单内，用接口桩/样例事实代替。

## 1. v2 修了什么（针对第 1/3 轮返工）

| 评审意见 | v2 处理 | 位置 |
|---|---|---|
| [blocker] 迁移建表后没有任何代码写入/读取，只有 `MemoryStore` | 新增 SQLAlchemy 2 ORM 与持久化仓储；`run_daily()` 真的 `DELETE 当天 + INSERT` 到 `taxonomy_tag_stats`，两个只读接口经仓储查询该表 | `taxonomy_stats/sqlalchemy_store.py`、`service.py`、`handlers.py` |
| [major] 只做了 `alembic --sql` 离线渲染、测试跑在内存实现上 | 在真实 PostgreSQL 16.2 上执行 `downgrade base` → `upgrade head` → `check` → `downgrade -1` → `upgrade head`；18 个用例在迁移后的库上重跑（不调用 `create_all`） | `evidence/migration.txt`、`evidence/test-run.txt` |

ORM 模型与 0001 迁移逐列对齐（唯一约束、两个 CHECK、两个索引、`counts` 列注释），
`alembic check` 输出 `No new upgrade operations detected.`

## 2. 目录

```
taxonomy_stats/models.py            TagRef / TagStat / SOURCES / 30 天窗口
taxonomy_stats/aggregate.py         统计口径（纯函数）+ top_tags / zero_ref_tags
taxonomy_stats/store.py             MemoryStore：零依赖口径复现适配器
taxonomy_stats/sqlalchemy_store.py  SQLAlchemy 2 持久化仓储（生产适配器，v2 新增）
taxonomy_stats/service.py           run_daily(store, stat_date, days) —— 写库后读回并算 digest
taxonomy_stats/handlers.py          两个只读用例层接口（读路径打到结果表）
taxonomy_stats/routes.py            FastAPI 适配层
tests/test_acceptance.py            口径边界与三条 AC（内存实现，零依赖）
tests/test_postgres_acceptance.py   三条 AC 在 PostgreSQL 上的重跑（v2 新增）
alembic/versions/0001_taxonomy_tag_stats.py
evidence/{migration,test-run,gate}.txt
```

## 3. 口径（容易写反的两处）

| 指标 | 定义 | 陷阱 |
|---|---|---|
| `counts` / `total` | 四来源（company / supply_demand / capability_card / activity）引用次数与总和，**全量** | 把窗口套到 total 上会让老标签引用消失 |
| `new_30d` | `created_at >= stat_date - 29 天` 的引用次数 | 30 天含当天；用 `-30` 会多算一天 |
| `zero_reference` | `total == 0`，按 tag_id 升序 | 用 `new_30d == 0` 会把老标签误判可删 |
| `top_referenced` | 按 total 降序，同分按 tag_id 升序 | 同分不定序会导致展示抖动 |

写库时 `tag_id` 按统一技术约定存 UUID：样例业务标签 T1…T6 经固定命名空间
`uuid5` 映射为确定性 UUID，重跑/补跑不漂移；UUID → 业务 id 用上游标签登记反查，
未知 UUID 不暴露成业务标签。

## 4. 运行与复核（PostgreSQL 16）

```bash
python -m pip install -r requirements.txt
export DATABASE_URL='postgresql+psycopg://user:pass@localhost:5432/tax'

alembic downgrade base          # 从空库开始，可选
alembic upgrade head            # 真跑迁移，不是 --sql 渲染
alembic check                   # ORM 映射与库结构一致：No new upgrade operations detected.
alembic downgrade -1            # 可逆性验证
alembic upgrade head            # 回到 head

python -m pytest tests/ -v      # 18 passed：12 个口径/HTTP 用例 + 6 个 PostgreSQL 落库用例
```

本机验证用 `pgserver>=0.1.4`（内置 PostgreSQL 16.2 + pgvector，免管理员权限）起实例：

```python
import pgserver, time
db = pgserver.get_server("/path/to/pgdata")
print(db.get_uri())             # 拼成 postgresql+psycopg://... 写入 DATABASE_URL
time.sleep(3600)                # 验证期间保持服务存活
```

不设 `DATABASE_URL` 时，`tests/test_postgres_acceptance.py` 整类跳过，
其余 12 个用例仍零依赖可跑（`12 passed, 6 skipped`）。
测试只连接迁移后的库，**不调用 `create_all`**：表必须由 Alembic 建出来。

## 5. 验收对照（三条 AC 在 PostgreSQL 上的实测）

| # | 验收原文 | 落库用例 | 实测 |
|---|---|---|---|
| 1 | 统计结果与样例数据的手工计数一致 | `test_ac1_postgres_matches_hand_count`、`test_ac1_postgres_outside_window_still_counted` | 6 标签 × 4 来源 × (total,new_30d) 逐格等于写死的 `HAND` 表；总引用数 10；窗口外引用计入 total 不计入 new_30d；直接查库 6 行 |
| 2 | 零引用标签列表正确 | `test_ac2_postgres_zero_reference_tags` | 从结果表读出 `zero_reference=["T5"]`、`tag_count=5`、top 顺序 `T1,T4,T3,T2` 稳定 |
| 3 | 统计任务重复运行结果不变 | `test_ac3_postgres_rerun_is_idempotent` | 两次 digest/row_count 相同、逐行一致；库内仍 6 行无重复；跑新一天不动旧一天 |
| 接口 | 两个只读接口从结果表读 | `test_read_handlers_query_table_not_memory`、`test_http_endpoints_against_persisted_table` | 新开一个无任何内存统计的仓储，接口仍能读出刚落库的结果；HTTP 层同样通过 |

证据是原始输出：`evidence/migration.txt`（真实 upgrade/downgrade/check）、
`evidence/test-run.txt`（18 passed + 直接查表的行）、`evidence/gate.txt`（GATE: PASS）。

## 6. 边界与对接点

- 来源事实（tags / refs）仍是上游 S2-TAX-002 / S2-CRM 的接口桩；接生产时把 `store.tags` / `store.refs`
  换成对四张来源表的查询即可，`aggregate()` 与 `run_daily()` 不变。
- 统计日期由调用方显式传入；挂调度每日 01:00 调 `run_daily(store, yesterday)`。
- 脏 tag_id 忽略；零引用标签照样写一行（缺行与零值是两种语义）。
- 不含：标签 CRUD、引用来源去重、调度器、前端页面。
