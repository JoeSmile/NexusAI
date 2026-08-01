"""
Agent Tools - Agent工具函数集合

提供文档中提到的核心工具函数：
1. play_meditation_audio() - 播放冥想音频
2. set_daily_reminder() - 设置每日提醒
3. search_mental_health_resources() - 搜索心理健康资源
5. send_follow_up_message() - 发送回访消息
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Any

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, project_root)

# 延迟导入，避免循环依赖
# 使用 importlib 直接加载文件，避免触发 backend/agent/__init__.py
import importlib.util


def _load_module_from_file(module_name: str, file_path: str):
    """直接从文件加载模块，避免包导入触发 __init__.py"""
    import os
    full_path = os.path.join(project_root, file_path)
    spec = importlib.util.spec_from_file_location(module_name, full_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def _get_db_session():
    from backend.database import SessionLocal
    return SessionLocal()


def _get_audio_player():
    module = _load_module_from_file('audio_player', 'backend/agent/tools/audio_player.py')
    return module.get_audio_player()

def _get_scheduler():
    module = _load_module_from_file('scheduler_service', 'backend/agent/tools/scheduler_service.py')
    return module.get_scheduler_service()

def _get_reminder_type():
    module = _load_module_from_file('scheduler_service', 'backend/agent/tools/scheduler_service.py')
    return module.ReminderType

def _get_psychology_db():
    module = _load_module_from_file('psychology_db', 'backend/agent/tools/psychology_db.py')
    return module.get_psychology_db()



def play_meditation_audio(genre: str, user_id: str | None = None) -> dict[str, Any]:
    """
    播放冥想音频，缓解焦虑
    
    Args:
        genre: 音频类型（"sleep"/"anxiety"/"relaxation"/"breathing"等）
        user_id: 用户ID（可选）
        
    Returns:
        {
            "success": bool,
            "audio": Dict,  # 音频信息
            "message": str
        }
    """
    try:
        audio_player = _get_audio_player()
        
        # 映射genre到主题
        genre_map = {
            "sleep": "sleep",
            "anxiety": "anxiety",
            "relaxation": "relaxation",
            "breathing": "breathing",
            "meditation": "relaxation"
        }
        
        theme = genre_map.get(genre.lower(), "relaxation")
        
        # 搜索音频
        audio_list = audio_player.search_audio(
            theme=theme,
            category="meditation"
        )
        
        if not audio_list:
            # 如果没有找到，尝试搜索白噪音
            audio_list = audio_player.search_audio(category="white_noise")
        
        if not audio_list:
            return {
                "success": False,
                "error": f"未找到类型为'{genre}'的音频资源",
                "message": "抱歉，暂时没有可用的音频资源"
            }
        
        # 选择第一个音频
        selected_audio = audio_list[0]
        
        # 如果提供了user_id，记录播放历史
        if user_id:
            result = audio_player.play_audio(user_id, selected_audio["id"])
            return result
        
        return {
            "success": True,
            "audio": {
                "id": selected_audio["id"],
                "title": selected_audio["title"],
                "url": selected_audio.get("url", ""),
                "duration": selected_audio.get("duration", 0),
                "description": selected_audio.get("description", "")
            },
            "message": f"已为你准备：{selected_audio['title']}"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "播放音频时出错"
        }


def set_daily_reminder(time: str, message: str, user_id: str) -> dict[str, Any]:
    """
    设置每日提醒，养成作息习惯
    
    Args:
        time: 提醒时间，格式 "HH:MM" 或 "HH:MM:SS"
        message: 提醒消息内容
        user_id: 用户ID
        
    Returns:
        {
            "success": bool,
            "reminder_id": str,
            "message": str
        }
    """
    try:
        scheduler = _get_scheduler()
        
        # 解析时间
        time_parts = time.split(":")
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
        
        # 计算今天的提醒时间
        today = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # 如果今天的时间已过，设置为明天
        if today < datetime.now():
            today = today + timedelta(days=1)
        
        # 创建每日重复提醒
        reminder_id = scheduler.create_reminder(
            user_id=user_id,
            content=message,
            schedule_time=today,
            reminder_type=_get_reminder_type().DAILY,
            metadata={
                "source": "agent_tool",
                "created_at": datetime.now().isoformat()
            }
        )
        
        return {
            "success": True,
            "reminder_id": reminder_id,
            "scheduled_time": today.isoformat(),
            "time": time,
            "message": f"已设置每日提醒：每天{time}提醒你「{message}」"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "设置提醒时出错"
        }


def search_mental_health_resources(query: str, resource_type: str | None = None) -> dict[str, Any]:
    """
    检索专业心理文章，提供知识支持
    
    Args:
        query: 搜索关键词
        resource_type: 资源类型（"article"/"video"/"exercise"），可选
        
    Returns:
        {
            "count": int,
            "resources": List[Dict],
            "message": str
        }
    """
    try:
        psychology_db = _get_psychology_db()
        
        # 从查询中提取可能的分类
        category_map = {
            "焦虑": "anxiety",
            "抑郁": "depression",
            "睡眠": "sleep",
            "压力": "anxiety",
            "失眠": "sleep",
            "正念": "mindfulness",
            "冥想": "mindfulness"
        }
        
        category = None
        for keyword, cat in category_map.items():
            if keyword in query:
                category = cat
                break
        
        # 搜索资源
        resources = psychology_db.search_resources(
            category=category,
            resource_type=resource_type,
            tags=[query] if query else None
        )
        
        # 如果指定了资源类型，只返回该类型
        if resource_type:
            resources = [r for r in resources if r.get("resource_type") == resource_type]
        
        # 限制返回数量
        resources = resources[:5]
        
        # 格式化结果
        formatted_resources = []
        for resource in resources:
            formatted_resources.append({
                "id": resource.get("id", ""),
                "title": resource.get("title", ""),
                "type": resource.get("resource_type", ""),
                "url": resource.get("url", ""),
                "summary": resource.get("summary") or resource.get("description", ""),
                "read_time": resource.get("read_time", 0),
                "duration": resource.get("duration", 0),
                "tags": resource.get("tags", [])
            })
        
        return {
            "count": len(formatted_resources),
            "resources": formatted_resources,
            "query": query,
            "message": f"找到{len(formatted_resources)}个相关资源" if formatted_resources else "未找到相关资源"
        }
        
    except Exception as e:
        return {
            "count": 0,
            "resources": [],
            "error": str(e),
            "message": "搜索资源时出错"
        }


def send_follow_up_message(user_id: str, days_ago: int = 1, custom_message: str | None = None) -> dict[str, Any]:
    """
    发送回访消息，验证效果
    
    Args:
        user_id: 用户ID
        days_ago: 回访几天前的对话，默认1天前
        custom_message: 自定义消息内容（可选）
        
    Returns:
        {
            "success": bool,
            "message": str,
            "scheduled_at": str
        }
    """
    try:
        scheduler = _get_scheduler()
        
        # 计算回访时间（默认明天）
        follow_up_time = datetime.now() + timedelta(days=1)
        
        # 如果没有自定义消息，生成默认回访消息
        if not custom_message:
            custom_message = f"你好，距离我们上次沟通已经过去{days_ago}天了。有什么需要协助的吗？"
        
        # 创建一次性提醒（回访消息）
        reminder_id = scheduler.create_reminder(
            user_id=user_id,
            content=custom_message,
            schedule_time=follow_up_time,
            reminder_type=_get_reminder_type().ONE_TIME,
            metadata={
                "source": "agent_follow_up",
                "follow_up_days": days_ago,
                "created_at": datetime.now().isoformat()
            }
        )
        
        return {
            "success": True,
            "reminder_id": reminder_id,
            "message": custom_message,
            "scheduled_at": follow_up_time.isoformat(),
            "days_ago": days_ago
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "发送回访消息时出错"
        }


# 导出所有工具函数
__all__ = [
    "play_meditation_audio",
    "search_mental_health_resources",
    "send_follow_up_message",
    "set_daily_reminder"
]

