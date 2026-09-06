"""教培营销合规红线 — fail-open 替换，不整段 BLOCK。

覆盖：绝对化用语、保过/包过、押题、升学承诺、价格/退费承诺。
不覆盖：医疗/疗效承诺（非本产品监管域，不进词典）。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("保证孩子提分", "帮孩子稳步提升"),
    ("承诺提分", "注重学习方法与习惯"),
    ("保证提分", "帮孩子稳步提升"),
    ("全市最专业", "专业负责"),
    ("最专业", "专业"),
    ("最好的", "优质的"),
    ("包过", "系统备考"),
    ("保过", "系统备考"),
    ("押题密卷", "精选练习"),
    ("押题", "重点复习"),
    ("国家级名师", "经验丰富的老师"),
    ("顶级名师", "经验丰富的老师"),
    ("国家级", "正规"),
    ("唯一指定", "可选"),
    ("全国唯一", "特色"),
    ("全网第一", "口碑较好"),
    ("行业第一", "口碑较好"),
    ("第一品牌", "口碑较好"),
    ("顶级", "优秀"),
    ("状元", "优秀学员"),
    ("名师", "老师"),
    ("升学率", "学习效果"),
    ("无效退款", "退费以公示规则为准"),
    ("原价", "定价"),
    ("立减", "优惠"),
    ("全额退款", "退费以公示规则为准"),
)

REDLINE_SOURCE_TERMS = tuple(src for src, _dst in _REPLACEMENTS)

_RESIDUAL = re.compile(r"(保过|包过|押题|承诺提分|保证提分|保证孩子提分)")


def apply_edu_marketing_redlines(text: str) -> tuple[str, list[str]]:
    """命中则替换或删句；返回 (新文本, 命中标签)。失败应被调用方吞掉。"""
    if not text:
        return text, []
    out = text
    hits: list[str] = []
    for src, dst in _REPLACEMENTS:
        if src in out:
            out = out.replace(src, dst)
            hits.append(src)
    if _RESIDUAL.search(out):
        pieces = re.split(r"(?<=[。！？!?\n])", out)
        kept: list[str] = []
        for piece in pieces:
            m = _RESIDUAL.search(piece)
            if m:
                hits.append(f"drop:{m.group(0)}")
                continue
            kept.append(piece)
        out = "".join(kept)
    if hits:
        logger.info("edu_marketing_redline hits=%s", hits)
    return out, hits
