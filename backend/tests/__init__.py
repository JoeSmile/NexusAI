"""
测试模块
包含单元测试、集成测试和端到端测试
"""

import asyncio
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, Mock

import pytest

# 测试配置
pytest_plugins = ["pytest_asyncio"]


class TestConfig:
    """测试配置"""
    TEST_DATABASE_URL = "sqlite:///./test.db"
    TEST_REDIS_URL = "redis://localhost:6379/1"
    TEST_OPENAI_API_KEY = "test-key"
    TEST_ENVIRONMENT = "testing"


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_config():
    """模拟配置"""
    
    config = Mock()
    config.database.url = TestConfig.TEST_DATABASE_URL
    config.redis.url = TestConfig.TEST_REDIS_URL
    config.openai.api_key = TestConfig.TEST_OPENAI_API_KEY
    config.environment = TestConfig.TEST_ENVIRONMENT
    config.debug = True
    
    return config


@pytest.fixture
def mock_logger():
    """模拟日志器"""
    
    logger = Mock()
    logger.debug = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.critical = Mock()
    
    return logger


@pytest.fixture
async def mock_database():
    """模拟数据库"""
    
    db = AsyncMock()
    db.connect = AsyncMock(return_value=True)
    db.disconnect = AsyncMock(return_value=True)
    db.execute_query = AsyncMock(return_value=[])
    db.health_check = AsyncMock(return_value={"status": "healthy"})
    
    return db


@pytest.fixture
async def mock_cache():
    """模拟缓存"""
    
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=True)
    cache.delete = AsyncMock(return_value=True)
    cache.exists = AsyncMock(return_value=False)
    
    return cache


@pytest.fixture
def sample_chat_request():
    """示例聊天请求"""
    return {
        "message": "你好，请帮我整理今天的会议纪要",
        "user_id": "test_user_123",
        "session_id": "test_session_456",
        "use_memory": True,
        "use_rag": True
    }


@pytest.fixture
def sample_chat_response():
    """示例聊天响应"""
    return {
        "success": True,
        "message": "回复生成成功",
        "response": "已为您整理会议纪要，要点如下：",
        "session_id": "test_session_456",
        "timestamp": "2025-10-16T14:30:00Z",
        "status_code": 200,
        "context": {
            "memories_count": 3,
            "has_profile": True,
            "used_rag": False
        }
    }


@pytest.fixture
def sample_memory():
    """示例记忆"""
    return {
        "id": "memory_123",
        "content": "用户偏好结构化的工作汇报",
        "importance": 0.8,
        "timestamp": "2025-10-16T14:30:00Z",
        "metadata": {
            "user_id": "test_user_123",
            "session_id": "test_session_456",
            "source": "user_message"
        }
    }


@pytest.fixture
def sample_rag_result():
    """示例RAG结果"""
    return {
        "answer": "根据企业知识库，数字化转型的关键要素包括：",
        "sources": [
            {
                "content": "数字化转型白皮书摘要...",
                "metadata": {
                    "topic": "企业数字化",
                    "source": "内置知识库"
                }
            }
        ],
        "confidence": 0.85,
        "knowledge_count": 1,
        "used_context": True
    }


# 测试工具函数
def assert_response_structure(response: dict[str, Any]):
    """断言响应结构"""
    assert "success" in response
    assert "message" in response
    assert "timestamp" in response
    assert "status_code" in response


def assert_error_response(response: dict[str, Any], expected_status: int = 400):
    """断言错误响应"""
    assert_response_structure(response)
    assert response["success"] is False
    assert response["status_code"] == expected_status
    assert "error" in response


def assert_success_response(response: dict[str, Any], expected_status: int = 200):
    """断言成功响应"""
    assert_response_structure(response)
    assert response["success"] is True
    assert response["status_code"] == expected_status


async def wait_for_condition(condition_func, timeout: float = 5.0, interval: float = 0.1):
    """等待条件满足"""
    import time
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        if await condition_func() if asyncio.iscoroutinefunction(condition_func) else condition_func():
            return True
        await asyncio.sleep(interval)
    
    return False


def create_mock_openai_response(content: str = "测试回复"):
    """创建模拟OpenAI响应"""
    return {
        "choices": [
            {
                "message": {
                    "content": content,
                    "role": "assistant"
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150
        }
    }


