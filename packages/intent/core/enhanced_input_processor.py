"""
增强版输入预处理器 - 集成错别字纠正、分词、重复检测等功能
Enhanced Input Processor with typo correction, tokenization, duplicate detection

功能特性：
- 错别字/网络用语自动纠正
- 分词与词性标注（jieba）
- 重复输入检测
- 问句类型识别
- 语言比例检测
- 友好的错误提示
"""

import logging
import re
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

# 尝试导入jieba（可选依赖）
try:
    import jieba
    JIEBA_AVAILABLE = True
    logger.info("✓ jieba分词引擎可用")
except ImportError:
    JIEBA_AVAILABLE = False
    logger.warning("⚠ jieba未安装，分词功能将被禁用")


class EnhancedInputProcessor:
    """增强版输入预处理器"""
    
    # 常见网络用语/错别字映射表
    TYPO_MAP = {
        # 网络流行语
        "累觉不爱": "累觉不爱了",
        "蓝瘦香菇": "难受想哭",
        "我裂开了": "我心态崩了",
        "破防了": "被击穿了",
        "爷青回": "爷的青春回来了",
        "社死": "社会性死亡",
        "yyds": "永远的神",
        "绝绝子": "非常好",
        "栓Q": "谢谢你",
        
        # 常见口语化表达
        "在吗": "在吗",
        "你好呀": "你好",
        "怎么办呀": "怎么办",
        
        # 可根据实际使用情况继续添加
    }
    
    # 高风险词汇（安全预警）
    HIGH_RISK_KEYWORDS = [
        "自杀", "自残", "割腕", "跳楼", "服药", "了结",
        "不想活", "想死", "结束生命", "撑不下去", 
        "活不下去", "想自杀", "轻生", "自尽"
    ]
    
    # 敏感词汇（根据需要配置，这里预留接口）
    SENSITIVE_WORDS = [
        # 可以添加需要过滤的敏感词
            ]
    
    # 配置参数
    MAX_LENGTH = 500  # 单次输入最大长度（建议值）
    ABSOLUTE_MAX_LENGTH = 2000  # 绝对最大长度（硬限制）
    MIN_LENGTH = 1    # 最小有效长度
    
    def __init__(self, enable_jieba: bool = True, enable_duplicate_check: bool = True):
        """
        初始化增强版处理器
        
        Args:
            enable_jieba: 是否启用jieba分词（可能影响性能）
            enable_duplicate_check: 是否启用重复检测
        """
        self.enable_jieba = enable_jieba and JIEBA_AVAILABLE
        self.enable_duplicate_check = enable_duplicate_check
        
        # 初始化jieba（可选）
        if self.enable_jieba:
            try:
                # 预加载jieba词典（提升首次分词速度）
                jieba.initialize()
                # 添加自定义词汇
                jieba.add_word('API网关', freq=1000, tag='nz')
                jieba.add_word('向量检索', freq=1000, tag='n')
                jieba.add_word('数据脱敏', freq=1000, tag='n')
                jieba.add_word('多租户', freq=1000, tag='n')
                logger.info("✓ jieba分词引擎已初始化并加载自定义词典")
            except Exception as e:
                logger.warning(f"jieba初始化失败: {e}，将禁用分词功能")
                self.enable_jieba = False
        
        # 用于检测重复输入的历史记录（每个用户独立）
        self.user_history = {}  # {user_id: deque([msg1, msg2, ...], maxlen=10)}
        
        logger.info(f"✓ 增强版输入处理器已初始化 (jieba={self.enable_jieba}, duplicate_check={self.enable_duplicate_check})")
    
    def preprocess(self, text: str, user_id: str | None = None) -> dict[str, Any]:
        """
        完整的预处理流程
        
        Args:
            text: 原始输入文本
            user_id: 用户ID（用于重复检测）
            
        Returns:
            处理结果字典，包含：
            - original: 原始文本
            - cleaned: 清洗后的文本
            - blocked: 是否被阻止
            - risk_level: 风险等级 (low/medium/high)
            - warnings: 警告信息列表
            - friendly_message: 友好的提示信息（如果有问题）
            - metadata: 元数据（长度、分词、问句类型等）
        """
        result = {
            "original": text,
            "cleaned": "",
            "blocked": False,
            "risk_level": "low",
            "warnings": [],
            "friendly_message": None,
            "metadata": {}
        }
        
        # === 第1步：去除首尾空格与特殊符号 ===
        cleaned = text.strip().replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        cleaned = re.sub(r'\s+', ' ', cleaned)  # 多个空格合并为一个
        
        # === 第2步：检查空输入 ===
        if not cleaned:
            result["blocked"] = True
            result["warnings"].append("输入为空")
            result["friendly_message"] = "你好像还没说话呢~ 😊"
            return result
        
        # === 第3步：长度检查 ===
        length = len(cleaned)
        result["metadata"]["length"] = length
        
        if length > self.ABSOLUTE_MAX_LENGTH:
            # 超过绝对最大长度，强制截断
            result["warnings"].append(f"输入文本过长（已截断至{self.ABSOLUTE_MAX_LENGTH}字符）")
            result["friendly_message"] = f"消息太长啦！已自动截断到{self.ABSOLUTE_MAX_LENGTH}字，建议分次发送哦~ 📝"
            cleaned = cleaned[:self.ABSOLUTE_MAX_LENGTH]
        elif length > self.MAX_LENGTH:
            # 超过建议长度，但不截断，只提示
            result["warnings"].append(f"输入文本较长（{length}字符）")
            result["metadata"]["length_warning"] = True
        
        # === 第4步：纠正常见错别字/网络用语 ===
        original_cleaned = cleaned
        cleaned = self._correct_typos(cleaned)
        if cleaned != original_cleaned:
            result["metadata"]["typos_corrected"] = True
        
        # === 第5步：检查重复发送 ===
        if self.enable_duplicate_check and user_id:
            is_repeat, repeat_count = self._check_duplicate(cleaned, user_id)
            if is_repeat:
                result["warnings"].append(f"检测到重复内容（连续{repeat_count}次）")
                result["metadata"]["is_duplicate"] = True
                result["metadata"]["duplicate_count"] = repeat_count
                
                if repeat_count >= 3:
                    # 连续重复3次以上，可能需要特别关注
                    result["friendly_message"] = "我已经收到你的消息了，正在认真思考怎么回应~ 💭"
                    result["metadata"]["high_frequency_repeat"] = True
        
        # === 第6步：分词与词性标注（可选）===
        if self.enable_jieba:
            try:
                words = jieba.lcut(cleaned)
                result["metadata"]["words"] = words
                result["metadata"]["word_count"] = len(words)
                
                # 提取关键词（频率较高且有意义的词）
                # 这里简化处理，可以后续优化
                meaningful_words = [w for w in words if len(w) > 1 and not re.match(r'^[\W_]+$', w)]
                result["metadata"]["keywords"] = meaningful_words[:10]  # 最多10个
            except Exception as e:
                logger.warning(f"分词失败: {e}")
        
        # === 第7步：识别问句类型 ===
        is_question = self._is_question(cleaned)
        result["metadata"]["contains_question"] = is_question
        
        if is_question:
            question_type = self._detect_question_type(cleaned)
            result["metadata"]["question_type"] = question_type
        
        # === 第8步：语言检测（中文为主）===
        chinese_ratio = self._calculate_chinese_ratio(cleaned)
        result["metadata"]["chinese_ratio"] = round(chinese_ratio, 2)
        
        if chinese_ratio < 0.3 and length > 10:  # 中文占比过低且文本较长
            result["warnings"].append(f"非中文内容较多（中文占比{chinese_ratio:.1%}）")
            result["friendly_message"] = "我更擅长中文交流哦，如果方便的话可以用中文告诉我吗？ 🌸"
            result["metadata"]["low_chinese_ratio"] = True
        
        # === 第9步：高风险内容检测（最重要）===
        is_high_risk, risk_keywords = self._check_high_risk(cleaned)
        if is_high_risk:
            result["risk_level"] = "high"
            result["warnings"].append("检测到高风险内容")
            result["metadata"]["risk_keywords"] = risk_keywords
            result["metadata"]["requires_crisis_intervention"] = True
            logger.warning(f"⚠️ 高风险输入 [user={user_id}]: {cleaned[:50]}... | 关键词: {risk_keywords}")
        
        # === 第10步：敏感词过滤 ===
        filtered_text, filtered_words = self._filter_sensitive_words(cleaned)
        if filtered_words:
            result["warnings"].append(f"已过滤{len(filtered_words)}个敏感词")
            result["metadata"]["filtered_words"] = filtered_words
            cleaned = filtered_text
        
        # === 第11步：检查是否只包含特殊字符 ===
        if re.match(r'^[\W_]+$', cleaned):
            result["blocked"] = True
            result["warnings"].append("输入内容无效（仅包含特殊字符）")
            result["friendly_message"] = "似乎没有识别到有效的内容，换个方式表达吧~ 🌟"
            return result
        
        # === 第12步：最终清洗结果 ===
        result["cleaned"] = cleaned
        
        return result
    
    def _correct_typos(self, text: str) -> str:
        """
        纠正常见错别字和网络用语
        
        Args:
            text: 输入文本
            
        Returns:
            纠正后的文本
        """
        corrected = text
        corrections_made = []
        
        for typo, correct in self.TYPO_MAP.items():
            if typo in corrected:
                corrected = corrected.replace(typo, correct)
                corrections_made.append(f"'{typo}' → '{correct}'")
        
        if corrections_made:
            logger.debug(f"文本纠正: {', '.join(corrections_made)}")
        
        return corrected
    
    def _check_duplicate(self, text: str, user_id: str) -> tuple[bool, int]:
        """
        检查是否为重复内容
        
        Args:
            text: 当前输入
            user_id: 用户ID
            
        Returns:
            (是否重复, 连续重复次数)
        """
        # 初始化用户历史
        if user_id not in self.user_history:
            self.user_history[user_id] = deque(maxlen=10)
        
        history = self.user_history[user_id]
        
        # 检查最近的消息中是否有重复
        recent_messages = list(history)
        
        # 计算连续重复次数
        repeat_count = 0
        for msg in reversed(recent_messages):
            if msg == text:
                repeat_count += 1
            else:
                break
        
        is_duplicate = repeat_count > 0
        
        # 添加到历史
        history.append(text)
        
        return is_duplicate, repeat_count
    
    def _is_question(self, text: str) -> bool:
        """
        判断是否为问句
        
        Args:
            text: 文本
            
        Returns:
            是否为问句
        """
        question_markers = [
            '?', '？', '吗', '呢', '么', '嘛', '啊',
            '怎么', '为什么', '为啥', '咋', '如何', '怎样',
            '是不是', '对不对', '好不好', '可以吗', '行吗'
        ]
        
        for marker in question_markers:
            if marker in text:
                return True
        
        return False
    
    def _detect_question_type(self, text: str) -> str | None:
        """
        检测问句类型
        
        Args:
            text: 文本
            
        Returns:
            问句类型：
            - how: 怎样类（寻求方法）
            - why: 为何类（寻求原因）
            - what: 什么类（寻求信息）
            - confirm: 确认类（是否/对错）
            - other: 其他问句
        """
        if not self._is_question(text):
            return None
        
        # 怎样类问句（最常见，寻求建议）
        if any(word in text for word in ['怎么办', '怎么', '怎样', '如何', '咋办', '咋整', '该咋']):
            return "how"
        
        # 为什么类问句（寻求原因解释）
        if any(word in text for word in ['为什么', '为啥', '为何', '咋回事', '怎么回事']):
            return "why"
        
        # 什么类问句（寻求具体信息）
        if any(word in text for word in ['什么', '啥', '哪', '谁', '几']):
            return "what"
        
        # 确认类问句（寻求肯定或否定）
        if any(word in text for word in ['是不是', '对不对', '好不好', '吗', '呢', '可以吗', '行吗']):
            return "confirm"
        
        return "other"
    
    def _calculate_chinese_ratio(self, text: str) -> float:
        """
        计算中文字符占比
        
        Args:
            text: 文本
            
        Returns:
            中文字符比例（0-1）
        """
        if not text:
            return 0.0
        
        # 统计中文字符数量（包括标点符号）
        chinese_count = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        
        return chinese_count / len(text)
    
    def _check_high_risk(self, text: str) -> tuple[bool, list[str]]:
        """
        检查高风险关键词（安全预警相关）
        
        Args:
            text: 文本
            
        Returns:
            (是否高风险, 匹配的关键词列表)
        """
        text_lower = text.lower()
        matched_keywords = []
        
        for keyword in self.HIGH_RISK_KEYWORDS:
            if keyword in text_lower:
                matched_keywords.append(keyword)
        
        return len(matched_keywords) > 0, matched_keywords
    
    def _filter_sensitive_words(self, text: str) -> tuple[str, list[str]]:
        """
        过滤敏感词（使用星号替换）
        
        Args:
            text: 文本
            
        Returns:
            (过滤后的文本, 被过滤的词列表)
        """
        filtered = text
        filtered_words = []
        
        for word in self.SENSITIVE_WORDS:
            if word in filtered:
                filtered = filtered.replace(word, "*" * len(word))
                filtered_words.append(word)
        
        return filtered, filtered_words
    
    def validate_input(self, text: str) -> tuple[bool, str | None]:
        """
        快速验证输入是否合规（轻量级检查）
        
        Args:
            text: 输入文本
            
        Returns:
            (是否合规, 友好的错误提示)
        """
        if not text or not text.strip():
            return False, "你好像还没说话呢~ 😊"
        
        if len(text) > 5000:
            return False, "消息太长啦！建议分成几次发送~ 📝"
        
        # 检查是否只包含特殊字符
        cleaned = text.strip()
        if re.match(r'^[\W_]+$', cleaned):
            return False, "似乎没有识别到有效的内容，换个方式表达吧~ 🌟"
        
        return True, None
    
    def clear_user_history(self, user_id: str):
        """
        清除用户的输入历史
        
        Args:
            user_id: 用户ID
        """
        if user_id in self.user_history:
            del self.user_history[user_id]
            logger.info(f"已清除用户 {user_id} 的输入历史")
    
    def get_statistics(self) -> dict[str, Any]:
        """
        获取处理器统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "jieba_enabled": self.enable_jieba,
            "duplicate_check_enabled": self.enable_duplicate_check,
            "tracked_users": len(self.user_history),
            "max_length": self.MAX_LENGTH,
            "absolute_max_length": self.ABSOLUTE_MAX_LENGTH,
            "typo_rules": len(self.TYPO_MAP),
            "high_risk_keywords": len(self.HIGH_RISK_KEYWORDS),
            "sensitive_words": len(self.SENSITIVE_WORDS)
        }
    
    def add_typo_rule(self, typo: str, correct: str):
        """
        动态添加错别字纠正规则
        
        Args:
            typo: 错误写法
            correct: 正确写法
        """
        self.TYPO_MAP[typo] = correct
        logger.info(f"添加纠错规则: '{typo}' → '{correct}'")
    
    def add_high_risk_keyword(self, keyword: str):
        """
        动态添加高风险关键词
        
        Args:
            keyword: 关键词
        """
        if keyword not in self.HIGH_RISK_KEYWORDS:
            self.HIGH_RISK_KEYWORDS.append(keyword)
            logger.info(f"添加高风险关键词: '{keyword}'")


# 创建全局单例（可选）
_global_processor = None

def get_global_processor() -> EnhancedInputProcessor:
    """获取全局处理器实例（单例模式）"""
    global _global_processor
    if _global_processor is None:
        _global_processor = EnhancedInputProcessor()
    return _global_processor

