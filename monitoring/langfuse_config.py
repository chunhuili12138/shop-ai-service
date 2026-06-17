"""
LangFuse 可观测性配置
提供 LLM 调用追踪、Token 监控、成本分析
"""

import time
import asyncio
import inspect
import functools
import logging
from typing import Optional, Dict, Any, Callable
from contextlib import contextmanager
from app.config import settings

logger = logging.getLogger(__name__)


# LangFuse 全局实例
_langfuse = None
_langfuse_handler = None


def get_langfuse():
    """
    获取 LangFuse 实例（单例）
    
    Returns:
        LangFuse 实例，如果未启用则返回 None
    """
    global _langfuse
    
    if not settings.LANGFUSE_ENABLED:
        return None
    
    if _langfuse is None:
        try:
            from langfuse import Langfuse
            
            _langfuse = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
                flush_at=1,
                flush_interval=1,
            )
            
            logger.info(f"LangFuse 已初始化: {settings.LANGFUSE_HOST}")
        except Exception as e:
            logger.error(f"LangFuse 初始化失败: {str(e)}")
            return None
    
    return _langfuse


def get_langfuse_callback_handler():
    """
    获取 LangFuse 回调处理器（用于 LangChain 集成）
    
    Returns:
        CallbackHandler 实例，如果未启用则返回 None
    """
    global _langfuse_handler
    
    if not settings.LANGFUSE_ENABLED:
        return None
    
    if _langfuse_handler is None:
        try:
            from langfuse.callback import CallbackHandler
            
            _langfuse_handler = CallbackHandler(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
            )
            
            logger.info("LangFuse 回调处理器已初始化")
        except Exception as e:
            logger.error(f"LangFuse 回调处理器初始化失败: {str(e)}")
            return None
    
    return _langfuse_handler


def create_trace(name: str, metadata: dict = None):
    """
    创建追踪记录
    
    Args:
        name: 追踪名称
        metadata: 元数据
    
    Returns:
        Trace 实例，如果未启用则返回 None
    """
    langfuse = get_langfuse()
    if langfuse is None:
        return None
    
    try:
        trace = langfuse.trace(
            name=name,
            metadata=metadata or {},
        )
        return trace
    except Exception as e:
        logger.error(f"LangFuse 创建追踪失败: {str(e)}")
        return None


def create_span(trace, name: str, metadata: dict = None):
    """
    创建跨度记录
    
    Args:
        trace: 父追踪实例
        name: 跨度名称
        metadata: 元数据
    
    Returns:
        Span 实例，如果未启用则返回 None
    """
    if trace is None:
        return None
    
    try:
        span = trace.span(
            name=name,
            metadata=metadata or {},
        )
        return span
    except Exception as e:
        logger.error(f"LangFuse 创建跨度失败: {str(e)}")
        return None


def flush():
    """
    刷新 LangFuse 缓存（在应用关闭时调用）
    """
    langfuse = get_langfuse()
    if langfuse is not None:
        try:
            langfuse.flush()
            logger.info("LangFuse 缓存已刷新")
        except Exception as e:
            logger.error(f"LangFuse 刷新失败: {str(e)}")


def trace_function(name: str, metadata: dict = None):
    """
    装饰器：自动追踪函数执行（兼容同步和异步函数）

    Args:
        name: 追踪名称
        metadata: 额外元数据

    Returns:
        装饰器函数
    """
    def decorator(func: Callable):
        if inspect.iscoroutinefunction(func):
            # 异步函数
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                trace = create_trace(name, metadata)
                start_time = time.time()

                try:
                    result = await func(*args, **kwargs)
                    duration_ms = (time.time() - start_time) * 1000

                    if trace:
                        create_span(trace, "success", {
                            "duration_ms": duration_ms,
                            "result_type": type(result).__name__,
                        })

                    return result
                except Exception as e:
                    duration_ms = (time.time() - start_time) * 1000

                    if trace:
                        create_span(trace, "error", {
                            "duration_ms": duration_ms,
                            "error": str(e),
                        })

                    raise
            return async_wrapper
        else:
            # 同步函数
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                trace = create_trace(name, metadata)
                start_time = time.time()

                try:
                    result = func(*args, **kwargs)
                    duration_ms = (time.time() - start_time) * 1000

                    if trace:
                        create_span(trace, "success", {
                            "duration_ms": duration_ms,
                            "result_type": type(result).__name__,
                        })

                    return result
                except Exception as e:
                    duration_ms = (time.time() - start_time) * 1000

                    if trace:
                        create_span(trace, "error", {
                            "duration_ms": duration_ms,
                            "error": str(e),
                        })

                    raise
            return sync_wrapper
    return decorator


@contextmanager
def trace_span(name: str, metadata: dict = None):
    """
    上下文管理器：追踪代码块执行
    
    Args:
        name: 跨度名称
        metadata: 额外元数据
    
    Yields:
        Span 实例
    """
    langfuse = get_langfuse()
    span = None
    
    if langfuse:
        try:
            trace = langfuse.trace(name=name)
            span = trace.span(name=name, metadata=metadata or {})
        except Exception as e:
            logger.error(f"LangFuse 创建跨度失败: {str(e)}")
    
    start_time = time.time()
    
    try:
        yield span
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        if span:
            try:
                span.end(metadata={"error": str(e), "duration_ms": duration_ms})
            except Exception:
                pass
        raise
    else:
        duration_ms = (time.time() - start_time) * 1000
        if span:
            try:
                span.end(metadata={"duration_ms": duration_ms})
            except Exception:
                pass


class LangFuseTracker:
    """
    LangFuse 追踪器
    提供便捷的追踪方法
    """
    
    def __init__(self, trace_name: str, metadata: dict = None):
        """
        初始化追踪器
        
        Args:
            trace_name: 追踪名称
            metadata: 额外元数据
        """
        self.trace_name = trace_name
        self.metadata = metadata or {}
        self.trace = None
        self.start_time = None
    
    def start(self):
        """开始追踪"""
        self.trace = create_trace(self.trace_name, self.metadata)
        self.start_time = time.time()
        return self
    
    def span(self, name: str, metadata: dict = None):
        """创建跨度"""
        if self.trace:
            return create_span(self.trace, name, metadata)
        return None
    
    def end(self, metadata: dict = None):
        """结束追踪"""
        if self.trace and self.start_time:
            duration_ms = (time.time() - self.start_time) * 1000
            final_metadata = {"duration_ms": duration_ms}
            if metadata:
                final_metadata.update(metadata)
            
            try:
                create_span(self.trace, "total", final_metadata)
            except Exception:
                pass
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.end({"error": str(exc_val)})
        else:
            self.end()
        return False
