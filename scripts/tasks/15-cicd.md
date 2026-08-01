# Task 15: CI/CD — GitHub Actions

## Subtask 15.01: lint + typecheck

**创建:** `.github/workflows/ci.yml`
```yaml
name: CI
on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run mypy backend/
```

## Subtask 15.02: 单元测试 + Coverage

在 `ci.yml` 追加：
```yaml
      - run: uv run pytest tests/ -v --cov=backend --cov-fail-under=70
```

## Subtask 15.03: Docker 构建

**创建:** `.github/workflows/docker.yml`
```yaml
name: Docker Build
on:
  push:
    tags: ["v*"]

jobs:
  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - run: docker build -t ghcr.io/joe/contextgate:latest .
      - run: docker push ghcr.io/joe/contextgate:latest
```

## 验证

`git push` → Actions 页自动跑 lint + test + build
