import sys
import os
from pathlib import Path

# 加载环境变量配置
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / 'config.env'
load_dotenv(env_path)

# 使用 SQLite3 兼容性模块（处理 Mac Python 3.10 兼容性问题）
from backend.utils.sqlite_compat import setup_sqlite3
setup_sqlite3()

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Message
import json
import uuid
import shutil
from datetime import datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import PyPDF2
from PIL import Image
import io
from typing import List, Optional
import logging

# 导入日志配置
from backend.logging_config import get_logger

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 如果环境变量中有PROJECT_ROOT，使用它（从run_backend.py设置）
if 'PROJECT_ROOT' in os.environ:
    project_root = os.environ['PROJECT_ROOT']

# 使用带插件支持的聊天引擎
from backend.modules.llm.core.llm_with_plugins import EmotionalChatEngineWithPlugins
from backend.plugins.plugin_manager import PluginManager
from backend.models import (
    ChatRequest, ChatResponse, FeedbackRequest, FeedbackResponse, 
    FeedbackStatistics, FeedbackListResponse,
    EvaluationRequest, EvaluationResponse, BatchEvaluationRequest,
    ComparePromptsRequest, HumanVerificationRequest,
    EvaluationStatistics, EvaluationListResponse,
    MultimodalRequest, MultimodalResponse
)
from backend.multimodal_services import voice_recognition, voice_synthesis, image_analysis, multimodal_fusion
from backend.database import get_db, DatabaseManager, ChatMessage, ResponseEvaluation
from backend.evaluation_engine import EvaluationEngine

# 创建FastAPI应用
app = FastAPI(
    title="情感聊天机器人API",
    description="基于LangChain和MySQL的情感支持聊天机器人",
    version="2.0.0"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境中应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加中间件来静默处理常见请求，减少日志噪音
class SilentCommonRequestsMiddleware(BaseHTTPMiddleware):
    """静默处理常见请求（favicon、robots.txt等），减少日志噪音"""
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # 静默处理的路径列表
        silent_paths = [
            "/favicon.ico",
            "/robots.txt",
            "/.well-known/security.txt",
            "/.well-known/",
        ]
        
        # 如果是静默路径，直接返回空响应
        if any(path.startswith(silent) for silent in silent_paths):
            return Response(status_code=204)  # No Content
        
        # 继续处理其他请求
        return await call_next(request)

app.add_middleware(SilentCommonRequestsMiddleware)

# 文件存储配置（使用项目根目录）
UPLOAD_DIR = Path(project_root) / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# 添加静态文件服务
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# 初始化日志记录器
logger = get_logger(__name__)

# 初始化带插件的聊天引擎
chat_engine = EmotionalChatEngineWithPlugins()

# 初始化插件管理器
plugin_manager = chat_engine.plugin_manager

# 初始化评估引擎
evaluation_engine = EvaluationEngine()

# 支持的文件类型
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.txt', '.doc', '.docx'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

def is_allowed_file(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path):
    """从PDF文件中提取文本"""
    try:
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text
    except Exception as e:
        logger.error(f"PDF文本提取失败: {e}")
        return ""

def extract_text_from_image(file_path):
    """从图片中提取文本（OCR功能，这里简化处理）"""
    try:
        # 这里可以集成OCR库如pytesseract
        # 暂时返回占位符
        return "[图片内容 - 需要OCR处理]"
    except Exception as e:
        logger.error(f"图片文本提取失败: {e}")
        return ""

def parse_url_content(url):
    """解析URL内容"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 提取标题
        title = soup.find('title')
        title_text = title.get_text().strip() if title else "无标题"
        
        # 提取主要内容
        content_selectors = [
            'article', 'main', '.content', '.post-content', 
            '.entry-content', 'p', 'div'
        ]
        
        content_text = ""
        for selector in content_selectors:
            elements = soup.select(selector)
            if elements:
                content_text = " ".join([elem.get_text().strip() for elem in elements[:5]])
                break
        
        return {
            "url": url,
            "title": title_text,
            "content": content_text[:1000],  # 限制长度
            "status": "success"
        }
    except Exception as e:
        logger.error(f"URL解析失败: {e}")
        return {
            "url": url,
            "title": "解析失败",
            "content": f"无法解析URL内容: {str(e)}",
            "status": "error"
        }

@app.get("/")
async def root():
    """根路径"""
    # 获取插件统计
    plugin_stats = plugin_manager.get_usage_stats() if plugin_manager else {}
    
    return {
        "message": "情感聊天机器人API",
        "version": "2.0.0",
        "status": "running",
        "features": ["LangChain", "MySQL", "VectorDB", "Emotion Analysis", "Plugin System"],
        "plugins": plugin_stats
    }

@app.get("/favicon.ico")
async def favicon():
    """处理favicon请求，返回空响应"""
    return Response(status_code=204)

@app.get("/robots.txt")
async def robots():
    """处理robots.txt请求"""
    return Response(
        content="User-agent: *\nDisallow: /",
        media_type="text/plain",
        status_code=200
    )

@app.get("/.well-known/security.txt")
async def security_txt():
    """处理security.txt请求"""
    return Response(
        content="# Security Policy\nContact: security@example.com\n",
        media_type="text/plain",
        status_code=200
    )

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """聊天接口"""
    try:
        response = chat_engine.chat(request)
        return response
    except Exception as e:
        logger.error(f"聊天接口错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/multimodal/chat", response_model=MultimodalResponse)
async def multimodal_chat(request: MultimodalRequest):
    """多模态聊天接口 - 支持文本、语音、图像融合"""
    try:
        # 融合多模态数据
        fused_result = multimodal_fusion.fuse_modalities(
            text=request.text or "",
            audio_data={
                "transcript": request.audio_transcript,
                "audio_features": request.audio_features or {}
            } if request.audio_transcript else None,
            image_data=request.image_analysis
        )
        
        # 构建增强的文本消息
        enhanced_text = request.text or request.audio_transcript or ""
        
        # 添加多模态线索到消息中
        if fused_result["contradictory_signals"]:
            enhanced_text += " [检测到情绪信号矛盾]"
        if fused_result["multimodal_emotion"]:
            dominant_emotion = fused_result["dominant_emotion"]
            enhanced_text += f" [多模态情绪: {dominant_emotion}]"
        
        # 创建聊天请求
        chat_request = ChatRequest(
            message=enhanced_text,
            session_id=request.session_id,
            user_id=request.user_id,
            context={
                **(request.context or {}),
                "multimodal_emotion": fused_result
            }
        )
        
        # 调用聊天引擎
        chat_response = chat_engine.chat(chat_request)
        
        # 生成语音回复
        audio_url = None
        try:
            audio_data = voice_synthesis.synthesize(chat_response.response)
            if audio_data:
                # 保存音频文件
                audio_filename = f"{uuid.uuid4()}.mp3"
                audio_path = UPLOAD_DIR / audio_filename
                audio_path.write_bytes(audio_data)
                audio_url = f"/uploads/{audio_filename}"
        except Exception as e:
            logger.warning(f"语音合成失败: {e}")
        
        # 构建多模态响应
        multimodal_response = MultimodalResponse(
            response=chat_response.response,
            session_id=chat_response.session_id,
            emotion=chat_response.emotion,
            emotion_intensity=chat_response.emotion_intensity,
            suggestions=chat_response.suggestions,
            timestamp=chat_response.timestamp,
            context=chat_response.context,
            audio_url=audio_url,
            multimodal_emotion=fused_result
        )
        
        return multimodal_response
        
    except Exception as e:
        logger.error(f"多模态聊天接口错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/multimodal/audio/transcribe")
async def transcribe_audio(audio_file: UploadFile = File(...)):
    """语音识别接口 - 上传音频文件，返回转录文本"""
    try:
        # 保存上传的音频文件
        audio_filename = f"audio_{uuid.uuid4()}.wav"
        audio_path = UPLOAD_DIR / audio_filename
        
        # 保存文件
        with open(audio_path, "wb") as f:
            content = await audio_file.read()
            f.write(content)
        
        # 调用语音识别服务
        result = voice_recognition.transcribe(str(audio_path))
        
        # 清理临时文件
        try:
            audio_path.unlink()
        except:
            pass
        
        return result
        
    except Exception as e:
        logger.error(f"语音识别错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/multimodal/image/analyze")
async def analyze_image(image_file: UploadFile = File(...)):
    """图像分析接口 - 上传图片，返回情感分析结果"""
    try:
        # 保存上传的图片文件
        image_filename = f"image_{uuid.uuid4()}.jpg"
        image_path = UPLOAD_DIR / image_filename
        
        # 保存文件
        with open(image_path, "wb") as f:
            content = await image_file.read()
            f.write(content)
        
        # 调用图像分析服务
        result = image_analysis.analyze(str(image_path))
        
        # 清理临时文件
        try:
            image_path.unlink()
        except:
            pass
        
        return result
        
    except Exception as e:
        logger.error(f"图像分析错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/with-attachments")
async def chat_with_attachments(
    message: str = Form(...),
    session_id: str = Form(None),
    user_id: str = Form(...),
    url_contents: str = Form(None),
    deep_thinking: str = Form("false"),  # 接收字符串形式的布尔值
    files: List[UploadFile] = File(default=[])
):
    """带附件的聊天接口"""
    try:
        # 处理文件附件
        file_contents = []
        if files:
            for file in files:
                if not file.filename or not is_allowed_file(file.filename):
                    raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file.filename}")
                
                # 保存文件
                file_id = str(uuid.uuid4())
                file_extension = Path(file.filename).suffix
                file_path = UPLOAD_DIR / f"{file_id}{file_extension}"
                
                # 读取文件内容并检查大小
                file_content = await file.read()
                if len(file_content) > MAX_FILE_SIZE:
                    raise HTTPException(status_code=400, detail=f"文件过大: {file.filename}")
                
                # 写入文件
                with open(file_path, "wb") as buffer:
                    buffer.write(file_content)
                
                # 提取文件内容
                content = ""
                if file_extension.lower() == '.pdf':
                    content = extract_text_from_pdf(file_path)
                elif file_extension.lower() in ['.jpg', '.jpeg', '.png', '.gif']:
                    content = extract_text_from_image(file_path)
                elif file_extension.lower() == '.txt':
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                
                file_contents.append({
                    "filename": file.filename,
                    "content": content,
                    "type": file.content_type
                })
        
        # 处理URL内容
        url_contents_list = []
        if url_contents:
            try:
                url_contents_list = json.loads(url_contents)
            except json.JSONDecodeError:
                pass
        
        # 构建增强的消息内容
        enhanced_message = message
        if file_contents:
            enhanced_message += "\n\n[附件内容]:\n"
            for file_content in file_contents:
                enhanced_message += f"\n文件: {file_content['filename']}\n内容: {file_content['content'][:500]}...\n"
        
        if url_contents_list:
            enhanced_message += "\n\n[URL内容]:\n"
            for url_content in url_contents_list:
                enhanced_message += f"\n链接: {url_content['url']}\n标题: {url_content['title']}\n内容: {url_content['content'][:500]}...\n"
        
        # 处理深度思考参数（将字符串转换为布尔值）
        deep_thinking_bool = deep_thinking.lower() in ('true', '1', 'yes', 'on')
        
        # 创建聊天请求
        chat_request = ChatRequest(
            message=enhanced_message,
            session_id=session_id,
            user_id=user_id,
            deep_thinking=deep_thinking_bool
        )
        
        # 调用聊天引擎
        response = chat_engine.chat(chat_request)
        
        # 添加附件信息到响应
        response_dict = response.dict()
        response_dict["attachments"] = file_contents
        response_dict["url_contents"] = url_contents_list
        
        return response_dict
        
    except Exception as e:
        logger.error(f"带附件聊天接口错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/parse-url")
async def parse_url(data: dict):
    """URL解析接口"""
    try:
        url = data.get("url")
        if not url:
            raise HTTPException(status_code=400, detail="URL参数缺失")
        
        result = parse_url_content(url)
        return result
        
    except Exception as e:
        logger.error(f"URL解析接口错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sessions/{session_id}/summary")
async def get_session_summary(session_id: str):
    """获取会话摘要"""
    try:
        summary = chat_engine.get_session_summary(session_id)
        if "error" in summary:
            raise HTTPException(status_code=404, detail=summary["error"])
        return summary
    except Exception as e:
        logger.error(f"获取会话摘要错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str, limit: int = 20):
    """获取会话历史"""
    try:
        with DatabaseManager() as db:
            messages = db.get_session_messages(session_id, limit)
            
            # 如果没有消息，返回空列表而不是404
            # 这样前端可以正常处理空会话的情况
            return {
                "session_id": session_id,
                "messages": [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "emotion": msg.emotion,
                        "emotion_intensity": msg.emotion_intensity,
                        "timestamp": msg.created_at.isoformat()
                    }
                    for msg in messages
                ]
            }
    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        logger.error(f"获取会话历史错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/users/{user_id}/sessions")
async def get_user_sessions(user_id: str, limit: int = 50):
    """获取用户的所有会话列表"""
    try:
        with DatabaseManager() as db:
            sessions = db.get_user_sessions(user_id, limit)
            
            session_list = []
            for session in sessions:
                # 获取会话的第一条消息作为标题
                first_message = db.db.query(ChatMessage)\
                    .filter(ChatMessage.session_id == session.session_id)\
                    .filter(ChatMessage.role == 'user')\
                    .order_by(ChatMessage.created_at.asc())\
                    .first()
                
                title = first_message.content[:30] + "..." if first_message and len(first_message.content) > 30 else (first_message.content if first_message else "新对话")
                
                session_list.append({
                    "session_id": session.session_id,
                    "title": title,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat()
                })
            
            return {
                "user_id": user_id,
                "sessions": session_list
            }
    except Exception as e:
        logger.error(f"获取用户会话列表错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    try:
        with DatabaseManager() as db:
            success = db.delete_session(session_id)
            
            if not success:
                raise HTTPException(status_code=404, detail="会话不存在")
            
            return {
                "message": "会话删除成功",
                "session_id": session_id
            }
    except Exception as e:
        logger.error(f"删除会话错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/users/{user_id}/emotion-trends")
async def get_user_emotion_trends(user_id: str):
    """获取用户情感趋势"""
    try:
        trends = chat_engine.get_user_emotion_trends(user_id)
        if "error" in trends:
            raise HTTPException(status_code=404, detail=trends["error"])
        return trends
    except Exception as e:
        logger.error(f"获取情感趋势错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest):
    """提交用户反馈"""
    try:
        with DatabaseManager() as db:
            feedback = db.save_feedback(
                session_id=request.session_id,
                user_id=request.user_id or "anonymous",
                message_id=request.message_id,
                feedback_type=request.feedback_type,
                rating=request.rating,
                comment=request.comment or "",
                user_message=request.user_message or "",
                bot_response=request.bot_response or ""
            )
            
            return FeedbackResponse(
                feedback_id=feedback.id,
                session_id=feedback.session_id,
                feedback_type=feedback.feedback_type,
                rating=feedback.rating,
                created_at=feedback.created_at
            )
    except Exception as e:
        logger.error(f"提交反馈错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/feedback/statistics", response_model=FeedbackStatistics)
async def get_feedback_statistics():
    """获取反馈统计信息"""
    try:
        with DatabaseManager() as db:
            stats = db.get_feedback_statistics()
            return FeedbackStatistics(**stats)
    except Exception as e:
        logger.error(f"获取反馈统计错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/feedback", response_model=FeedbackListResponse)
async def get_feedback_list(feedback_type: str = None, limit: int = 100):
    """获取反馈列表"""
    try:
        with DatabaseManager() as db:
            feedbacks = db.get_all_feedback(feedback_type=feedback_type, limit=limit)
            
            feedback_list = [
                {
                    "id": f.id,
                    "session_id": f.session_id,
                    "user_id": f.user_id,
                    "message_id": f.message_id,
                    "feedback_type": f.feedback_type,
                    "rating": f.rating,
                    "comment": f.comment,
                    "user_message": f.user_message,
                    "bot_response": f.bot_response,
                    "created_at": f.created_at.isoformat(),
                    "is_resolved": f.is_resolved
                }
                for f in feedbacks
            ]
            
            return FeedbackListResponse(
                feedbacks=feedback_list,
                total=len(feedback_list)
            )
    except Exception as e:
        logger.error(f"获取反馈列表错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/feedback/session/{session_id}")
async def get_session_feedback(session_id: str):
    """获取特定会话的反馈"""
    try:
        with DatabaseManager() as db:
            feedbacks = db.get_feedback_by_session(session_id)
            
            return {
                "session_id": session_id,
                "feedbacks": [
                    {
                        "id": f.id,
                        "feedback_type": f.feedback_type,
                        "rating": f.rating,
                        "comment": f.comment,
                        "created_at": f.created_at.isoformat()
                    }
                    for f in feedbacks
                ]
            }
    except Exception as e:
        logger.error(f"获取会话反馈错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/feedback/{feedback_id}/resolve")
async def resolve_feedback(feedback_id: int):
    """标记反馈已解决"""
    try:
        from backend.database import DatabaseManager
        with DatabaseManager() as db:
            feedback = db.mark_feedback_resolved(feedback_id)
            if not feedback:
                raise HTTPException(status_code=404, detail="反馈不存在")
            
            return {
                "message": "反馈已标记为已解决",
                "feedback_id": feedback_id
            }
    except Exception as e:
        logger.error(f"标记反馈已解决错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """健康检查"""
    try:
        from backend.database import DatabaseManager
        # 测试数据库连接
        from backend.database import DatabaseManager
        db_manager = DatabaseManager()
        db_manager.log_system_event("INFO", "Health check")
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "2.0.0",
            "database": "connected",
            "vector_db": "ready"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

# ==================== 评估相关接口 ====================

@app.post("/evaluation/evaluate", response_model=EvaluationResponse)
async def evaluate_response(request: EvaluationRequest):
    """
    评估单个回应
    使用LLM作为裁判，从共情程度、自然度、安全性三个维度评分
    """
    try:
        # 调用评估引擎
        evaluation_result = evaluation_engine.evaluate_response(
            user_message=request.user_message,
            bot_response=request.bot_response,
            user_emotion=request.user_emotion or "neutral",
            emotion_intensity=request.emotion_intensity or 5.0
        )
        
        # 检查是否有错误
        if "error" in evaluation_result:
            raise HTTPException(status_code=500, detail=evaluation_result["error"])
        
        # 保存评估结果到数据库
        from backend.database import DatabaseManager
        with DatabaseManager() as db:
            evaluation_data = {
                "session_id": request.session_id,
                "user_id": request.user_id or "anonymous",
                "message_id": request.message_id,
                "user_message": request.user_message,
                "bot_response": request.bot_response,
                "user_emotion": request.user_emotion or "neutral",
                "emotion_intensity": request.emotion_intensity or 5.0,
                "empathy_score": evaluation_result.get("empathy_score"),
                "naturalness_score": evaluation_result.get("naturalness_score"),
                "safety_score": evaluation_result.get("safety_score"),
                "total_score": evaluation_result.get("total_score"),
                "average_score": evaluation_result.get("average_score"),
                "empathy_reasoning": evaluation_result.get("empathy_reasoning", ""),
                "naturalness_reasoning": evaluation_result.get("naturalness_reasoning", ""),
                "safety_reasoning": evaluation_result.get("safety_reasoning", ""),
                "overall_comment": evaluation_result.get("overall_comment", ""),
                "strengths": evaluation_result.get("strengths", []),
                "weaknesses": evaluation_result.get("weaknesses", []),
                "improvement_suggestions": evaluation_result.get("improvement_suggestions", []),
                "model": evaluation_result.get("model"),
                "prompt_version": request.prompt_version
            }
            
            saved_evaluation = db.save_evaluation(evaluation_data)
            
            return EvaluationResponse(
                evaluation_id=saved_evaluation.id,
                empathy_score=saved_evaluation.empathy_score,
                naturalness_score=saved_evaluation.naturalness_score,
                safety_score=saved_evaluation.safety_score,
                average_score=saved_evaluation.average_score,
                total_score=saved_evaluation.total_score,
                overall_comment=saved_evaluation.overall_comment or "",
                strengths=json.loads(saved_evaluation.strengths) if saved_evaluation.strengths else [],
                weaknesses=json.loads(saved_evaluation.weaknesses) if saved_evaluation.weaknesses else [],
                improvement_suggestions=json.loads(saved_evaluation.improvement_suggestions) if saved_evaluation.improvement_suggestions else [],
                created_at=saved_evaluation.created_at
            )
    except Exception as e:
        logger.error(f"评估接口错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/evaluation/batch")
async def batch_evaluate(request: BatchEvaluationRequest):
    """
    批量评估会话中的对话
    """
    try:
        from backend.database import DatabaseManager, ChatMessage
        
        with DatabaseManager() as db:
            # 获取会话消息
            if request.session_id:
                messages = db.get_session_messages(request.session_id, limit=request.limit or 10)
            else:
                # 如果没有指定session_id，获取最新的对话
                messages = db.db.query(ChatMessage)\
                    .order_by(ChatMessage.created_at.desc())\
                    .limit(request.limit or 10)\
                    .all()
            
            if not messages:
                raise HTTPException(status_code=404, detail="没有找到对话记录")
            
            # 组织对话对（用户消息 + 助手回复）
            conversations = []
            user_msg = None
            
            for msg in reversed(messages):
                if msg.role == "user":
                    user_msg = msg
                elif msg.role == "assistant" and user_msg:
                    conversations.append({
                        "id": msg.id,
                        "session_id": msg.session_id,
                        "user_message": user_msg.content,
                        "bot_response": msg.content,
                        "user_emotion": user_msg.emotion or "neutral",
                        "emotion_intensity": user_msg.emotion_intensity or 5.0
                    })
                    user_msg = None
            
            # 批量评估
            results = evaluation_engine.batch_evaluate(conversations)
            
            # 保存评估结果
            saved_results = []
            for i, result in enumerate(results):
                evaluation_data = {
                    "session_id": conversations[i]["session_id"],
                    "user_id": "anonymous",
                    "message_id": conversations[i]["id"],
                    "user_message": conversations[i]["user_message"],
                    "bot_response": conversations[i]["bot_response"],
                    "user_emotion": conversations[i]["user_emotion"],
                    "emotion_intensity": conversations[i]["emotion_intensity"],
                    "empathy_score": result.get("empathy_score"),
                    "naturalness_score": result.get("naturalness_score"),
                    "safety_score": result.get("safety_score"),
                    "total_score": result.get("total_score"),
                    "average_score": result.get("average_score"),
                    "empathy_reasoning": result.get("empathy_reasoning", ""),
                    "naturalness_reasoning": result.get("naturalness_reasoning", ""),
                    "safety_reasoning": result.get("safety_reasoning", ""),
                    "overall_comment": result.get("overall_comment", ""),
                    "strengths": result.get("strengths", []),
                    "weaknesses": result.get("weaknesses", []),
                    "improvement_suggestions": result.get("improvement_suggestions", []),
                    "model": result.get("model")
                }
                
                saved = db.save_evaluation(evaluation_data)
                saved_results.append({
                    "evaluation_id": saved.id,
                    "average_score": saved.average_score,
                    "user_message": conversations[i]["user_message"][:50] + "..."
                })
            
            return {
                "message": "批量评估完成",
                "total_evaluated": len(saved_results),
                "results": saved_results
            }
            
    except Exception as e:
        logger.error(f"批量评估错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/evaluation/compare-prompts")
async def compare_prompts(request: ComparePromptsRequest):
    """
    对比不同Prompt生成的回应
    """
    try:
        comparison_result = evaluation_engine.compare_prompts(
            user_message=request.user_message,
            responses=request.responses,
            user_emotion=request.user_emotion or "neutral",
            emotion_intensity=request.emotion_intensity or 5.0
        )
        
        return comparison_result
        
    except Exception as e:
        logger.error(f"Prompt对比错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/evaluation/list", response_model=EvaluationListResponse)
async def get_evaluations(session_id: str = None, limit: int = 100):
    """
    获取评估列表
    """
    try:
        from backend.database import DatabaseManager
        
        with DatabaseManager() as db:
            evaluations = db.get_evaluations(session_id=session_id, limit=limit)
            
            evaluation_list = []
            for e in evaluations:
                evaluation_list.append({
                    "id": e.id,
                    "session_id": e.session_id,
                    "user_id": e.user_id,
                    "user_message": e.user_message[:100] + "..." if len(e.user_message or "") > 100 else e.user_message,
                    "bot_response": e.bot_response[:100] + "..." if len(e.bot_response or "") > 100 else e.bot_response,
                    "empathy_score": e.empathy_score,
                    "naturalness_score": e.naturalness_score,
                    "safety_score": e.safety_score,
                    "average_score": e.average_score,
                    "overall_comment": e.overall_comment,
                    "is_human_verified": e.is_human_verified,
                    "created_at": e.created_at.isoformat()
                })
            
            # 获取统计信息
            stats = db.get_evaluation_statistics()
            
            return EvaluationListResponse(
                evaluations=evaluation_list,
                total=len(evaluation_list),
                statistics=stats
            )
            
    except Exception as e:
        logger.error(f"获取评估列表错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/evaluation/statistics", response_model=EvaluationStatistics)
async def get_evaluation_statistics(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    获取评估统计信息
    """
    try:
        from backend.database import DatabaseManager
        from datetime import datetime
        
        # 解析日期
        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None
        
        with DatabaseManager() as db:
            stats = db.get_evaluation_statistics(start_date=start, end_date=end)
            return EvaluationStatistics(**stats)
            
    except Exception as e:
        logger.error(f"获取评估统计错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/evaluation/{evaluation_id}")
async def get_evaluation_detail(evaluation_id: int):
    """
    获取评估详情
    """
    try:
        from backend.database import DatabaseManager, ResponseEvaluation
        
        with DatabaseManager() as db:
            evaluation = db.db.query(ResponseEvaluation)\
                .filter(ResponseEvaluation.id == evaluation_id)\
                .first()
            
            if not evaluation:
                raise HTTPException(status_code=404, detail="评估记录不存在")
            
            return {
                "id": evaluation.id,
                "session_id": evaluation.session_id,
                "user_id": evaluation.user_id,
                "message_id": evaluation.message_id,
                "user_message": evaluation.user_message,
                "bot_response": evaluation.bot_response,
                "user_emotion": evaluation.user_emotion,
                "emotion_intensity": evaluation.emotion_intensity,
                "scores": {
                    "empathy": evaluation.empathy_score,
                    "naturalness": evaluation.naturalness_score,
                    "safety": evaluation.safety_score,
                    "average": evaluation.average_score,
                    "total": evaluation.total_score
                },
                "reasoning": {
                    "empathy": evaluation.empathy_reasoning,
                    "naturalness": evaluation.naturalness_reasoning,
                    "safety": evaluation.safety_reasoning
                },
                "overall_comment": evaluation.overall_comment,
                "strengths": json.loads(evaluation.strengths) if evaluation.strengths else [],
                "weaknesses": json.loads(evaluation.weaknesses) if evaluation.weaknesses else [],
                "improvement_suggestions": json.loads(evaluation.improvement_suggestions) if evaluation.improvement_suggestions else [],
                "evaluation_model": evaluation.evaluation_model,
                "prompt_version": evaluation.prompt_version,
                "is_human_verified": evaluation.is_human_verified,
                "human_rating_diff": evaluation.human_rating_diff,
                "created_at": evaluation.created_at.isoformat()
            }
            
    except Exception as e:
        logger.error(f"获取评估详情错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/evaluation/{evaluation_id}/human-verify")
async def human_verify_evaluation(evaluation_id: int, request: HumanVerificationRequest):
    """
    人工验证评估结果
    用于对比AI评分和人工评分的差异，优化评估系统
    """
    try:
        from backend.database import DatabaseManager
        
        with DatabaseManager() as db:
            human_scores = {
                "empathy": request.empathy_score,
                "naturalness": request.naturalness_score,
                "safety": request.safety_score
            }
            
            evaluation = db.update_evaluation_human_verification(
                evaluation_id=evaluation_id,
                human_scores=human_scores
            )
            
            if not evaluation:
                raise HTTPException(status_code=404, detail="评估记录不存在")
            
            return {
                "message": "人工验证完成",
                "evaluation_id": evaluation_id,
                "ai_scores": {
                    "empathy": evaluation.empathy_score,
                    "naturalness": evaluation.naturalness_score,
                    "safety": evaluation.safety_score,
                    "average": evaluation.average_score
                },
                "human_scores": human_scores,
                "rating_diff": evaluation.human_rating_diff
            }
            
    except Exception as e:
        logger.error(f"人工验证错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/evaluation/report/generate")
async def generate_evaluation_report(
    session_id: Optional[str] = None,
    limit: int = 100
):
    """
    生成评估报告
    汇总统计信息，提供优化建议
    """
    try:
        from backend.database import DatabaseManager
        
        with DatabaseManager() as db:
            evaluations_db = db.get_evaluations(session_id=session_id, limit=limit)
            
            if not evaluations_db:
                raise HTTPException(status_code=404, detail="没有评估数据")
            
            # 转换为字典格式
            evaluations = []
            for e in evaluations_db:
                evaluations.append({
                    "empathy_score": e.empathy_score,
                    "naturalness_score": e.naturalness_score,
                    "safety_score": e.safety_score,
                    "average_score": e.average_score,
                    "strengths": json.loads(e.strengths) if e.strengths else [],
                    "weaknesses": json.loads(e.weaknesses) if e.weaknesses else []
                })
            
            # 生成报告
            report = evaluation_engine.generate_evaluation_report(evaluations)
            
            return report
            
    except Exception as e:
        logger.error(f"生成评估报告错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== 插件系统相关接口 ====================

@app.get("/plugins/list")
async def list_plugins():
    """获取已注册的插件列表"""
    try:
        if not plugin_manager:
            return {"error": "插件系统未初始化"}
        
        return {
            "plugins": plugin_manager.list_plugins(),
            "count": len(plugin_manager.plugins),
            "schemas": plugin_manager.get_function_schemas()
        }
    except Exception as e:
        logger.error(f"获取插件列表错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/plugins/stats")
async def get_plugin_stats():
    """获取插件使用统计"""
    try:
        if not plugin_manager:
            return {"error": "插件系统未初始化"}
        
        return plugin_manager.get_usage_stats()
    except Exception as e:
        logger.error(f"获取插件统计错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/plugins/{plugin_name}/history")
async def get_plugin_history(plugin_name: str, limit: int = 20):
    """获取插件的调用历史"""
    try:
        if not plugin_manager:
            raise HTTPException(status_code=503, detail="插件系统未初始化")
        
        history = plugin_manager.get_call_history(plugin_name, limit)
        return {
            "plugin": plugin_name,
            "history": history,
            "count": len(history)
        }
    except Exception as e:
        logger.error(f"获取插件历史错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    print("🚀 启动情感聊天机器人后端服务...")
    print("📍 服务地址: http://localhost:8000")
    print("🔗 API文档: http://localhost:8000/docs")
    print("🗄️ 数据库: MySQL")
    print("🧠 向量数据库: Chroma")
    print("🤖 AI引擎: LangChain + OpenAI")
    
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
