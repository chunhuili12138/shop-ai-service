"""
ShopCopilot - 店铺智能助手 AI Service
基于 FastAPI + LangChain 构建的 AI Agent 服务
"""

import os
# 禁用 Chroma 遥测（必须在导入 Chroma 之前设置）
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time

from app.config import settings
from app.chat.router import router as chat_router
from app.nl2sql.security_router import router as security_router
from app.knowledge.router import router as knowledge_router
from app.file.router import router as file_router

# 配置日志
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 第三方库日志级别调高，避免刷屏
for noisy in ["httpcore", "httpx", "openai", "chromadb", "watchfiles",
              "langchain", "langchain_core", "langfuse", "urllib3", "asyncio"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("ShopCopilot AI Service 启动中...")
    logger.info(f"环境: {settings.ENVIRONMENT}")
    logger.info(f"LLM: {settings.LLM_MODEL}")
    logger.info(f"Embedding: {settings.EMBEDDING_MODEL}")
    logger.info(f"长时记忆: {'启用' if settings.MULTI_AGENT_ENABLED else '禁用'}")
    logger.info(f"多 Agent 协作: {'启用' if settings.MULTI_AGENT_ENABLED else '禁用'}")

    # 启动定时任务
    try:
        from app.knowledge.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning(f"定时任务启动失败: {str(e)}")

    yield
    # 关闭时执行
    logger.info("ShopCopilot AI Service 关闭中...")

    # 刷新 LangFuse 缓存
    try:
        from monitoring.langfuse_config import flush
        flush()
    except Exception:
        pass


app = FastAPI(
    title="ShopCopilot AI Service",
    description="店铺智能助手 - 基于 AI Agent 的店铺运营辅助系统",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录请求日志"""
    start_time = time.time()

    # 跳过健康检查和文档的日志
    if request.url.path in ["/", "/health", "/docs", "/openapi.json"]:
        return await call_next(request)

    method = request.method
    path = request.url.path
    logger.debug(f"{method} {path}")

    try:
        response = await call_next(request)
        duration = (time.time() - start_time) * 1000
        logger.info(f"{method} {path} - {response.status_code} ({duration:.0f}ms)")
        return response
    except Exception as e:
        duration = (time.time() - start_time) * 1000
        logger.error(f"{method} {path} - 500 ({duration:.0f}ms) - {str(e)}")
        raise


# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    error_type = type(exc).__name__
    error_msg = str(exc)

    logger.error(f"未处理的异常: [{error_type}] {error_msg}", exc_info=True)

    # 根据错误类型返回不同的提示
    user_msg = "服务器内部错误"
    if "timeout" in error_msg.lower() or "TimeoutError" in error_type:
        user_msg = "请求超时，请稍后重试"
    elif "connection" in error_msg.lower() or "ConnectionError" in error_type:
        user_msg = "网络连接异常，请检查网络后重试"
    elif "memory" in error_msg.lower() or "MemoryError" in error_type:
        user_msg = "服务器资源不足，请稍后重试"
    elif settings.DEBUG:
        user_msg = f"错误: {error_msg}"

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "code": 500,
            "msg": user_msg,
            "error_type": error_type if settings.DEBUG else None,
        }
    )


# 注册路由
app.include_router(chat_router, prefix="/api/chat", tags=["统一聊天"])
app.include_router(security_router, prefix="/api/nl2sql/security", tags=["NL2SQL安全校验"])
app.include_router(knowledge_router, prefix="/api/knowledge", tags=["知识库管理"])
app.include_router(file_router, tags=["文件上传"])


@app.get("/")
async def root():
    """健康检查"""
    return {
        "service": "ShopCopilot AI Service",
        "version": "0.3.0",
        "status": "running",
        "environment": settings.ENVIRONMENT,
        "features": {
            "memory": settings.MULTI_AGENT_ENABLED,
            "multi_agent": settings.MULTI_AGENT_ENABLED,
            "vision": settings.VISION_AGENT_ENABLED,
        }
    }


@app.get("/health")
async def health():
    """详细健康状态（不暴露内部配置）"""
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "features": {
            "memory_enabled": settings.MULTI_AGENT_ENABLED,
            "multi_agent_enabled": settings.MULTI_AGENT_ENABLED,
            "vision_enabled": settings.VISION_AGENT_ENABLED,
        }
    }


@app.get("/api/features")
async def get_features():
    """获取系统功能列表"""
    return {
        "chat": {
            "enabled": True,
            "endpoints": ["/api/chat/stream"],
            "description": "统一聊天接口，自动路由到合适的模块"
        },
        "modules": {
            "rag": {
                "enabled": True,
                "description": "知识问答（套餐、价格、营业时间等）"
            },
            "nl2sql": {
                "enabled": True,
                "description": "数据查询（营业额、顾客数、库存等）"
            },
            "tools": {
                "enabled": True,
                "count": 23,
                "description": "工具调用（查询顾客、库存、排班等）"
            },
            "vision": {
                "enabled": settings.VISION_AGENT_ENABLED,
                "description": "图像识别（OCR、图像理解）"
            },
            "multi_agent": {
                "enabled": settings.MULTI_AGENT_ENABLED,
                "description": "多 Agent 协作（复杂任务处理）"
            }
        },
        "memory": {
            "enabled": settings.MULTI_AGENT_ENABLED,
            "types": ["user_profile", "conversation_summary", "long_term_memory"]
        },
        "security": {
            "endpoints": ["/api/nl2sql/security/*"],
            "description": "SQL 安全校验、注入检测"
        },
        "knowledge": {
            "endpoints": ["/api/knowledge/*"],
            "description": "知识库管理"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.DEBUG,
    )
