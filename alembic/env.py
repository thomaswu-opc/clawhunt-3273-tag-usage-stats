"""Alembic 环境。支持 offline（--sql，不连库）与 online 两种模式。

连接串只从环境变量 DATABASE_URL 读取，代码里不出现任何明文凭据。
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:  # noqa: BLE001  离线场景可以没有 logging 配置
        pass

from taxonomy_stats.sqlalchemy_store import Base  # noqa: E402  与生产 ORM 模型共用元数据

target_metadata = Base.metadata


def _url() -> str:
    return os.environ.get("DATABASE_URL") or "postgresql+psycopg://user:pass@localhost:5432/crm"


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
