# 项目脚本

这里存放不属于应用运行时源码的一次性工具、维护命令和兼容入口。

## 常用脚本

- `init_rag_knowledge.py`：初始化 RAG 知识库（企业文档入库）。
- `seed_api_keys.py` / `seed_pgvector.py`：写入开发用 API Key 与示例数据（`make seed`）。
- `verify_schema.py`：校验数据库 schema 与 ORM 模型完全一致（防漂移）。
- `audit_consistency.py`：全仓一致性审计（残留引用 / 断链 / make target / env 键 / import 冒烟）。
- `start_services.sh` / `restart_services.sh`：Linux 运维脚本。

## 数据库迁移

表结构统一由 Alembic 管理，不再需要包装脚本：

```bash
uv run alembic upgrade head    # 建表/升级
uv run alembic current         # 查看当前版本
uv run alembic downgrade -1    # 回退一步
```

## RAG 知识库

```bash
uv run python scripts/init_rag_knowledge.py
```

## Schema 校验

```bash
uv run python scripts/verify_schema.py
```

所有命令都从项目根目录执行。
