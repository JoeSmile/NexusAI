import os
from pathlib import Path
from dotenv import load_dotenv

# 加载.env配置文件
env_path = Path(__file__).parent / 'config.env'
load_dotenv(env_path)

# 获取项目根目录
PROJECT_ROOT = os.getenv('PROJECT_ROOT', str(Path(__file__).parent))

class Config:
    # ── LLM API Key 安全治理 ──
    # DB 加密存储 + KeyManager 运行时解密；保留 env fallback 过渡
    LLM_KEY_MASTER_KEY = os.getenv("LLM_KEY_MASTER_KEY", "")
    LLM_API_KEY_FALLBACK = (
        os.getenv("LLM_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )
    LLM_BASE_URL_FALLBACK = (
        os.getenv("LLM_BASE_URL")
        or os.getenv("DEEPSEEK_BASE_URL")
        or os.getenv("API_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    )

    # 兼容层：遗留代码仍读 LLM_API_KEY / LLM_BASE_URL
    LLM_API_KEY = LLM_API_KEY_FALLBACK
    LLM_BASE_URL = LLM_BASE_URL_FALLBACK

    # 为了兼容性，保留旧的属性名（指向统一的配置）
    OPENAI_API_KEY = LLM_API_KEY
    API_BASE_URL = LLM_BASE_URL
    DASHSCOPE_API_KEY = LLM_API_KEY
    
    # LangChain配置
    LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")
    # 禁用LangSmith以避免403错误
    LANGCHAIN_ENDPOINT = os.getenv("LANGCHAIN_ENDPOINT", "")
    
    # 数据库配置（PostgreSQL + pgvector）
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://contextgate:contextgate_local@localhost:5432/contextgate",
    )
    
    # 模型配置
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL") or os.getenv("DEEPSEEK_MODEL", "glm-5.1")
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1000"))
    
    # 服务器配置
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"

    # Hermes 风格工作区自动化（参考 Nous Hermes Agent 工具与 MCP 文档）
    HERMES_TOOLS_ENABLED = os.getenv("HERMES_TOOLS_ENABLED", "0").lower() in ("1", "true", "yes")
    HERMES_WORKSPACE_ROOT = os.getenv("HERMES_WORKSPACE_ROOT", "").strip()
    HERMES_WEB_FETCH_ENABLED = os.getenv("HERMES_WEB_FETCH_ENABLED", "0").lower() in ("1", "true", "yes")
    HERMES_WEB_ALLOWLIST = os.getenv("HERMES_WEB_ALLOWLIST", "").strip()
    HERMES_WEB_MAX_BYTES = int(os.getenv("HERMES_WEB_MAX_BYTES", "524288"))
    HERMES_SHELL_ENABLED = os.getenv("HERMES_SHELL_ENABLED", "0").lower() in ("1", "true", "yes")
    HERMES_SHELL_TIMEOUT_SEC = int(os.getenv("HERMES_SHELL_TIMEOUT_SEC", "60"))
