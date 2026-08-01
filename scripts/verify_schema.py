"""验证数据库 schema 与 ORM 模型完全一致(迁移正确性验收)。

用法: DATABASE_URL=postgresql://... uv run python scripts/verify_schema.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import MetaData, create_engine, inspect
from sqlalchemy.dialects import postgresql

from backend.database.models import Base as ModelsBase
from backend.database.pgvector_session import Base as VectorBase

# 合并两套 metadata(与 alembic/env.py 逻辑一致)
merged = MetaData()
for table in VectorBase.metadata.sorted_tables:
    table.to_metadata(merged)
for table in ModelsBase.metadata.sorted_tables:
    if table.name in merged.tables:
        continue
    table.to_metadata(merged)

url = os.getenv("DATABASE_URL", "postgresql://contextgate:contextgate_local@localhost:5432/contextgate")
engine = create_engine(url)
inspector = inspect(engine)

errors = []

# 1) 表级对比
db_tables = set(inspector.get_table_names())
model_tables = set(merged.tables.keys())
# alembic_version 是迁移自身的记账表,不算多余
EXPECTED_EXTRA = {"alembic_version"}
for t in sorted(model_tables - db_tables):
    errors.append(f"[缺失表] {t}")
for t in sorted(db_tables - model_tables - EXPECTED_EXTRA):
    errors.append(f"[多余表] {t}")

# PostgreSQL 中 sa.Float() 即 double precision,FLOAT/DOUBLE PRECISION 等价
FLOAT_COMPAT = {"FLOAT": {"DOUBLE PRECISION"}, "DOUBLE PRECISION": {"FLOAT"}}

# 2) 列级对比
for table_name in sorted(model_tables & db_tables):
    model_table = merged.tables[table_name]
    db_cols = {c["name"]: c for c in inspector.get_columns(table_name)}
    model_cols = {c.name: c for c in model_table.columns}

    for col_name in sorted(model_cols.keys() - db_cols.keys()):
        errors.append(f"[缺失列] {table_name}.{col_name}")
    for col_name in sorted(db_cols.keys() - model_cols.keys()):
        errors.append(f"[多余列] {table_name}.{col_name}")

    # 类型对比(映射到 postgresql 方言字符串)
    for col_name in sorted(model_cols.keys() & db_cols.keys()):
        model_col = model_cols[col_name]
        db_col = db_cols[col_name]
        model_type = model_col.type.compile(dialect=postgresql.dialect())
        db_type = db_col["type"].compile(dialect=postgresql.dialect())
        if model_type != db_type and db_type not in FLOAT_COMPAT.get(model_type, set()):
            errors.append(
                f"[类型不符] {table_name}.{col_name}: 模型={model_type}, DB={db_type}"
            )
        if model_col.nullable != db_col["nullable"]:
            errors.append(
                f"[可空不符] {table_name}.{col_name}: 模型 nullable={model_col.nullable}, "
                f"DB nullable={db_col['nullable']}"
            )

# 3) 唯一约束/索引抽查: 模型里的 unique 约束必须在 DB 存在
for table_name in sorted(model_tables & db_tables):
    model_table = merged.tables[table_name]
    db_unique = {tuple(sorted(u["column_names"])) for u in inspector.get_unique_constraints(table_name)}
    for constraint in model_table.constraints:
        if constraint.__class__.__name__ == "UniqueConstraint":
            cols = tuple(sorted(c.name for c in constraint.columns))
            if cols not in db_unique:
                errors.append(f"[缺唯一约束] {table_name}{cols}")

if errors:
    print(f"❌ 发现 {len(errors)} 处不一致:")
    for e in errors:
        print("  ", e)
    sys.exit(1)
else:
    print(f"✅ schema 与模型完全一致: {len(model_tables)} 张表, 全部通过")
