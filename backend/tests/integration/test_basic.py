#!/usr/bin/env python3
"""
基础集成测试
"""


import pytest


class TestBasicIntegration:
    """基础集成测试"""
    
    def test_imports(self):
        """测试模块导入"""
        # 测试核心模块可以正常导入
        from packages.config import Config, get_config
        from packages.errors import NexusAIException

        assert Config is not None
        assert get_config is not None
        assert NexusAIException is not None

    @pytest.mark.asyncio
    async def test_config_loading(self):
        """测试配置加载"""
        from packages.config import get_config

        # 测试配置可以正常加载
        config = get_config()
        assert config is not None
        assert hasattr(config, 'environment')
        assert hasattr(config, 'database')

    def test_exception_handling(self):
        """测试异常处理"""
        from packages.errors import ErrorCode, NexusAIException

        exc = NexusAIException("TEST_001", "测试错误")
        assert exc.code == "TEST_001"
        assert exc.message == "测试错误"

        val_exc = NexusAIException(ErrorCode.REQ_INVALID, "验证失败", detail="test")
        assert val_exc.code == ErrorCode.REQ_INVALID
        assert val_exc.detail == "test"

        db_exc = NexusAIException(ErrorCode.INTERNAL_ERROR, "数据库错误")
        assert isinstance(db_exc, NexusAIException)

