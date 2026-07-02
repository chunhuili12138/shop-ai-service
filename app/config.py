"""
配置管理模块
从环境变量或 .env 文件加载配置
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings
from typing import List
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""

    # ========== 基础配置 ==========
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    PORT: int = 8000

    # ========== CORS 配置 ==========
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",  # Vue3 前端
        "http://localhost:3000",
        "http://localhost:8080",
    ]

    # ========== LLM 配置（MiMo，OpenAI 兼容接口）==========
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://token-plan-cn.xiaomimimo.com/v1"  # Token Plan 中国集群
    LLM_MODEL: str = "mimo-v2.5"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 4000  # 提升输出上限，支持含文件内容的较长回复

    # ========== MiMo 模型配置 ==========
    MIMO_VISION_MODEL: str = "mimo-v2.5"  # 多模态模型（支持图像/视频/音频）
    MIMO_PRO_MODEL: str = "mimo-v2.5-pro"  # 旗舰推理模型（适合复杂分析和 Agent 任务）

    # ========== Embedding 配置（阿里百炼 text-embedding-v4）==========
    EMBEDDING_API_KEY: str = ""  # 阿里百炼 API Key
    EMBEDDING_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_MODEL: str = "text-embedding-v4"
    EMBEDDING_DIMENSIONS: int = 1024
    # text-embedding-v4 支持自定义维度（2048/1536/1024/768/512/256/128/64）
    EMBEDDING_USE_CUSTOM_DIMENSIONS: bool = True
    EMBEDDING_CHECK_CTX_LENGTH: bool = False

    # ========== 向量库配置 ==========
    VECTOR_STORE_TYPE: str = "chroma"  # chroma / milvus
    CHROMA_PERSIST_DIR: str = "./data/chroma_db"
    CHROMA_COLLECTION_NAME: str = "shop_knowledge"

    # ========== MySQL 配置（复用现有系统）==========
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = "shop_operate_system"

    @property
    def MYSQL_URL(self) -> str:
        from urllib.parse import quote_plus
        password = quote_plus(self.MYSQL_PASSWORD)
        return f"mysql+pymysql://{self.MYSQL_USER}:{password}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"

    # ========== Redis 配置（复用现有系统）==========
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_SESSION_TTL: int = 259200  # 会话TTL（秒，默认3天）

    # ========== LangFuse 可观测性配置 ==========
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # ========== NL2SQL 配置 ==========
    NL2SQL_MAX_ROWS: int = 100  # 查询最大返回行数
    NL2SQL_TIMEOUT: int = 30  # SQL执行超时（秒）
    NL2SQL_DANGEROUS_KEYWORDS: List[str] = [
        "DROP", "DELETE", "TRUNCATE", "ALTER", "UPDATE", "INSERT"
    ]

    # ========== RAG 配置 ==========
    RAG_TOP_K: int = 5  # 检索返回文档数
    RAG_SCORE_THRESHOLD: float = 0.6  # 相关性阈值
    RAG_CHUNK_SIZE: int = 1000  # 文档分块大小（增大减少块数，降低API调用）
    RAG_CHUNK_OVERLAP: int = 100  # 分块重叠

    # ========== Agent 配置 ==========
    AGENT_MAX_ITERATIONS: int = 10  # Agent最大迭代次数
    AGENT_TIMEOUT: int = 60  # Agent超时（秒）

    # ========== 长时记忆配置 ==========
    MEMORY_ENABLED: bool = True  # 是否启用长时记忆
    MEMORY_TYPE: str = "vector"  # 记忆存储类型（redis / vector / hybrid）
    MEMORY_TTL: int = 2592000  # 记忆过期时间（秒，默认30天）
    MEMORY_TOP_K: int = 5  # 记忆检索返回数量
    MEMORY_COLLECTION_NAME: str = "agent_memory"  # Chroma 集合名称

    # ========== 多 Agent 协作配置 ==========
    MULTI_AGENT_ENABLED: bool = True  # 是否启用多 Agent 协作
    SUPERVISOR_MODEL: str = "flash"  # Supervisor 使用的模型（flash / pro）
    VISION_AGENT_ENABLED: bool = True  # 是否启用 Vision Agent

    # ========== 后台管理系统配置 ==========
    BACKEND_URL: str = "http://localhost:8081"  # 后台管理系统地址
    TOKEN_CACHE_TTL: int = 300  # Token 缓存过期时间（秒，默认5分钟）

    # ========== HITL 审批阈值配置 ==========
    HITL_REFUND_THRESHOLD: float = 100.0  # 退款超过此金额需要审批
    HITL_TRANSFER_THRESHOLD: float = 1000.0  # 转账超过此金额需要审批

    # ========== 互联网搜索配置 ==========
    SEARCH_API: str = "tavily"  # 搜索引擎（tavily / duckduckgo）
    TAVILY_API_KEY: str = ""  # Tavily API Key

    # 兼容旧版 OPENAI_* 环境变量（LLM 专用）
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""

    @model_validator(mode="after")
    def apply_legacy_llm_env(self) -> "Settings":
        if not self.LLM_API_KEY and self.OPENAI_API_KEY:
            self.LLM_API_KEY = self.OPENAI_API_KEY
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()
