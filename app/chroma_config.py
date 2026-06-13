"""
Chroma 配置模块
在导入 Chroma 之前禁用遥测
"""

import os
import sys

# 必须在导入 chromadb 之前设置
os.environ["ANONYMIZED_TELEMETRY"] = "false"
os.environ["CHROMA_TELEMETRY"] = "false"
os.environ["DO_NOT_TRACK"] = "true"
os.environ["CHROMA_CLIENT_AUTH_PROVIDER"] = ""
os.environ["CHROMA_CLIENT_AUTH_CREDENTIALS"] = ""

# 导入 Chroma 配置
from chromadb.config import Settings as ChromaSettings

# 创建禁用遥测的配置
chroma_settings = ChromaSettings(
    anonymized_telemetry=False,
    allow_reset=True,
)

# 全局禁用 Chroma 遥测（monkey-patch）
def _disable_chroma_telemetry():
    """禁用 Chroma 遥测"""
    try:
        # 方法1: patch posthog
        import chromadb.telemetry.posthog as posthog_module
        if hasattr(posthog_module, 'Posthog'):
            class MockPosthog:
                def capture(self, *args, **kwargs): pass
                def identify(self, *args, **kwargs): pass
                def flush(self, *args, **kwargs): pass
                def shutdown(self, *args, **kwargs): pass
            posthog_module.Posthog = MockPosthog
    except Exception:
        pass
    
    try:
        # 方法2: patch telemetry module
        import chromadb.telemetry as telemetry_module
        if hasattr(telemetry_module, 'posthog'):
            class MockPosthogModule:
                class Posthog:
                    def capture(self, *args, **kwargs): pass
                    def identify(self, _args, **kwargs): pass
            telemetry_module.posthog = MockPosthogModule()
    except Exception:
        pass

_disable_chroma_telemetry()

__all__ = ["chroma_settings"]
