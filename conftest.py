"""pytest 全局夹具 — 固定测试环境(APP_ENV=test + replay 回放)。"""

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "replay")
