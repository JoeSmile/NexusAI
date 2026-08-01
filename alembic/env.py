#!/usr/bin/env python3
"""Alembic环境配置文件

两套 ORM Base(models + pgvector)合并为单一 target_metadata:
- 会话/消息表(chat_sessions / chat_messages)仅存在于 pgvector Base
- 其余表取并集,保证 autogenerate / upgrade 覆盖完整 schema
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import MetaData, engine_from_config, pool

from alembic import context

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))
# 导入配置和数据库模型
from config import Config
from backend.database.models import Base as ModelsBase
from backend.database.pgvector_session import Base as VectorBase

# 这是Alembic配置对象，提供了alembic.ini文件的访问
config = context.config

# 从环境变量 / Config 读取数据库 URL（默认 PostgreSQL + pgvector）
database_url = os.getenv(
    "DATABASE_URL",
    getattr(
        Config,
        "DATABASE_URL",
        "postgresql://contextgate:***@localhost:5432/contextgate",
    ),
)
config.set_main_option("sqlalchemy.url", database_url)

# 解释Python日志配置文件
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 合并两套 Base 的 metadata(表名无交集,直接并集)
_merged_metadata = MetaData()
for table in VectorBase.metadata.sorted_tables:
    table.to_metadata(_merged_metadata)
for table in ModelsBase.metadata.sorted_tables:
    table.to_metadata(_merged_metadata)
target_metadata = _merged_metadata


def run_migrations_offline() -> None:
    """在'离线'模式下运行迁移。

    这将配置上下文仅使用URL，而不是Engine，
    尽管在这里也可以接受一个Engine。
    通过跳过Engine创建，我们甚至不需要DBAPI可用。

    这里调用context.execute()会将给定的字符串输出到脚本输出。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在'在线'模式下运行迁移。

    在这种情况下，我们需要创建一个Engine
    并将连接与上下文关联。
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
