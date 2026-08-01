"""图片 OCR — PaddleOCR（optional，中文优先）"""

from __future__ import annotations

from pathlib import Path

from backend.modules.rag.extractors.audio import MultimodalDependencyError


def extract_image_text(path: str | Path) -> str:
    """OCR 提取图片中的文本。"""
    path = Path(path)
    from backend.core.errors import ErrorCode

    if not path.exists():
        raise MultimodalDependencyError(
            ErrorCode.FILE_NOT_FOUND.value, f"文件不存在: {path}"
        )

    try:
        from paddleocr import PaddleOCR  # type: ignore
    except ImportError as e:
        raise MultimodalDependencyError(
            ErrorCode.RAG_DEP_MISSING.value,
            "多模态图片依赖未安装: uv sync --extra multimodal",
        ) from e

    ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    result = ocr.ocr(str(path), cls=True)
    lines: list[str] = []
    for block in result or []:
        for line in block or []:
            if line and len(line) >= 2:
                txt = line[1][0] if isinstance(line[1], (list, tuple)) else str(line[1])
                if txt:
                    lines.append(str(txt))
    return "\n".join(lines).strip()
