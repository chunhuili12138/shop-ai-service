"""
库存查询和操作工具
使用 Pydantic V2 Schema 约束入参，LangChain StructuredTool 注册
"""

from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class InventoryQueryInput(BaseModel):
    """库存查询参数"""
    shop_id: int = Field(description="店铺ID")
    keyword: Optional[str] = Field(default=None, description="物料名称关键词（可选）")


class LowStockInput(BaseModel):
    """库存预警查询参数"""
    shop_id: int = Field(description="店铺ID")


class MaterialInboundInput(BaseModel):
    """物料入库参数"""
    shop_id: int = Field(description="店铺ID")
    material_id: int = Field(description="物料ID")
    quantity: float = Field(description="入库数量")
    unit_price: Optional[float] = Field(default=None, description="单价（可选）")
    remark: Optional[str] = Field(default=None, description="备注（可选）")


class MaterialOutboundInput(BaseModel):
    """物料出库参数"""
    shop_id: int = Field(description="店铺ID")
    material_id: int = Field(description="物料ID")
    quantity: float = Field(description="出库数量")
    remark: Optional[str] = Field(default=None, description="备注（可选）")


# ==================== Tools ====================

@tool(args_schema=InventoryQueryInput)
def query_inventory(shop_id: int, keyword: Optional[str] = None) -> str:
    """
    查询店铺库存信息。
    可按物料名称关键词过滤，返回物料名称、SKU、当前数量和库存状态。
    """
    sql = """
        SELECT
            m.id as material_id,
            m.name as material_name,
            m.sku,
            m.unit,
            i.quantity,
            m.min_stock,
            CASE WHEN i.quantity <= m.min_stock THEN '库存不足' ELSE '正常' END as status
        FROM inventory i
        JOIN materials m ON i.material_id = m.id
        WHERE i.shop_id = :shop_id AND (m.is_deleted = 0 OR m.is_deleted IS NULL)
    """

    params = {"shop_id": shop_id}

    if keyword:
        sql += " AND m.name LIKE :keyword"
        params["keyword"] = f"%{keyword}%"

    sql += " ORDER BY i.quantity ASC"

    try:
        results = execute_sql(sql, params)
        if not results:
            return "暂无库存数据"

        output = "库存信息:\n"
        for row in results:
            output += f"- [{row['material_id']}] {row['material_name']} ({row['sku']}): {row['quantity']}{row['unit']} [{row['status']}]\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=LowStockInput)
def query_low_stock(shop_id: int) -> str:
    """
    查询库存预警。
    返回当前库存低于最低库存线的物料列表，提示需要补货。
    """
    sql = """
        SELECT
            m.id as material_id,
            m.name as material_name,
            m.sku,
            i.quantity,
            m.min_stock,
            m.unit
        FROM inventory i
        JOIN materials m ON i.material_id = m.id
        WHERE i.shop_id = :shop_id
        AND i.quantity <= m.min_stock
        AND (m.is_deleted = 0 OR m.is_deleted IS NULL)
        ORDER BY (i.quantity / m.min_stock) ASC
    """

    try:
        results = execute_sql(sql, {"shop_id": shop_id})
        if not results:
            return "所有库存正常，无预警"

        output = "库存预警（需要补货）:\n"
        for row in results:
            output += f"- [{row['material_id']}] {row['material_name']} ({row['sku']}): 当前{row['quantity']}{row['unit']}, 最低{row['min_stock']}{row['unit']}\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=MaterialInboundInput)
def material_inbound(shop_id: int, material_id: int, quantity: float, unit_price: Optional[float] = None, remark: Optional[str] = None) -> dict:
    """
    物料入库操作。
    增加物料库存数量，记录入库流水。
    
    返回确认框数据，需要用户确认后执行。
    """
    try:
        # ===== 参数完整性检查 =====
        fields = []

        if not material_id or material_id == 0:
            materials = execute_sql(
                "SELECT id, name, unit, category FROM materials "
                "WHERE shop_id = :sid AND (is_deleted = 0 OR is_deleted IS NULL) "
                "ORDER BY name",
                {"sid": shop_id}
            )
            if not materials:
                return {"type": "error", "message": "当前没有物料"}
            fields.append({
                "name": "material_id",
                "type": "select",
                "label": "选择物料",
                "required": True,
                "options": [
                    {"value": str(m["id"]), "label": f"{m['name']} ({m['unit']}) [{m['category'] or '未分类'}]"}
                    for m in materials
                ],
            })

        if not quantity or quantity <= 0:
            fields.append({
                "name": "quantity",
                "type": "input",
                "label": "入库数量",
                "required": True,
                "placeholder": "请输入入库数量",
            })

        if fields:
            return {
                "type": "confirm",
                "tool_name": "material_inbound",
                "title": "物料入库",
                "message": "请填写以下信息：",
                "details": {},
                "fields": fields,
                "buttons": [
                    {"type": "confirm", "label": "确认入库"},
                    {"type": "cancel", "label": "取消"},
                ],
                "action": "material_inbound",
                "params": {"shop_id": shop_id, **({"material_id": material_id} if material_id else {})},
            }

        # ===== 参数齐全 =====
        material_sql = """
            SELECT id, name, sku, unit
            FROM materials
            WHERE id = :material_id AND shop_id = :shop_id
        """
        material = execute_sql(material_sql, {"material_id": material_id, "shop_id": shop_id})
        
        if not material:
            return {"type": "error", "message": "物料不存在"}
        
        material_info = material[0]
        
        # 查询当前库存
        inventory_sql = """
            SELECT quantity FROM inventory
            WHERE material_id = :material_id AND shop_id = :shop_id
        """
        inventory = execute_sql(inventory_sql, {"material_id": material_id, "shop_id": shop_id})
        current_quantity = inventory[0]["quantity"] if inventory else 0
        
        # 返回确认框数据
        return {
            "type": "confirm",
            "tool_name": "material_inbound",
            "title": "确认入库",
            "message": f"确定要入库 {material_info['name']} 吗？",
            "details": {
                "物料名称": material_info["name"],
                "SKU": material_info["sku"],
                "入库数量": f"{quantity}{material_info['unit']}",
                "当前库存": f"{current_quantity}{material_info['unit']}",
                "入库后库存": f"{current_quantity + quantity}{material_info['unit']}",
            },
            "fields": [
                {"name": "remark", "type": "input", "label": "备注", "required": False, "placeholder": "可选填写备注", "value": remark or ""}
            ],
            "buttons": [
                {"type": "confirm", "label": "确认入库"},
                {"type": "cancel", "label": "取消"}
            ],
            "action": "material_inbound",
            "params": {
                "shop_id": shop_id,
                "material_id": material_id,
                "quantity": quantity,
                "unit_price": unit_price,
            }
        }
    except Exception as e:
        return {"type": "error", "message": f"查询失败: {str(e)}"}


@tool(args_schema=MaterialOutboundInput)
def material_outbound(shop_id: int, material_id: int, quantity: float, remark: Optional[str] = None) -> dict:
    """
    物料出库操作。
    减少物料库存数量，记录出库流水。
    
    返回确认框数据，需要用户确认后执行。
    """
    try:
        # ===== 参数完整性检查 =====
        fields = []

        if not material_id or material_id == 0:
            materials = execute_sql(
                "SELECT id, name, unit, category FROM materials "
                "WHERE shop_id = :sid AND (is_deleted = 0 OR is_deleted IS NULL) "
                "ORDER BY name",
                {"sid": shop_id}
            )
            if not materials:
                return {"type": "error", "message": "当前没有物料"}
            fields.append({
                "name": "material_id",
                "type": "select",
                "label": "选择物料",
                "required": True,
                "options": [
                    {"value": str(m["id"]), "label": f"{m['name']} ({m['unit']}) [{m['category'] or '未分类'}]"}
                    for m in materials
                ],
            })

        if not quantity or quantity <= 0:
            fields.append({
                "name": "quantity",
                "type": "input",
                "label": "出库数量",
                "required": True,
                "placeholder": "请输入出库数量",
            })

        if fields:
            return {
                "type": "confirm",
                "tool_name": "material_outbound",
                "title": "物料出库",
                "message": "请填写以下信息：",
                "details": {},
                "fields": fields,
                "buttons": [
                    {"type": "confirm", "label": "确认出库"},
                    {"type": "cancel", "label": "取消"},
                ],
                "action": "material_outbound",
                "params": {"shop_id": shop_id, **({"material_id": material_id} if material_id else {})},
            }

        # ===== 参数齐全 =====
        material_sql = """
            SELECT id, name, sku, unit
            FROM materials
            WHERE id = :material_id AND shop_id = :shop_id
        """
        material = execute_sql(material_sql, {"material_id": material_id, "shop_id": shop_id})
        
        if not material:
            return {"type": "error", "message": "物料不存在"}
        
        material_info = material[0]
        
        inventory_sql = """
            SELECT quantity FROM inventory
            WHERE material_id = :material_id AND shop_id = :shop_id
        """
        inventory = execute_sql(inventory_sql, {"material_id": material_id, "shop_id": shop_id})
        current_quantity = inventory[0]["quantity"] if inventory else 0
        
        if current_quantity < quantity:
            return {
                "type": "error",
                "message": f"库存不足，当前库存 {current_quantity}{material_info['unit']}，需要 {quantity}{material_info['unit']}"
            }
        
        return {
            "type": "confirm",
            "tool_name": "material_outbound",
            "title": "确认出库",
            "message": f"确定要出库 {material_info['name']} 吗？",
            "details": {
                "物料名称": material_info["name"],
                "SKU": material_info["sku"],
                "出库数量": f"{quantity}{material_info['unit']}",
                "当前库存": f"{current_quantity}{material_info['unit']}",
                "出库后库存": f"{current_quantity - quantity}{material_info['unit']}",
            },
            "fields": [
                {"name": "remark", "type": "input", "label": "备注", "required": False, "placeholder": "可选填写备注", "value": remark or ""}
            ],
            "buttons": [
                {"type": "confirm", "label": "确认出库"},
                {"type": "cancel", "label": "取消"}
            ],
            "action": "material_outbound",
            "params": {
                "shop_id": shop_id,
                "material_id": material_id,
                "quantity": quantity,
                "remark": remark
            }
        }
    except Exception as e:
        return {"type": "error", "message": f"查询失败: {str(e)}"}


def execute_material_inbound(shop_id: int, material_id: int, quantity: float, unit_price: Optional[float] = None, remark: Optional[str] = None, operator_id: Optional[int] = None, token: str = None) -> str:
    """执行物料入库操作（调用 Java 后端 API）"""
    from app.common.backend_client import material_inbound
    result = material_inbound(token=token, shop_id=shop_id, material_id=material_id, quantity=str(int(quantity)), remark=remark)
    if result.get("success"):
        return result.get("msg", "入库成功")
    else:
        return result.get("msg", "入库失败")


def execute_material_outbound(shop_id: int, material_id: int, quantity: float, remark: Optional[str] = None, operator_id: Optional[int] = None, token: str = None) -> str:
    """执行物料出库操作（调用 Java 后端 API）"""
    from app.common.backend_client import material_outbound
    result = material_outbound(token=token, shop_id=shop_id, material_id=material_id, quantity=str(int(quantity)), remark=remark)
    if result.get("success"):
        return result.get("msg", "出库成功")
    else:
        return result.get("msg", "出库失败")
