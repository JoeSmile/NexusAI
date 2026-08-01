"""多模态提取器 — audio / image（optional deps）"""

from backend.modules.rag.extractors.audio import extract_audio_text
from backend.modules.rag.extractors.image import extract_image_text

__all__ = ["extract_audio_text", "extract_image_text"]
