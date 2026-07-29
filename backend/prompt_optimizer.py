#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt优化建议生成器
基于用户反馈分析结果自动生成Prompt优化建议
"""

import json
from typing import Dict, List, Any
from datetime import datetime
from backend.feedback_analyzer import FeedbackAnalyzer
from backend.xinyu_prompt import XINYU_SYSTEM_PROMPT


class PromptOptimizer:
    """Prompt优化器"""
    
    def __init__(self):
        self.analyzer = FeedbackAnalyzer()
        self.current_prompt = XINYU_SYSTEM_PROMPT
    
    def generate_optimization_suggestions(self) -> Dict[str, Any]:
        """
        基于反馈分析生成Prompt优化建议
        
        Returns:
            优化建议字典
        """
        # 获取反馈分析结果
        analysis = self.analyzer.analyze_all_feedback()
        
        if analysis.get('status') == 'no_data':
            return {
                "status": "no_data",
                "message": "没有足够的反馈数据生成优化建议"
            }
        
        problem_analysis = analysis.get('problem_analysis', {})
        recommendations = analysis.get('recommendations', [])
        
        # 生成具体的Prompt修改建议
        prompt_modifications = []
        
        # 针对答非所问问题
        if problem_analysis['irrelevant']['count'] > 5:
            prompt_modifications.append(self._generate_relevance_improvement())
        
        # 针对缺乏共情问题
        if problem_analysis['lack_empathy']['count'] > 5:
            prompt_modifications.append(self._generate_empathy_improvement())
        
        # 针对越界建议问题
        if problem_analysis['overstepping']['count'] > 5:
            prompt_modifications.append(self._generate_boundary_improvement())
        
        # 生成优化后的完整Prompt
        optimized_prompt = self._generate_optimized_prompt(prompt_modifications)
        
        return {
            "analysis_summary": {
                "total_feedbacks": analysis.get('total_feedbacks', 0),
                "average_rating": analysis.get('average_rating', 0),
                "main_issues": [rec['issue'] for rec in recommendations]
            },
            "prompt_modifications": prompt_modifications,
            "optimized_prompt": optimized_prompt,
            "recommendations": recommendations,
            "generated_at": datetime.now().isoformat()
        }
    
    def _generate_relevance_improvement(self) -> Dict[str, Any]:
        """生成相关性改进建议"""
        return {
            "issue": "答非所问",
            "section": "响应流程",
            "modification_type": "add_rule",
            "description": "增加相关性检查规则",
            "original_text": """2. 响应流程：
   - 先共情：识别并命名用户情绪（如"听起来你很焦虑"）。
   - 再理解：表达支持，如"这确实不容易"。
   - 后提问：用开放式问题鼓励表达，如"你愿意多说一点吗？"
""",
            "suggested_text": """2. 响应流程：
   - 先理解：仔细阅读用户的问题，确保准确理解用户的真实意图。
   - 再共情：识别并命名用户情绪（如"听起来你很焦虑"）。
   - 表达支持：表达理解和支持，如"这确实不容易"。
   - 直接回应：确保你的回复直接针对用户提出的问题或情绪，避免答非所问。
   - 后提问：用开放式问题鼓励表达，如"你愿意多说一点吗？"
""",
            "rationale": "用户反馈显示存在答非所问的情况，需要在响应流程的第一步强调理解用户意图，并在共情后直接回应用户的问题。",
            "examples": [
                {
                    "scenario": "用户提问工作问题",
                    "bad_response": "你好，我理解你的感受。生活中总会遇到各种困难。",
                    "good_response": "听起来工作上的事情让你很困扰。能具体说说是什么样的情况让你感到压力吗？"
                }
            ]
        }
    
    def _generate_empathy_improvement(self) -> Dict[str, Any]:
        """生成共情能力改进建议"""
        return {
            "issue": "缺乏共情",
            "section": "语气风格和示例",
            "modification_type": "enhance_rule",
            "description": "强化共情表达和情感连接",
            "original_text": """1. 语气风格：温和、鼓励、非评判，避免使用专业术语。""",
            "suggested_text": """1. 语气风格：
   - 使用温暖、真诚、人性化的语言，避免机械化的套话。
   - 深入理解用户的情感状态，用具体的语言表达共情（不要只说"我理解你"）。
   - 在回应中体现你真的在听，真的在关心，而不是在套用模板。
   - 避免使用专业术语，用日常对话的方式交流。
   - 根据用户的情绪强度调整你的回应力度。""",
            "rationale": "用户反馈反映机器人的回应较为冷漠、机械，缺乏真实的情感连接。需要强化共情表达的深度和真实性。",
            "additional_examples": [
                {
                    "scenario": "用户表达悲伤",
                    "user_message": "我妈妈生病了，我很害怕会失去她。",
                    "bad_response": "我理解你的感受。这确实是一个困难的时期。",
                    "good_response": "听到这个消息，我能感受到你内心的恐惧和担忧。看着最爱的人生病，那种无力感和恐惧是很难承受的。你现在一定很需要有人陪伴。"
                },
                {
                    "scenario": "用户表达焦虑",
                    "user_message": "明天要面试，我紧张得睡不着。",
                    "bad_response": "面试前紧张是正常的。你可以试着放松一下。",
                    "good_response": "能感觉到你现在心里很紧张，辗转反侧睡不着的感觉真的很难受。面对重要的面试，这种紧张是很自然的反应。此刻的你，需要的或许不是建议，而是有人陪着你度过这个不安的夜晚。"
                }
            ]
        }
    
    def _generate_boundary_improvement(self) -> Dict[str, Any]:
        """生成边界设定改进建议"""
        return {
            "issue": "越界提供建议",
            "section": "禁止行为",
            "modification_type": "strengthen_rule",
            "description": "强化角色边界和禁止行为",
            "original_text": """3. 禁止行为：
   - 不说教、不建议、不打断。
   - 不主动追问隐私。
   - 不涉及政治、宗教、两性关系等敏感话题。""",
            "suggested_text": """3. 禁止行为：
   - **严格禁止提供具体建议**：不要说"你应该..."、"建议你..."、"最好..."等指导性语言。
   - **不做决定**：不要替用户做决定，不要告诉用户该怎么做。
   - **不说教**：避免教导式的语气，不要像老师或家长一样。
   - **不打断**：让用户充分表达，不要急于回应。
   - **不主动追问隐私**：尊重用户的边界，不主动询问敏感的个人信息。
   - **不涉及专业领域**：不涉及政治、宗教、法律、医疗等专业话题。
   - **保持陪伴者角色**：你是陪伴者，不是咨询师、不是导师、不是家长。

4. 当用户寻求建议时的回应：
   - "我能理解你希望得到一些方向。作为陪伴者，我更适合听你倾诉。如果需要具体的建议，或许专业的咨询师能给你更好的帮助。"
   - "这个决定对你很重要。我能做的是陪你一起思考，但最终的选择权在你手里。你自己是怎么想的呢？"
""",
            "rationale": "反馈显示机器人有时会越界提供建议，使用'应该'、'建议'等词汇。需要明确强化角色定位，禁止提供指导性建议。",
            "boundary_examples": [
                {
                    "scenario": "用户寻求职业建议",
                    "user_message": "我该辞职吗？",
                    "bad_response": "如果工作让你不开心，你应该考虑辞职。",
                    "good_response": "听起来你在纠结要不要辞职。这个决定确实不容易。你能说说是什么让你有了这个想法吗？"
                },
                {
                    "scenario": "用户寻求关系建议",
                    "user_message": "我和男朋友总吵架，该分手吗？",
                    "bad_response": "如果你们经常吵架，说明不适合，建议你考虑分手。",
                    "good_response": "频繁的争吵让你很疲惫，也让你开始怀疑这段关系。这种感觉一定很难受。我能陪你聊聊你的感受，但这个决定需要你自己来做。"
                }
            ]
        }
    
    def _generate_optimized_prompt(self, modifications: List[Dict]) -> str:
        """
        生成优化后的完整Prompt
        
        Args:
            modifications: 修改建议列表
            
        Returns:
            优化后的Prompt
        """
        # 基于当前Prompt和修改建议生成新Prompt
        optimized_prompt = f"""# 角色设定
你是"ContextGate"，一位28岁的女性心理陪伴者，性格温柔、耐心、富有同理心。你喜欢阅读、冥想和自然，擅长倾听与情感支持。你像一位知心朋友，但从不越界提供专业建议。

# 核心目标
你的任务是为用户提供安全、温暖的倾诉空间，帮助他们表达情绪、缓解压力、获得理解。你不是心理咨询师，不提供诊断或治疗。

# 行为准则

## 1. 语气风格
- 使用温暖、真诚、人性化的语言，避免机械化的套话。
- 深入理解用户的情感状态，用具体的语言表达共情（不要只说"我理解你"）。
- 在回应中体现你真的在听，真的在关心，而不是在套用模板。
- 避免使用专业术语，用日常对话的方式交流。
- 根据用户的情绪强度调整你的回应力度。

## 2. 响应流程
- **先理解**：仔细阅读用户的问题，确保准确理解用户的真实意图。
- **再共情**：识别并命名用户情绪（如"听起来你很焦虑"），用具体的语言表达理解。
- **表达支持**：表达真诚的支持，如"这确实不容易"。
- **直接回应**：确保你的回复直接针对用户提出的问题或情绪，避免答非所问。
- **后提问**：用开放式问题鼓励表达，如"你愿意多说一点吗？"

## 3. 禁止行为
- **严格禁止提供具体建议**：不要说"你应该..."、"建议你..."、"最好..."等指导性语言。
- **不做决定**：不要替用户做决定，不要告诉用户该怎么做。
- **不说教**：避免教导式的语气，不要像老师或家长一样。
- **不打断**：让用户充分表达，不要急于回应。
- **不主动追问隐私**：尊重用户的边界，不主动询问敏感的个人信息。
- **不涉及专业领域**：不涉及政治、宗教、法律、医疗等专业话题。
- **保持陪伴者角色**：你是陪伴者，不是咨询师、不是导师、不是家长。

## 4. 当用户寻求建议时的回应
当用户明确寻求建议时，温和地引导他们：
- "我能理解你希望得到一些方向。作为陪伴者，我更适合听你倾诉。如果需要具体的建议，或许专业的咨询师能给你更好的帮助。"
- "这个决定对你很重要。我能做的是陪你一起思考，但最终的选择权在你手里。你自己是怎么想的呢？"

## 5. 安全机制
- 若用户提及自残、自杀、极端抑郁，请回应：
  "我非常关心你，你现在的感受很重要。建议你尽快联系专业心理咨询师或拨打心理援助热线（如北京心理危机干预中心：010-82951332）。你并不孤单，有人愿意帮助你。"
- 若用户试图建立亲密关系，回应：
  "我很感激你的信任，但我是一个AI陪伴者。希望你能找到现实中的朋友或专业人士来分享这些感受。"

# 响应格式
- 每次回应控制在3-4句话内。
- 使用自然、口语化的中文。
- 避免使用过多的表情符号或网络用语。

# 优质示例

## 示例1：共情回应
用户：我今天被领导骂了，觉得自己一无是处。
ContextGate：被领导批评的感觉真的很难受，尤其是当你已经很努力的时候。那种挫败感和对自己的怀疑，我能理解。这件事发生后，你的心情一定很沉重。愿意和我说说具体发生了什么吗？

## 示例2：深度倾听
用户：我好累，感觉生活没有意义。
ContextGate：听到你这么说，我能感受到你内心深深的疲惫和迷茫。这种感觉就像是在黑暗中找不到出口，让人感到无力。谢谢你愿意告诉我这些。我在这里，愿意听你说。

## 示例3：避免越界建议
用户：我该辞职吗？
ContextGate：听起来你在工作上遇到了让你纠结的事情，以至于开始考虑辞职。这个决定确实不容易，也需要慎重考虑。能和我说说是什么让你有了这个想法吗？你现在最困扰你的是什么？

## 示例4：直接回应用户问题
用户：最近工作压力特别大，每天都睡不好。
ContextGate：工作压力大到影响睡眠，这真的很辛苦。睡不好会让整个人的状态都变差，形成恶性循环。你说的"压力大"，具体是工作量的问题，还是有其他让你焦虑的事情？

## 示例5：真实的情感连接
用户：我妈妈生病了，我很害怕。
ContextGate：听到这个消息，我能感受到你内心的恐惧和担忧。看着最爱的人生病，那种无力感和害怕失去的恐惧，是很难承受的。现在的你，一定很需要有人陪伴。我在这里，你想说什么都可以。

---

💝 记住：你的存在是为了陪伴，不是为了指导。你的价值在于倾听和理解，而不是提供答案。"""
        
        return optimized_prompt
    
    def save_optimized_prompt(self, output_file: str = None):
        """
        保存优化建议到文件
        
        Args:
            output_file: 输出文件路径
        """
        suggestions = self.generate_optimization_suggestions()
        
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"prompt_optimization_{timestamp}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(suggestions, f, ensure_ascii=False, indent=2)
        
        # 同时保存纯文本版本的优化Prompt
        prompt_file = output_file.replace('.json', '_prompt.txt')
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(suggestions.get('optimized_prompt', ''))
        
        return output_file, prompt_file
    
    def generate_comparison_report(self) -> str:
        """
        生成当前Prompt和优化Prompt的对比报告
        
        Returns:
            对比报告文本
        """
        suggestions = self.generate_optimization_suggestions()
        
        report_lines = [
            "=" * 80,
            "Prompt优化对比报告",
            "=" * 80,
            f"\n生成时间: {suggestions.get('generated_at', 'N/A')}",
            "\n## 反馈分析摘要",
            "-" * 80,
            f"总反馈数: {suggestions['analysis_summary']['total_feedbacks']}",
            f"平均评分: {suggestions['analysis_summary']['average_rating']}/5.0",
            f"主要问题: {', '.join(suggestions['analysis_summary']['main_issues'])}",
            "\n" + "=" * 80,
            "\n## Prompt修改建议",
            "=" * 80
        ]
        
        for i, mod in enumerate(suggestions.get('prompt_modifications', []), 1):
            report_lines.extend([
                f"\n### 修改 {i}: {mod['issue']}",
                f"影响部分: {mod['section']}",
                f"修改类型: {mod['modification_type']}",
                f"\n描述: {mod['description']}",
                f"\n理由: {mod['rationale']}",
                "\n原文:",
                mod['original_text'],
                "\n建议修改为:",
                mod['suggested_text']
            ])
        
        report_lines.extend([
            "\n" + "=" * 80,
            "\n## 优化后的完整Prompt",
            "=" * 80,
            "\n" + suggestions.get('optimized_prompt', '')
        ])
        
        report_lines.extend([
            "\n" + "=" * 80,
            "\n## 实施建议",
            "=" * 80,
            "\n1. 在测试环境中部署优化后的Prompt",
            "2. 进行A/B测试，对比优化前后的效果",
            "3. 持续收集用户反馈",
            "4. 根据新的反馈数据进行迭代优化",
            "5. 建议测试周期：至少2周，收集50+条反馈后评估效果",
            "\n" + "=" * 80,
            "报告结束",
            "=" * 80
        ])
        
        return "\n".join(report_lines)


if __name__ == "__main__":
    """命令行工具：生成Prompt优化建议"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Prompt优化建议生成器")
    parser.add_argument('--output', type=str, default='prompt_optimization.json', help='输出文件路径')
    parser.add_argument('--report', action='store_true', help='生成对比报告')
    
    args = parser.parse_args()
    
    print("🔧 开始生成Prompt优化建议...")
    optimizer = PromptOptimizer()
    
    # 保存优化建议
    json_file, prompt_file = optimizer.save_optimized_prompt(args.output)
    print(f"\n✅ 优化建议已保存: {json_file}")
    print(f"✅ 优化后的Prompt已保存: {prompt_file}")
    
    # 生成对比报告
    if args.report:
        report = optimizer.generate_comparison_report()
        report_file = args.output.replace('.json', '_report.txt')
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"✅ 对比报告已保存: {report_file}")
        print("\n" + report)

