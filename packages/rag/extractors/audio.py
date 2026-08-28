"""音频转写 — faster-whisper / openai-whisper（optional）"""

from __future__ import annotations

from pathlib import Path


class MultimodalDependencyError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def extract_audio_text(path: str | Path) -> list[dict]:
    """
    转写音频为带时间戳的文本块。
    返回 [{text, start, end}, ...]
    """
    path = Path(path)
    from backend.core.errors import ErrorCode

    if not path.exists():
        raise MultimodalDependencyError(
            ErrorCode.FILE_NOT_FOUND.value, f"文件不存在: {path}"
        )

    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        try:
            import whisper  # type: ignore
        except ImportError as e:
            from backend.core.errors import ErrorCode

            raise MultimodalDependencyError(
                ErrorCode.RAG_DEP_MISSING.value,
                "多模态音频依赖未安装: uv sync --extra multimodal",
            ) from e
        model = whisper.load_model(whisper_model_name())
        result = model.transcribe(str(path))
        chunks = []
        for seg in result.get("segments") or []:
            chunks.append(
                {
                    "text": (seg.get("text") or "").strip(),
                    "start": float(seg.get("start") or 0),
                    "end": float(seg.get("end") or 0),
                }
            )
        if not chunks and result.get("text"):
            chunks = [{"text": result["text"].strip(), "start": 0.0, "end": 0.0}]
        return [c for c in chunks if c["text"]]

    model_size = whisper_model_name()
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path))
    chunks = []
    for seg in segments:
        text = (seg.text or "").strip()
        if text:
            chunks.append(
                {
                    "text": text,
                    "start": float(seg.start),
                    "end": float(seg.end),
                }
            )
    return chunks


def whisper_model_name() -> str:
    import os

    return os.getenv("WHISPER_MODEL", "base")
