from __future__ import annotations

SERIES_DEFAULT_BASE_URL: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}

_ALLOWED = frozenset(SERIES_DEFAULT_BASE_URL)


def normalize_series(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in ("dashscope", "tongyi", "taobao_qwen"):
        return "qwen"
    if s not in _ALLOWED:
        raise ValueError(f"unsupported_series:{s}")
    return s


def default_base_url(series: str) -> str:
    return SERIES_DEFAULT_BASE_URL[normalize_series(series)]


def infer_series_from_model(model: str) -> str | None:
    m = (model or "").strip().lower()
    if m.startswith("deepseek"):
        return "deepseek"
    if m.startswith("qwen") or m.startswith("qwq"):
        return "qwen"
    return None
