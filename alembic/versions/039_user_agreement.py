"""Unify login terms into a single user_agreement kind."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "039_user_agreement"
down_revision = "038_content_artifact_visibility"
branch_labels = None
depends_on = None

_CONTENT = """# 用户协议

> 正式法律文本将由运营补充。以下为现行各专项条款合并稿，登录前须阅读并勾选同意。

---

# 平台通用条款 [律师审]

## 1. 接受
使用 NexusAI 即表示同意本协议（含隐私、公司 Key / BYOK 相关约定）。

## 2. 禁止行为
不得用于违法、侵权、攻击或绕过安全护栏的用途。

## 3. 免责声明
AI 输出仅供参考；正式法律文本 [律师审] 以签署版本为准。

---

# 隐私政策 [律师审]

## 1. 收集范围
账号、租户标识、调用元数据（token/成本/trace）；对话正文按审计策略留存。

## 2. 使用目的
认证、计费、安全护栏、可观测与合规审计。

## 3. 存储与删除
审计日志可清理；`usage_records` 计费流水不可删除。

## 4. 第三方
模型请求发送至客户配置的上游；具体数据处理以各厂商政策为准。

---

# 公司 Key 服务条款（转售/池化） [律师审]

## 1. 服务范围
平台提供 LLM 网关与按量计费能力；模型调用费用由租户预付费钱包抵扣。

## 2. 计费与配额
按 `usage_records` 计量扣费；配额与熔断规则以管理后台公示为准。

## 3. 客户责任
超用、滥用、违法内容导致的封号或损失由客户承担。

## 4. 充值与退款
充值通过对公转账人工入账；退款政策 [律师审] 以运营公告为准。

## 5. 价格变更
价格调整将提前通知；继续使用视为接受新版本条款。

---

# BYOK 服务条款 [律师审]

## 1. Key 归属
客户自行提供上游 API Key；Key 归客户所有，平台加密存储且仅用于代发请求。

## 2. 费用与风险
上游费用、限流、封号风险由客户承担；平台仅记录 BYOK 用量明细。

## 3. SLA
SLA 仅覆盖网关自身可用性，不含上游模型 SLA。

## 4. Key 泄露
若怀疑 Key 泄露，客户应立即轮换并在平台停用旧 Key；处置流程 [律师审]。
"""


def upgrade() -> None:
    terms = sa.table(
        "terms_versions",
        sa.column("version", sa.String),
        sa.column("kind", sa.String),
        sa.column("effective_at", sa.DateTime),
        sa.column("content_md", sa.Text),
        sa.column("created_at", sa.DateTime),
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(
        terms,
        [
            {
                "version": "v1.0.0",
                "kind": "user_agreement",
                "effective_at": now,
                "content_md": _CONTENT,
                "created_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM terms_versions WHERE kind = 'user_agreement' AND version = 'v1.0.0'")
    )
