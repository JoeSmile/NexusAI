-- 首次初始化数据卷时确保 langfuse 独立库存在(docker-entrypoint-initdb.d 机制,
-- 与 init_pgvector.sql 同批次执行;幂等,已存在则跳过)
-- 注意: 本文件仅在 postgres 数据卷为空时执行;已有卷请手工确认 langfuse 库存在。
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
