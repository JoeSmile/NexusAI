"""输出护栏 — 长度截断 + 敏感内容 + 企业助手角色漂移"""

from __future__ import annotations

import re

from backend.core.guardrails.base import GuardResult

OUTPUT_BLOCK_PATTERNS = [
    r"API密钥",
    r"sk-[a-zA-Z0-9]{10,}",
    r"SECRET_KEY",
    r"PASSWORD",
]

# 角色漂移词库 — 检测模型从「企业助手」人设漂移为消费域/违规人设。
# 基准人设: 企业秘书 / HR / 前台助理 — 正式、客观、不推销、不情感化、不涉资金操作。
# 命中任一 = 整段拦截(人设崩塌比误杀代价更高,只保留高精度标记)。
# 历史: v1.0 曾含 "点击.*链接" 等低精度词,会误伤企业合法输出(如"点击链接查看制度"),已移除。
DRIFT_PATTERNS = [
    # ── 直播带货话术(助手 → 带货主播)──
    r"家人们",
    r"直播间",
    r"买了.*不亏",
    r"错过.*后悔",
    # ── 亲密/陪聊话术(助手 → 消费域人设,遗留拦截)──
    r"宝贝",
    r"么么哒",
    r"亲亲",
    r"抱抱",
    r"想你了",
    # ── 迷信/江湖术士(助手 → 算命先生)──
    r"算命",
    r"改运",
    r"开光",
    r"做法事",
    # ── 资金诱导/诈骗话术(助手 → 骗子,企业场景绝不允许)──
    r"安全账户",
    r"转账到.*(个人|私人|安全)账户",
    r"稳赚不赔",
    r"日入过万",
    r"拉人头",
]

VIOLATION_PATTERNS = [
    r"sk-[a-zA-Z0-9]{10,}",
    r"SECRET_KEY",
]


async def check_role_drift(response: str) -> GuardResult:
    """检测角色漂移: 企业助手人设 → 消费域/违规人设(带货、陪聊、迷信、资金诱导)。"""
    for pattern in DRIFT_PATTERNS:
        if re.search(pattern, response):
            return GuardResult(
                action="blocked",
                redacted_text="[OUTPUT BLOCKED: 角色漂移]",
                reason=f"role_drift:{pattern}",
            )
    return GuardResult(action="pass", redacted_text=response, reason="")


async def check_output(response: str) -> GuardResult:
    """检查 LLM 输出"""
    if len(response) > 4000:
        return GuardResult(
            action="truncated",
            redacted_text=response[:4000],
            reason="length_exceeded",
        )

    for pattern in OUTPUT_BLOCK_PATTERNS:
        if re.search(pattern, response, re.IGNORECASE):
            return GuardResult(
                action="blocked",
                redacted_text="[OUTPUT BLOCKED: 包含敏感内容]",
                reason=f"sensitive_content:{pattern}",
            )

    drift = await check_role_drift(response)
    if drift.action == "blocked":
        return drift

    return GuardResult(action="pass", redacted_text=response, reason="")
