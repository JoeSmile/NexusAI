from packages.llm_series import (
    SERIES_DEFAULT_BASE_URL,
    default_base_url,
    infer_series_from_model,
    normalize_series,
)


def test_defaults():
    assert default_base_url("deepseek") == "https://api.deepseek.com/v1"
    assert default_base_url("qwen") == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert "deepseek" in SERIES_DEFAULT_BASE_URL


def test_normalize_and_infer():
    assert normalize_series("DeepSeek") == "deepseek"
    assert infer_series_from_model("deepseek-v4-flash") == "deepseek"
    assert infer_series_from_model("qwen-plus") == "qwen"
    assert infer_series_from_model("gpt-4o") is None
