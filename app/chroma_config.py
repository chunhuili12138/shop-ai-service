"""
Chroma 配置模块
在导入 Chroma 之前禁用遥测
"""

import os

# 必须在导入 chromadb 之前设置
os.environ["ANONYMIZED_TELEMETRY"] = "false"
os.environ["CHROMA_TELEMETRY"] = "false"
os.environ["DO_NOT_TRACK"] = "true"

# 导入 Chroma 配置
from chromadb.config import Settings as ChromaSettings

# 创建禁用遥测的配置
chroma_settings = ChromaSettings(
    anonymized_telemetry=False,
    allow_reset=True,
)

__all__ = ["chroma_settings"]
