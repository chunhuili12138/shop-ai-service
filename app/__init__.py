"""ShopCopilot AI Service"""

import os
# 禁用 Chroma 遥测（必须在导入任何 Chroma 相关模块之前设置）
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"
