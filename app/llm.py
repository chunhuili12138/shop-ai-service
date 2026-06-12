"""LLM 客户端封装（MiMo 等 OpenAI 兼容 API）"""

from typing import Optional
from langchain_openai import ChatOpenAI
from app.config import settings


# 模型配置
MODEL_CONFIGS = {
    "flash": {
        "model": "mimo-v2.5",
        "description": "多模态模型，支持图像/视频/音频，响应速度快",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
    },
    "pro": {
        "model": "mimo-v2.5-pro",
        "description": "旗舰推理模型，适合复杂分析和 Agent 任务",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
    },
    "vision": {
        "model": "mimo-v2.5",
        "description": "多模态视觉模型，支持图像理解",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
    },
}


def get_chat_llm(**kwargs) -> ChatOpenAI:
    """
    获取 Chat LLM 实例（使用默认模型）
    
    Args:
        **kwargs: 额外参数
    
    Returns:
        ChatOpenAI 实例
    """
    if not settings.LLM_API_KEY:
        raise ValueError("请配置 LLM_API_KEY（MiMo API Key）")

    params = {
        "model": settings.LLM_MODEL,
        "temperature": settings.LLM_TEMPERATURE,
        "openai_api_key": settings.LLM_API_KEY,
        "openai_api_base": settings.LLM_BASE_URL,
    }
    if "max_tokens" not in kwargs:
        params["max_tokens"] = settings.LLM_MAX_TOKENS
    params.update(kwargs)
    return ChatOpenAI(**params)


def get_chat_llm_by_model(model_type: str = "flash", **kwargs) -> ChatOpenAI:
    """
    根据模型类型获取 Chat LLM 实例
    
    Args:
        model_type: 模型类型（"flash"、"pro" 或 "vision"）
        **kwargs: 额外参数
    
    Returns:
        ChatOpenAI 实例
    """
    if not settings.LLM_API_KEY:
        raise ValueError("请配置 LLM_API_KEY（MiMo API Key）")
    
    # 获取模型配置
    model_config = MODEL_CONFIGS.get(model_type, MODEL_CONFIGS["flash"])
    
    params = {
        "model": model_config["model"],
        "temperature": settings.LLM_TEMPERATURE,
        "openai_api_key": settings.LLM_API_KEY,
        "openai_api_base": model_config.get("base_url", settings.LLM_BASE_URL),
    }
    if "max_tokens" not in kwargs:
        params["max_tokens"] = settings.LLM_MAX_TOKENS
    params.update(kwargs)
    return ChatOpenAI(**params)


def get_vision_llm(**kwargs) -> ChatOpenAI:
    """
    获取多模态视觉 LLM 实例（MiMo-V2.5）
    
    Args:
        **kwargs: 额外参数
    
    Returns:
        ChatOpenAI 实例
    """
    return get_chat_llm_by_model("vision", **kwargs)


def get_pro_llm(**kwargs) -> ChatOpenAI:
    """
    获取旗舰推理 LLM 实例（MiMo-V2.5-Pro）
    
    Args:
        **kwargs: 额外参数
    
    Returns:
        ChatOpenAI 实例
    """
    return get_chat_llm_by_model("pro", **kwargs)


def select_model(question: str, tool_calls_count: int = 0) -> str:
    """
    根据问题复杂度选择模型
    
    Args:
        question: 用户问题
        tool_calls_count: 预期工具调用数量
    
    Returns:
        模型类型（"flash" 或 "pro"）
    """
    # 简单规则：单工具调用用 flash，多工具调用用 pro
    if tool_calls_count <= 1:
        return "flash"
    else:
        return "pro"


def get_model_info(model_type: str = "flash") -> dict:
    """
    获取模型信息
    
    Args:
        model_type: 模型类型
    
    Returns:
        模型信息字典
    """
    return MODEL_CONFIGS.get(model_type, MODEL_CONFIGS["flash"])


def get_all_models() -> dict:
    """
    获取所有可用模型信息
    
    Returns:
        模型配置字典
    """
    return MODEL_CONFIGS
