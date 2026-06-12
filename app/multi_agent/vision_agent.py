"""
Vision Agent - 图像理解 + OCR Agent
使用 MiMo-V2.5 多模态模型进行图像识别和文字提取
"""

import json
from typing import Optional, Dict, Any
from app.llm import get_vision_llm
from app.common.user_context import UserContext
from app.multi_agent.protocol import AgentResult, AgentType


# OCR 提示词
OCR_PROMPT = """请识别这张图片中的所有文字信息，保持原始格式。

要求：
1. 准确识别所有文字
2. 保持原始排版和格式
3. 如果是表格，保持表格结构
4. 如果有数字，确保准确

识别结果："""

# 数据处理提示词
DATA_PROCESS_PROMPT = """根据以下 OCR 识别结果和用户指令，进行数据处理。

OCR 识别结果：
{ocr_text}

用户指令：{task}

请根据指令进行处理，返回处理结果。如果需要录入数据库，请提取关键信息。"""


class VisionAgent:
    """
    Vision Agent - 图像理解 + OCR
    
    功能：
    1. 图像文字识别（OCR）
    2. 根据用户指令进行数据处理
    3. 支持订单、收据、清单等识别
    """
    
    def __init__(self):
        self._llm = None
    
    @property
    def llm(self):
        """懒加载 LLM"""
        if self._llm is None:
            self._llm = get_vision_llm()
        return self._llm
    
    async def execute(self, task: str, context: UserContext, image_url: str = None, **kwargs) -> AgentResult:
        """
        执行图像理解任务
        
        Args:
            task: 用户任务
            context: 用户上下文
            image_url: 图像 URL
        
        Returns:
            执行结果
        """
        if not image_url:
            return AgentResult(
                agent=AgentType.VISION,
                result="未提供图像",
                confidence=0.0,
                success=False,
                error="No image provided"
            )
        
        try:
            # 1. OCR 识别文字
            ocr_result = await self.extract_text(image_url)
            
            # 2. 根据用户指令进行数据处理
            if task and task.strip():
                result = await self.process_with_instruction(ocr_result, task)
            else:
                result = ocr_result
            
            return AgentResult(
                agent=AgentType.VISION,
                result=result,
                confidence=0.9,
                metadata={
                    "ocr_text": ocr_result,
                    "image_url": image_url,
                }
            )
        except Exception as e:
            print(f"[VisionAgent] 执行失败: {str(e)}")
            return AgentResult(
                agent=AgentType.VISION,
                result=f"图像识别失败: {str(e)}",
                confidence=0.0,
                success=False,
                error=str(e)
            )
    
    async def extract_text(self, image_url: str) -> str:
        """
        OCR 提取文字
        
        Args:
            image_url: 图像 URL
        
        Returns:
            识别结果
        """
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": OCR_PROMPT},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }
            ]
            
            response = await self.llm.ainvoke(messages)
            return response.content.strip()
        except Exception as e:
            print(f"[VisionAgent] OCR 失败: {str(e)}")
            raise
    
    async def process_with_instruction(self, ocr_text: str, task: str) -> str:
        """
        根据用户指令处理 OCR 结果
        
        Args:
            ocr_text: OCR 识别结果
            task: 用户指令
        
        Returns:
            处理结果
        """
        try:
            from app.llm import get_chat_llm
            from langchain_core.messages import HumanMessage
            
            # 使用纯文本 LLM 处理
            llm = get_chat_llm()
            
            prompt = DATA_PROCESS_PROMPT.format(ocr_text=ocr_text, task=task)
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            return response.content.strip()
        except Exception as e:
            print(f"[VisionAgent] 数据处理失败: {str(e)}")
            # 降级：返回 OCR 结果
            return f"OCR 识别结果：\n{ocr_text}"
    
    async def extract_order_info(self, image_url: str) -> Dict[str, Any]:
        """
        提取订单信息
        
        Args:
            image_url: 图像 URL
        
        Returns:
            订单信息字典
        """
        try:
            from langchain_core.messages import HumanMessage
            
            ocr_text = await self.extract_text(image_url)
            
            # 使用 LLM 提取结构化信息
            prompt = f"""请从以下 OCR 识别结果中提取订单信息，返回 JSON 格式：

OCR 识别结果：
{ocr_text}

请提取以下信息：
{{
    "order_id": "订单号",
    "date": "日期",
    "customer_name": "顾客姓名",
    "items": [
        {{
            "name": "商品名称",
            "quantity": "数量",
            "price": "单价"
        }}
    ],
    "total_amount": "总金额",
    "payment_method": "支付方式"
}}

如果某个字段无法识别，请返回 null。"""

            from app.llm import get_chat_llm
            llm = get_chat_llm()
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            return json.loads(response.content)
        except Exception as e:
            print(f"[VisionAgent] 提取订单信息失败: {str(e)}")
            return {}
    
    async def extract_receipt_info(self, image_url: str) -> Dict[str, Any]:
        """
        提取收据信息
        
        Args:
            image_url: 图像 URL
        
        Returns:
            收据信息字典
        """
        try:
            from langchain_core.messages import HumanMessage
            
            ocr_text = await self.extract_text(image_url)
            
            # 使用 LLM 提取结构化信息
            prompt = f"""请从以下 OCR 识别结果中提取收据信息，返回 JSON 格式：

OCR 识别结果：
{ocr_text}

请提取以下信息：
{{
    "receipt_no": "收据号",
    "date": "日期",
    "store_name": "店铺名称",
    "items": [
        {{
            "name": "项目名称",
            "amount": "金额"
        }}
    ],
    "total": "总金额",
    "payment_method": "支付方式"
}}

如果某个字段无法识别，请返回 null。"""

            from app.llm import get_chat_llm
            llm = get_chat_llm()
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            return json.loads(response.content)
        except Exception as e:
            print(f"[VisionAgent] 提取收据信息失败: {str(e)}")
            return {}


# 全局实例
_vision_agent = None


def get_vision_agent() -> VisionAgent:
    """获取 Vision Agent 单例"""
    global _vision_agent
    if _vision_agent is None:
        _vision_agent = VisionAgent()
    return _vision_agent
