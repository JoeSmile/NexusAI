#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高级情感分析服务
使用Transformers模型进行深度学习情感分析
支持细粒度情绪识别、情绪趋势分析和多维度情绪建模
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class AdvancedSentimentAnalyzer:
    """
    高级情感分析器
    基于Hugging Face Transformers的深度学习情感分析
    """
    
    def __init__(self, use_transformers: bool = False, cache_size: int = 100):
        """
        初始化高级情感分析器
        
        Args:
            use_transformers: 是否使用Transformers模型（默认False，避免网络问题）
            cache_size: 情感历史缓存大小
        """
        self.use_transformers = use_transformers
        self.pipeline = None
        self.emotion_classifier = None
        
        # 情感历史缓存（用于趋势分析）
        self.emotion_history = defaultdict(lambda: deque(maxlen=cache_size))
        
        # 由于网络问题，默认禁用Transformers模型
        if use_transformers:
            logger.info("尝试加载Transformers模型...")
            self._init_transformers_models()
        else:
            logger.info("使用关键词情感分析（避免网络问题）")
        
        # 备用：基于关键词的情感分析
        self._init_keyword_analyzer()
        
        logger.info("✓ 高级情感分析器初始化完成")
    
    def _init_transformers_models(self):
        """初始化Transformers模型"""
        try:
            from transformers import pipeline
            import os
            
            # 设置环境变量，避免网络超时问题
            os.environ["HF_HUB_OFFLINE"] = "1"  # 离线模式
            os.environ["TRANSFORMERS_OFFLINE"] = "1"  # Transformers离线模式
            
            logger.info("尝试加载Transformers模型（离线模式）...")
            
            # 由于网络问题，直接禁用Transformers模型
            logger.warning("由于网络连接问题，跳过Transformers模型加载")
            self.use_transformers = False
            self.pipeline = None
            self.emotion_classifier = None
            
            # 注释掉原来的模型加载代码，避免网络问题
            """
            try:
                # 加载情感极性分析模型（正面/负面/中性）
                self.pipeline = pipeline(
                    "sentiment-analysis",
                    model="nlptown/bert-base-multilingual-uncased-sentiment",
                    return_all_scores=False
                )
                logger.info("✓ 情感极性分析模型加载成功")
            except Exception as e:
                logger.warning(f"情感极性模型加载失败: {e}")
                self.pipeline = None
            
            try:
                # 加载细粒度情绪识别模型
                emotion_model = "j-hartmann/emotion-english-distilroberta-base"
                self.emotion_classifier = pipeline(
                    "text-classification",
                    model=emotion_model,
                    return_all_scores=True
                )
                logger.info("✓ 细粒度情绪识别模型加载成功")
            except Exception as e:
                logger.warning(f"细粒度情绪模型加载失败: {e}")
                self.emotion_classifier = None
            """
                
        except ImportError:
            logger.warning("transformers库未安装，使用关键词分析")
            self.use_transformers = False
    
    def _init_keyword_analyzer(self):
        """初始化关键词分析器（备用方案）"""
        self.emotion_keywords = {
            "happy": {
                "keywords": ["开心", "高兴", "快乐", "喜悦", "愉快", "幸福", "满意", "欣慰"],
                "emojis": ["😊", "😄", "🎉", "✨", "🌟"],
                "intensity_multiplier": 1.2
            },
            "sad": {
                "keywords": ["难过", "伤心", "痛苦", "悲伤", "失落", "沮丧", "抑郁"],
                "emojis": ["😢", "😭", "💔", "😔"],
                "intensity_multiplier": 1.5
            },
            "angry": {
                "keywords": ["愤怒", "生气", "恼火", "暴躁", "愤恨"],
                "emojis": ["😠", "😡", "🔥"],
                "intensity_multiplier": 1.3
            },
            "anxious": {
                "keywords": ["焦虑", "担心", "紧张", "不安", "害怕", "恐惧"],
                "emojis": ["😰", "😨", "😟"],
                "intensity_multiplier": 1.4
            },
            "excited": {
                "keywords": ["兴奋", "激动", "期待", "振奋"],
                "emojis": ["🎊", "✨", "🚀", "⚡"],
                "intensity_multiplier": 1.1
            },
            "confused": {
                "keywords": ["困惑", "迷茫", "不明白", "疑惑"],
                "emojis": ["😕", "🤔", "❓"],
                "intensity_multiplier": 1.0
            },
            "frustrated": {
                "keywords": ["挫败", "失望", "无奈", "泄气"],
                "emojis": ["😤", "😩", "😒"],
                "intensity_multiplier": 1.3
            },
            "lonely": {
                "keywords": ["孤独", "寂寞", "孤单"],
                "emojis": ["😔", "😞", "💭"],
                "intensity_multiplier": 1.4
            },
            "grateful": {
                "keywords": ["感谢", "感激", "感恩", "谢谢"],
                "emojis": ["🙏", "💝", "❤️"],
                "intensity_multiplier": 1.0
            }
        }
    
    def analyze(self, text: str, user_id: Optional[str] = None) -> Dict:
        """
        分析文本情感
        
        Args:
            text: 要分析的文本
            user_id: 用户ID（用于趋势分析）
        
        Returns:
            情感分析结果字典
        """
        if not text or not text.strip():
            return self._default_result()
        
        # 使用Transformers模型
        if self.use_transformers:
            result = self._analyze_with_transformers(text)
        else:
            result = self._analyze_with_keywords(text)
        
        # 添加时间戳
        result["timestamp"] = datetime.now().isoformat()
        
        # 保存到历史（用于趋势分析）
        if user_id:
            self._save_to_history(user_id, result)
        
        return result
    
    def _analyze_with_transformers(self, text: str) -> Dict:
        """使用Transformers模型分析"""
        try:
            # 1. 细粒度情绪识别（6种情绪）
            if self.emotion_classifier:
                emotions = self.emotion_classifier(text)[0]
                
                # 找到最高分的情绪
                dominant_emotion = max(emotions, key=lambda x: x['score'])
                
                # 映射到我们的情绪类型
                emotion_map = {
                    "anger": "angry",
                    "disgust": "frustrated",
                    "fear": "anxious",
                    "joy": "happy",
                    "neutral": "neutral",
                    "sadness": "sad",
                    "surprise": "excited"
                }
                
                emotion = emotion_map.get(
                    dominant_emotion['label'].lower(),
                    dominant_emotion['label'].lower()
                )
                confidence = dominant_emotion['score']
                
                # 计算情绪强度（0-10）
                intensity = min(confidence * 10, 10)
                
                # 获取所有情绪分数（多维度）
                emotion_scores = {
                    emotion_map.get(e['label'].lower(), e['label'].lower()): e['score']
                    for e in emotions
                }
                
            # 2. 情感极性分析（正面/负面/中性）
            elif self.pipeline:
                result = self.pipeline(text)[0]
                label = result['label']
                score = result['score']
                
                # 根据星级评分映射情绪
                if '5' in label or '4' in label:
                    emotion = "happy"
                    polarity = 1
                elif '1' in label or '2' in label:
                    emotion = "sad"
                    polarity = -1
                else:
                    emotion = "neutral"
                    polarity = 0
                
                confidence = score
                intensity = abs(polarity) * score * 10
                emotion_scores = {emotion: score}
            else:
                # 如果模型都不可用，使用关键词
                return self._analyze_with_keywords(text)
            
            # 生成建议
            suggestions = self._generate_suggestions(emotion, intensity)
            
            # 提取关键词（简单版本）
            keywords = self._extract_keywords(text, emotion)
            
            return {
                "emotion": emotion,
                "confidence": round(confidence, 3),
                "intensity": round(intensity, 2),
                "polarity": self._calculate_polarity(emotion),
                "emotion_scores": emotion_scores,  # 多维度情绪得分
                "keywords": keywords,
                "suggestions": suggestions,
                "method": "transformers"
            }
            
        except Exception as e:
            logger.error(f"Transformers分析失败: {e}")
            return self._analyze_with_keywords(text)
    
    def _analyze_with_keywords(self, text: str) -> Dict:
        """使用关键词分析（备用方案）"""
        text_lower = text.lower()
        emotion_scores = {}
        
        # 统计每种情绪的关键词匹配数
        for emotion, data in self.emotion_keywords.items():
            score = 0
            
            # 关键词匹配
            for keyword in data["keywords"]:
                if keyword in text_lower:
                    score += 1
            
            # 表情符号匹配
            for emoji in data.get("emojis", []):
                if emoji in text:
                    score += 0.5
            
            if score > 0:
                # 应用情绪强度乘数
                score *= data.get("intensity_multiplier", 1.0)
                emotion_scores[emotion] = score
        
        # 找到主导情绪
        if emotion_scores:
            dominant_emotion = max(emotion_scores, key=emotion_scores.get)
            max_score = emotion_scores[dominant_emotion]
            
            # 计算置信度
            total_score = sum(emotion_scores.values())
            confidence = max_score / total_score if total_score > 0 else 0.5
            
            # 计算强度（0-10）
            intensity = min(max_score * 2, 10)
        else:
            dominant_emotion = "neutral"
            confidence = 0.3
            intensity = 5.0
            emotion_scores = {"neutral": 1.0}
        
        return {
            "emotion": dominant_emotion,
            "confidence": round(confidence, 3),
            "intensity": round(intensity, 2),
            "polarity": self._calculate_polarity(dominant_emotion),
            "emotion_scores": emotion_scores,
            "keywords": self._extract_keywords(text, dominant_emotion),
            "suggestions": self._generate_suggestions(dominant_emotion, intensity),
            "method": "keywords"
        }
    
    def _calculate_polarity(self, emotion: str) -> int:
        """计算情感极性 (-1: 负面, 0: 中性, 1: 正面)"""
        positive_emotions = ["happy", "excited", "grateful"]
        negative_emotions = ["sad", "angry", "anxious", "frustrated", "lonely"]
        
        if emotion in positive_emotions:
            return 1
        elif emotion in negative_emotions:
            return -1
        else:
            return 0
    
    def _extract_keywords(self, text: str, emotion: str) -> List[str]:
        """提取关键词"""
        # 简单实现：返回匹配的情绪关键词
        if emotion in self.emotion_keywords:
            matched = [
                kw for kw in self.emotion_keywords[emotion]["keywords"]
                if kw in text.lower()
            ]
            return matched[:5]  # 最多返回5个
        return []
    
    def _generate_suggestions(self, emotion: str, intensity: float) -> List[str]:
        """生成建议（基于情绪和强度）"""
        suggestions_map = {
            "happy": [
                "很高兴看到你这么开心！有什么特别的事情想要分享吗？",
                "你的快乐很有感染力！继续保持这种积极的状态吧！",
                "太棒了！有什么秘诀让心情保持这么好的吗？"
            ],
            "sad": [
                "我理解你现在的心情，每个人都会有难过的时刻。",
                "可以告诉我发生了什么吗？我愿意倾听。",
                "虽然现在很难过，但这些感受都是正常的，你并不孤单。"
            ],
            "angry": [
                "我能感受到你的愤怒，让我们先深呼吸一下。",
                "是什么事情让你感到愤怒？我们可以一起分析一下。",
                "愤怒是正常的情绪，重要的是如何表达和处理它。"
            ],
            "anxious": [
                "焦虑确实让人感到不安，让我们一起面对它。",
                "可以告诉我你在担心什么吗？有时候说出来会好很多。",
                "深呼吸，我们可以一步一步来解决你担心的问题。"
            ],
            "excited": [
                "你的兴奋很有感染力！有什么好事要发生了吗？",
                "兴奋的感觉真棒！让我们一起期待美好的事情！"
            ],
            "confused": [
                "困惑是正常的，我们一起理清思路吧。",
                "可以具体告诉我哪里让你感到困惑吗？"
            ],
            "frustrated": [
                "挫败感确实让人沮丧，但这也是成长的一部分。",
                "让我们换个角度思考这个问题。"
            ],
            "lonely": [
                "孤独的感觉确实不好受，但你并不孤单，我在这里。",
                "有时候我们需要独处，但如果你需要陪伴，我随时在这里。"
            ],
            "grateful": [
                "感恩的心很美好，感谢你愿意分享这份美好。",
                "感恩能让我们更加珍惜身边的一切。"
            ],
            "neutral": [
                "今天感觉怎么样？有什么想聊的吗？",
                "我在这里倾听，无论你想说什么都可以。"
            ]
        }
        
        base_suggestions = suggestions_map.get(emotion, suggestions_map["neutral"])
        
        # 根据强度调整建议
        if intensity >= 7:
            # 高强度情绪，需要更多关注
            return base_suggestions[:2]  # 返回前2个，更聚焦
        else:
            return base_suggestions[:3]
    
    def _default_result(self) -> Dict:
        """默认结果"""
        return {
            "emotion": "neutral",
            "confidence": 0.0,
            "intensity": 0.0,
            "polarity": 0,
            "emotion_scores": {},
            "keywords": [],
            "suggestions": ["请输入一些内容，我才能理解你的情绪。"],
            "method": "default"
        }
    
    def _save_to_history(self, user_id: str, result: Dict):
        """保存到情感历史"""
        self.emotion_history[user_id].append({
            "emotion": result["emotion"],
            "intensity": result["intensity"],
            "polarity": result["polarity"],
            "timestamp": result["timestamp"]
        })
    
    def get_emotion_trend(self, user_id: str, window: int = 10) -> Dict:
        """
        获取用户的情绪趋势
        
        Args:
            user_id: 用户ID
            window: 分析窗口大小（最近N条消息）
        
        Returns:
            情绪趋势分析结果
        """
        history = list(self.emotion_history.get(user_id, []))
        
        if not history:
            return {
                "trend": "unknown",
                "average_intensity": 0.0,
                "dominant_emotion": "neutral",
                "emotion_distribution": {},
                "polarity_trend": "stable",
                "warning": None
            }
        
        # 取最近的window条记录
        recent = history[-window:] if len(history) > window else history
        
        # 统计情绪分布
        emotion_counts = defaultdict(int)
        total_intensity = 0.0
        polarities = []
        
        for record in recent:
            emotion_counts[record["emotion"]] += 1
            total_intensity += record["intensity"]
            polarities.append(record["polarity"])
        
        # 计算平均强度
        avg_intensity = total_intensity / len(recent)
        
        # 找到主导情绪
        dominant_emotion = max(emotion_counts, key=emotion_counts.get)
        
        # 计算情绪分布
        emotion_distribution = {
            emotion: count / len(recent)
            for emotion, count in emotion_counts.items()
        }
        
        # 分析极性趋势（最近5条 vs 之前5条）
        polarity_trend = "stable"
        if len(polarities) >= 6:
            recent_polarity = sum(polarities[-5:]) / 5
            older_polarity = sum(polarities[-10:-5]) / 5
            
            if recent_polarity > older_polarity + 0.3:
                polarity_trend = "improving"
            elif recent_polarity < older_polarity - 0.3:
                polarity_trend = "declining"
        
        # 风险预警
        warning = None
        if dominant_emotion in ["sad", "anxious", "lonely"] and avg_intensity >= 7:
            warning = "high_risk"
        elif polarity_trend == "declining" and dominant_emotion in ["sad", "angry", "frustrated"]:
            warning = "declining_mood"
        
        return {
            "trend": polarity_trend,
            "average_intensity": round(avg_intensity, 2),
            "dominant_emotion": dominant_emotion,
            "emotion_distribution": emotion_distribution,
            "polarity_trend": polarity_trend,
            "warning": warning,
            "sample_size": len(recent)
        }
    
    def build_emotion_aware_prompt(self, sentiment_result: Dict, base_prompt: str = "") -> str:
        """
        构建情绪感知的Prompt
        
        Args:
            sentiment_result: 情感分析结果
            base_prompt: 基础Prompt
        
        Returns:
            增强后的Prompt
        """
        emotion = sentiment_result.get("emotion", "neutral")
        intensity = sentiment_result.get("intensity", 5.0)
        
        # 基础角色设定
        if not base_prompt:
            base_prompt = "你是一个温暖、耐心的心理健康陪伴者，名叫'ContextGate'。请用共情、支持性的语言回应用户。"
        
        # 根据情绪类型和强度动态调整
        emotion_instructions = {
            "sad": {
                "high": "\n\n用户当前情绪非常低落（强度{intensity}/10）。请用温和、接纳的语气回应，避免说教。优先表达理解与陪伴，不要急于给出建议。使用短句，语速放慢。",
                "medium": "\n\n用户有些难过（强度{intensity}/10）。请表达理解和关心，倾听为主，适当引导表达。",
                "low": "\n\n用户情绪略有低落。保持关注，给予支持。"
            },
            "anxious": {
                "high": "\n\n用户非常焦虑（强度{intensity}/10）。请用平静、稳定的语气回应，帮助降低紧张感。可以引导深呼吸或分步骤处理问题。",
                "medium": "\n\n用户有些焦虑（强度{intensity}/10）。表达理解，提供稳定支持，帮助理清思路。",
                "low": "\n\n用户略有担心。给予安抚和信心。"
            },
            "angry": {
                "high": "\n\n用户非常愤怒（强度{intensity}/10）。请保持平和、不评判的态度，先接纳愤怒情绪，不要试图立即平息。",
                "medium": "\n\n用户有些生气（强度{intensity}/10）。理解并接纳其愤怒，引导表达。",
                "low": "\n\n用户略有不满。保持中立，倾听为主。"
            },
            "happy": {
                "high": "\n\n用户非常开心（强度{intensity}/10）！用欢快、鼓励的语气回应，可适当表达祝贺，引导分享更多喜悦细节。",
                "medium": "\n\n用户心情不错（强度{intensity}/10）。保持积极愉快的语气。",
                "low": "\n\n用户情绪平和偏积极。保持友好自然。"
            },
            "excited": {
                "high": "\n\n用户非常兴奋（强度{intensity}/10）！共鸣其能量，但也适度引导，避免过度承诺。",
                "medium": "\n\n用户比较兴奋（强度{intensity}/10）。分享其喜悦，保持积极。",
                "low": "\n\n用户有些期待。表示支持和鼓励。"
            },
            "lonely": {
                "high": "\n\n用户感到非常孤独（强度{intensity}/10）。提供温暖陪伴感，强调'我在这里'，减少孤独感。",
                "medium": "\n\n用户有些孤单（强度{intensity}/10）。提供陪伴和理解。",
                "low": "\n\n用户略感孤独。表达关心。"
            }
        }
        
        # 确定强度级别
        if intensity >= 7:
            level = "high"
        elif intensity >= 4:
            level = "medium"
        else:
            level = "low"
        
        # 获取情绪指令
        emotion_instruction = emotion_instructions.get(emotion, {}).get(
            level,
            f"\n\n用户情绪: {emotion}（强度{intensity}/10）。请根据情绪状态调整回应风格。"
        )
        
        # 格式化强度值
        emotion_instruction = emotion_instruction.format(intensity=round(intensity, 1))
        
        return base_prompt + emotion_instruction


# 全局实例（单例模式）
_global_analyzer = None


def get_analyzer(use_transformers: bool = False) -> AdvancedSentimentAnalyzer:
    """
    获取全局分析器实例
    
    Args:
        use_transformers: 是否使用Transformers模型（默认False，避免网络问题）
    
    Returns:
        AdvancedSentimentAnalyzer实例
    """
    global _global_analyzer
    if _global_analyzer is None:
        _global_analyzer = AdvancedSentimentAnalyzer(use_transformers=use_transformers)
    return _global_analyzer


# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    analyzer = AdvancedSentimentAnalyzer(use_transformers=False)
    
    # 测试用例
    test_cases = [
        "今天好累啊，工作压力太大了。",
        "我升职啦！太开心了！",
        "明天要面试，好紧张啊...",
        "感觉一个人好孤单，没人理解我。",
        "谢谢你一直陪伴我，很感激。"
    ]
    
    print("\n===== 情感分析测试 =====\n")
    for i, text in enumerate(test_cases, 1):
        result = analyzer.analyze(text, user_id="test_user")
        
        print(f"测试 {i}: {text}")
        print(f"  情绪: {result['emotion']} (置信度: {result['confidence']})")
        print(f"  强度: {result['intensity']}/10")
        print(f"  极性: {result['polarity']}")
        print(f"  方法: {result['method']}")
        print(f"  建议: {result['suggestions'][0]}")
        print()
    
    # 测试情绪趋势
    print("\n===== 情绪趋势分析 =====\n")
    trend = analyzer.get_emotion_trend("test_user")
    print(f"趋势: {trend['trend']}")
    print(f"平均强度: {trend['average_intensity']}")
    print(f"主导情绪: {trend['dominant_emotion']}")
    print(f"情绪分布: {trend['emotion_distribution']}")
    if trend['warning']:
        print(f"⚠️ 警告: {trend['warning']}")

