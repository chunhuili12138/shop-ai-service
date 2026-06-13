"""
套餐API客户端
从Java后端获取最新套餐数据
"""

import httpx
import asyncio
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

# Java后端地址
JAVA_BACKEND_URL = "http://localhost:8081"


class PackageAPIClient:
    """
    套餐API客户端

    调用微信小程序的套餐列表接口获取最新数据
    """

    def __init__(self, base_url: str = None):
        self.base_url = base_url or JAVA_BACKEND_URL

    async def fetch_packages(self, shop_id: int) -> list[dict]:
        """
        从Java后端API获取套餐列表（异步）

        Args:
            shop_id: 店铺ID

        Returns:
            套餐列表 [{id, name, type, price, durationMinutes, description, ...}]
        """
        try:
            url = f"{self.base_url}/api/mp/packages/list"
            params = {
                "shopId": shop_id,
                "page": 1,
                "size": 100,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

            data = response.json()

            if data.get("success"):
                packages = data.get("data", {}).get("list", [])
                logger.info(f"[套餐API] 获取到 {len(packages)} 个套餐")
                return packages
            else:
                logger.warning(f"[套餐API] 请求失败: {data.get('msg')}")
                return []

        except Exception as e:
            logger.error(f"[套餐API] 请求异常: {str(e)}")
            return []

    def format_packages_to_markdown(self, packages: list[dict]) -> str:
        """
        将套餐数据格式化为Markdown
        
        Args:
            packages: 套餐列表
        
        Returns:
            Markdown格式的套餐文档
        """
        # 套餐类型映射
        type_names = {
            "single": "单次卡",
            "weekly": "周卡",
            "monthly": "月卡",
        }
        
        # 使用次数映射
        usage_count = {
            "single": "1次",
            "weekly": "7次（每天1次，共7天）",
            "monthly": "30次（每天1次，共30天）",
        }
        
        md_content = "# 套餐介绍\n\n"
        
        for pkg in packages:
            pkg_type = pkg.get("type", "unknown")
            type_name = type_names.get(pkg_type, pkg_type)
            usage = usage_count.get(pkg_type, "请咨询店员")
            
            # 时长处理
            duration_minutes = pkg.get("durationMinutes", 0) or 0
            hours = duration_minutes // 60
            minutes = duration_minutes % 60
            duration_text = f"{hours}小时{minutes}分钟" if minutes else f"{hours}小时"
            
            md_content += f"## {pkg.get('name', '未知套餐')}\n\n"
            md_content += f"- **类型**：{type_name}\n"
            md_content += f"- **价格**：¥{pkg.get('price', 0)}\n"
            md_content += f"- **使用次数**：{usage}\n"
            md_content += f"- **单次时长**：{duration_text}\n"
            md_content += f"- **每场上限**：{pkg.get('maxPeoplePerSession', 1)}人\n"
            
            if pkg.get("originalPrice"):
                md_content += f"- **原价**：¥{pkg['originalPrice']}\n"
            
            if pkg.get("description"):
                md_content += f"- **说明**：{pkg['description']}\n"
            
            md_content += "\n"
        
        return md_content


# 全局实例
_package_client = None


def get_package_client() -> PackageAPIClient:
    """获取PackageAPIClient单例"""
    global _package_client
    if _package_client is None:
        _package_client = PackageAPIClient()
    return _package_client
