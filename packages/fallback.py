"""降级回复"""

FALLBACK = {
    "zh": "系统暂时繁忙，请稍后再试。",
    "en": "Service temporarily unavailable. Please try again later.",
}


def get_fallback(lang: str = "zh") -> str:
    return FALLBACK.get(lang, FALLBACK["zh"])
