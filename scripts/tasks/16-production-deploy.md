# Task 16: 生产部署配置

## Subtask 16.01: docker-compose.prod.yml

**创建:** `docker-compose.prod.yml`
- `contextgate`: 不挂载本地代码（构建时打包），`restart: always`
- `postgres`: 数据卷持久化
- `langfuse`: `NEXTAUTH_SECRET`/`SALT` 用环境变量注入
- `nginx`: 反向代理 + HTTPS

```yaml
services:
  contextgate:
    build: .
    ports: ["8000:8000"]
    env_file: config.env
    depends_on: [postgres, langfuse]
    restart: always

  postgres:
    image: pgvector/pgvector:pg16
    volumes: [pgdata:/var/lib/postgresql/data]
    environment:
      POSTGRES_DB: contextgate
      POSTGRES_USER: contextgate
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U contextgate"]

  langfuse:
    image: ghcr.io/langfuse/langfuse:latest
    environment:
      DATABASE_URL: postgresql://contextgate:${DB_PASSWORD}@postgres/contextgate
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET}
      SALT: ${SALT}

  nginx:
    image: nginx:alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./deploy/nginx.conf:/etc/nginx/nginx.conf
      - ./deploy/ssl:/etc/nginx/ssl
    depends_on: [contextgate, langfuse]

volumes:
  pgdata:
```

## Subtask 16.02: nginx.conf

**创建:** `deploy/nginx.conf`
- `/api/*` → contextgate:8000
- `/langfuse/*` → langfuse:3000
- 限制请求体 20MB
- 速率限制 100 req/s per IP
- CORS + HTTPS

```nginx
server {
    listen 443 ssl;
    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    client_max_body_size 20M;

    location /api/ {
        proxy_pass http://contextgate:8000/;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /langfuse/ {
        proxy_pass http://langfuse:3000/;
    }
}
```

## 验证

```bash
docker compose -f docker-compose.prod.yml config  # → 语法正确
```
