"""
多模态情感交互模块
支持语音识别、语音合成、图像理解等功能。

注意：图像/ASR 依赖 (opencv/deepface/whisper) 已移出核心依赖，
按需懒加载；未安装时导入对应服务会失败。
"""

__all__ = [
    "MultimodalProcessor",
    "ASRService",
    "TTSService",
    "ImageService",
    "EmotionFusionService",
]


def __getattr__(name: str):
    if name == "MultimodalProcessor":
        from .core.multimodal_processor import MultimodalProcessor

        return MultimodalProcessor
    if name == "ASRService":
        from .services.asr_service import ASRService

        return ASRService
    if name == "TTSService":
        from .services.tts_service import TTSService

        return TTSService
    if name == "ImageService":
        from .services.image_service import ImageService

        return ImageService
    if name == "EmotionFusionService":
        from .services.emotion_fusion import EmotionFusionService

        return EmotionFusionService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
