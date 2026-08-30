"""
意图分类器 - 混合式意图识别（规则+模型）
Intent Classifier with hybrid approach (rule-based + ML)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..models.intent_models import IntentResult, IntentType, confidence_tier
from .label_map import V8_ID2LABEL, V8_LABEL_ORDER
from .rule_engine import RuleBasedIntentEngine

logger = logging.getLogger(__name__)

MAX_SEQ_LEN = 48


def _resolve_torch_device():
    """INTENT_DEVICE=cpu|cuda|auto（默认 cpu；无 GPU 构建不装 CUDA 轮子）。"""
    import os

    import torch

    pref = (os.getenv("INTENT_DEVICE") or "").strip().lower()
    if not pref:
        try:
            from config import get_settings

            pref = (get_settings().intent_device or "cpu").strip().lower()
        except Exception:
            pref = "cpu"

    if pref == "cpu":
        return torch.device("cpu")
    if pref == "cuda":
        if not torch.cuda.is_available():
            logger.warning("INTENT_DEVICE=cuda but CUDA unavailable; using cpu")
            return torch.device("cpu")
        return torch.device("cuda")
    # auto
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def resolve_intent_model_path(model_path: str | None = None) -> Path:
    """Resolve INTENT_MODEL_PATH (absolute or relative to project_root)."""
    try:
        from config import get_settings

        settings = get_settings()
        root = Path(settings.project_root)
        raw = model_path or settings.intent_model_path
    except Exception:
        root = Path(__file__).resolve().parents[4]
        raw = model_path or "data/models/intent_v8"

    path = Path(raw)
    if path.is_absolute():
        return path
    return root / path


def _attach_tier(result: IntentResult) -> IntentResult:
    if result.tier is None:
        return result.model_copy(update={"tier": confidence_tier(result.confidence)})
    return result


class MLIntentClassifier:
    """v8 BERT 意图分类器；加载失败时回退启发式规则。"""

    def __init__(self, model_path: str | None = None):
        self.model_path = resolve_intent_model_path(model_path)
        self.model = None
        self.tokenizer = None
        self._device = None
        self.id2label: dict[int, str] = dict(V8_ID2LABEL)
        self._load_model()

    def _load_model(self) -> None:
        config_file = self.model_path / "config.json"
        if not config_file.is_file():
            logger.warning(
                "Intent v8 model not found at %s; using rule/heuristic fallback",
                self.model_path,
            )
            return
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError:
            logger.warning(
                "transformers/torch not installed (uv sync --extra intent-model); "
                "using rule/heuristic fallback"
            )
            return

        try:
            with config_file.open(encoding="utf-8") as fh:
                cfg = json.load(fh)
            raw_id2label = cfg.get("id2label") or {}
            if raw_id2label:
                self.id2label = {int(k): str(v) for k, v in raw_id2label.items()}
            elif len(self.id2label) != 8:
                raise ValueError("config.json id2label missing and V8_ID2LABEL invalid")

            self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_path))
            self.model = AutoModelForSequenceClassification.from_pretrained(
                str(self.model_path)
            )
            self.model.eval()
            self._device = _resolve_torch_device()
            self.model.to(self._device)
            logger.info("Intent v8 BERT loaded from %s on %s", self.model_path, self._device)
        except Exception as exc:
            logger.warning("Intent v8 model load failed (%s); using fallback", exc)
            self.model = None
            self.tokenizer = None
            self._device = None

    @property
    def is_loaded(self) -> bool:
        return self.model is not None and self.tokenizer is not None

    def classify(self, text: str) -> IntentResult:
        if self.is_loaded:
            return _attach_tier(self._predict_with_model(text))
        return _attach_tier(self._heuristic_classify(text))

    def _predict_with_model(self, text: str) -> IntentResult:
        import torch

        assert self.model is not None and self.tokenizer is not None
        enc = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_SEQ_LEN,
        )
        enc = {k: v.to(self._device) for k, v in enc.items()}
        with torch.no_grad():
            logits = self.model(**enc).logits
        probs = torch.softmax(logits, dim=-1)[0]
        idx = int(probs.argmax())
        conf = float(probs[idx].item())
        label = self.id2label.get(idx)
        if label is None and 0 <= idx < len(V8_LABEL_ORDER):
            label = V8_LABEL_ORDER[idx]
        try:
            intent = IntentType(label or IntentType.CONVERSATION.value)
        except ValueError:
            intent = IntentType.CONVERSATION
        return IntentResult(
            intent=intent,
            confidence=conf,
            source="model",
            metadata={"method": "bert_v8", "model_path": str(self.model_path)},
        )

    def _heuristic_classify(self, text: str) -> IntentResult:
        """Model unavailable — delegate to rule engine, else conversation."""
        rule = RuleBasedIntentEngine().detect_intent(text)
        if rule is not None:
            return rule.model_copy(update={"source": "rule"})
        return IntentResult(
            intent=IntentType.CONVERSATION,
            confidence=0.60,
            source="rule",
            metadata={"method": "fallback_default"},
        )


class IntentClassifier:
    """混合式意图分类器 — 规则优先，模型补充。"""

    def __init__(self, model_path: str | None = None):
        self.rule_engine = RuleBasedIntentEngine()
        self.ml_classifier = MLIntentClassifier(model_path)
        logger.info(
            "意图分类器初始化完成（混合模式：规则+模型%s）",
            "" if self.ml_classifier.is_loaded else "，BERT 未加载→规则回退",
        )

    def detect_intent(self, text: str) -> IntentResult:
        if not text or not text.strip():
            return _attach_tier(
                IntentResult(
                    intent=IntentType.CONVERSATION,
                    confidence=0.5,
                    source="default",
                    metadata={"reason": "empty_input"},
                )
            )

        rule_result = self.rule_engine.detect_intent(text)
        if rule_result and rule_result.confidence > 0.85:
            return _attach_tier(rule_result)

        ml_result = self.ml_classifier.classify(text)

        if rule_result:
            if rule_result.intent == ml_result.intent:
                boosted = min(ml_result.confidence + 0.1, 1.0)
                metadata = dict(ml_result.metadata or {})
                metadata["rule_confirmed"] = True
                ml_result = ml_result.model_copy(
                    update={"confidence": boosted, "metadata": metadata}
                )
            else:
                ml_result = ml_result.model_copy(
                    update={
                        "secondary_intents": {
                            rule_result.intent: rule_result.confidence
                        }
                    }
                )

        return _attach_tier(ml_result)

    def batch_detect(self, texts: list[str]) -> list[IntentResult]:
        return [self.detect_intent(text) for text in texts]
