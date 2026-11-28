"""SQLAlchemy 2 持久化仓储：真正读写 PostgreSQL 表 taxonomy_tag_stats。

v1 的 MemoryStore 只是零依赖复现口径的适配器，评审指出迁移建出的表没有任何代码写入或读取。
本模块补上生产适配器：

* ORM 模型与 alembic/versions/0001_taxonomy_tag_stats.py 一一对应（列名、约束、索引）；
* run_daily 调用 replace_day() 时，DELETE 当天 + INSERT 新行在同一个事务里完成；
* 两个只读接口经 latest_for / day_rows / latest_day 查询该表，不再从内存字典取结果。

tag_id 在库里按统一技术约定存 UUID。样例标签（T1…T6）通过固定命名空间映射成确定性 UUID，
同一 tag_id 每次都得到同一个 UUID，便于复现和核对；UUID -> 业务 tag_id 的反查使用本仓储的
标签登记（上游 S2-TAX-002 的接口桩），不会把未知 UUID 误认成业务标签。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    insert,
    select,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from taxonomy_stats.models import TagRef, TagStat

# 固定命名空间：同一业务 tag_id 永远映射到同一个 UUID，重跑/补跑不会漂移。
_TAG_NAMESPACE = uuid.UUID("6f5c3f08-8b62-4f5e-9b3a-327300000001")


def tag_uuid(tag_id: str) -> uuid.UUID:
    return uuid.uuid5(_TAG_NAMESPACE, tag_id)


class Base(DeclarativeBase):
    """供 Alembic target_metadata 使用，便于后续 autogenerate 比对。"""


class TagStatRow(Base):
    """taxonomy_tag_stats 的 ORM 映射，与 0001 迁移的定义逐列对齐。"""

    __tablename__ = "taxonomy_tag_stats"
    __table_args__ = (
        UniqueConstraint("tag_id", "stat_date", name="uq_tag_stats_tag_day"),
        CheckConstraint("total >= 0 AND new_30d >= 0", name="ck_tag_stats_non_negative"),
        CheckConstraint("new_30d <= total", name="ck_tag_stats_window_subset"),
        Index("ix_tag_stats_dict_day", "dict_code", "stat_date"),
        Index("ix_tag_stats_day_total", "stat_date", "total"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dict_code: Mapped[str] = mapped_column(String(64), nullable=False)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    counts: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment='{"company":n,"supply_demand":n,"capability_card":n,"activity":n}',
    )
    total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    new_30d: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SqlAlchemyStore:
    """生产适配器：统计结果持久化在 PostgreSQL，来源事实仍由上游接口桩提供。

    tags / refs 是 S2-TAX-002 与 S2-CRM 的接口桩（description 允许 mock），
    统计结果（stats）没有内存副本 —— 所有读路径都打到 taxonomy_tag_stats。
    """

    def __init__(self, dsn: str | Engine) -> None:
        self.engine = dsn if isinstance(dsn, Engine) else create_engine(dsn, future=True)
        self.tags: dict[str, str] = {}       # tag_id -> dict_code（接口桩）
        self.refs: list[TagRef] = []          # 引用事实（接口桩）
        self._uuid_to_tag: dict[uuid.UUID, str] = {}

    # --- 上游接口桩 -----------------------------------------------------
    def add_tag(self, tag_id: str, dict_code: str) -> None:
        self.tags[tag_id] = dict_code
        self._uuid_to_tag[tag_uuid(tag_id)] = tag_id

    def add_ref(self, ref: TagRef) -> None:
        self.refs.append(ref)

    def has_tag(self, tag_id: str) -> bool:
        return tag_id in self.tags

    def tag_ids_for_dict(self, dict_code: str) -> set[str]:
        return {t for t, code in self.tags.items() if code == dict_code}

    # --- 结果表：按 tag_id + stat_date 覆盖当天 -------------------------
    def replace_day(self, stat_date: date, rows: dict[str, TagStat]) -> None:
        payload = [
            {
                "tag_id": tag_uuid(tag_id),
                "dict_code": stat.dict_code,
                "stat_date": stat_date,
                "counts": dict(stat.counts),
                "total": stat.total,
                "new_30d": stat.new_30d,
            }
            for tag_id, stat in rows.items()
        ]
        with Session(self.engine, expire_on_commit=False) as session:
            with session.begin():
                # 同一事务：先删当天全部行，再整批插入。唯一约束兜底防重。
                session.execute(delete(TagStatRow).where(TagStatRow.stat_date == stat_date))
                if payload:
                    session.execute(insert(TagStatRow), payload)

    def _to_stat(self, row: TagStatRow, tag_id: str | None = None) -> TagStat | None:
        resolved = tag_id or self._uuid_to_tag.get(row.tag_id)
        if resolved is None:
            return None  # 库里的未知 UUID 不暴露成业务标签
        return TagStat(
            tag_id=resolved,
            dict_code=row.dict_code,
            stat_date=row.stat_date,
            counts=dict(row.counts),
            total=row.total,
            new_30d=row.new_30d,
        )

    def day_rows(self, stat_date: date) -> list[TagStat]:
        with Session(self.engine, expire_on_commit=False) as session:
            rows = session.scalars(
                select(TagStatRow).where(TagStatRow.stat_date == stat_date)
            ).all()
        stats = [self._to_stat(r) for r in rows]
        return sorted((s for s in stats if s is not None), key=lambda s: s.tag_id)

    def latest_for(self, tag_id: str) -> TagStat | None:
        with Session(self.engine, expire_on_commit=False) as session:
            row = session.scalars(
                select(TagStatRow)
                .where(TagStatRow.tag_id == tag_uuid(tag_id))
                .order_by(TagStatRow.stat_date.desc())
                .limit(1)
            ).first()
        return self._to_stat(row, tag_id) if row is not None else None

    def latest_day(self) -> date | None:
        with Session(self.engine) as session:
            return session.scalar(select(func.max(TagStatRow.stat_date)))

    def row_count(self, stat_date: date | None = None) -> int:
        """给测试/运维用的直接计数：绕过任何内存状态，直接查库。"""
        stmt = select(func.count()).select_from(TagStatRow)
        with Session(self.engine) as session:
            if stat_date is not None:
                return int(session.scalar(stmt.where(TagStatRow.stat_date == stat_date)) or 0)
            return int(session.scalar(stmt) or 0)
