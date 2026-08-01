-- pgvector 初始化脚本（仅 PostgreSQL 容器首次启动时由 docker-entrypoint 执行）
--
-- 职责只保留一项：创建 vector 扩展。
-- 所有业务表结构统一由 Alembic 迁移管理：alembic upgrade head
-- （见 Makefile 的 db-init 目标；历史版本曾在此建表并残留 emotion 列与孤儿表，
--   已全部移除，勿再在此处建表。）
CREATE EXTENSION IF NOT EXISTS vector;
