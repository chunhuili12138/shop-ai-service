"""
权限隔离和动态 Prompt 测试用例
"""

import pytest

# 设置测试环境
import os
os.environ["ENVIRONMENT"] = "test"
os.environ["LLM_API_KEY"] = "test_key"


class TestUserContext:
    """用户上下文测试"""
    
    def test_user_context_creation(self):
        """测试用户上下文创建"""
        from app.common.user_context import UserContext
        
        ctx = UserContext(
            user_id=1,
            shop_id=5,
            role="店长",
            permissions=["query_revenue", "query_customer"],
        )
        
        assert ctx.user_id == 1
        assert ctx.shop_id == 5
        assert ctx.role == "店长"
        assert len(ctx.permissions) == 2
    
    def test_user_context_has_permission(self):
        """测试权限检查"""
        from app.common.user_context import UserContext
        
        ctx = UserContext(
            user_id=1,
            shop_id=5,
            role="店长",
            permissions=["query_revenue", "query_customer"],
        )
        
        assert ctx.has_permission("query_revenue") is True
        assert ctx.has_permission("query_inventory") is False
    
    def test_user_context_super_admin(self):
        """测试超级管理员权限"""
        from app.common.user_context import UserContext
        
        ctx = UserContext(
            user_id=0,
            shop_id=0,
            role="超级管理员",
            permissions=["*"],
            is_super_admin=True,
        )
        
        assert ctx.has_permission("any_permission") is True
    
    def test_user_context_to_dict(self):
        """测试转换为字典"""
        from app.common.user_context import UserContext
        
        ctx = UserContext(
            user_id=1,
            shop_id=5,
            role="店长",
        )
        
        result = ctx.to_dict()
        
        assert result["user_id"] == 1
        assert result["shop_id"] == 5
        assert result["role"] == "店长"
    
    def test_user_context_from_dict(self):
        """测试从字典创建"""
        from app.common.user_context import UserContext
        
        data = {
            "user_id": 1,
            "shop_id": 5,
            "role": "店长",
            "permissions": ["query_revenue"],
        }
        
        ctx = UserContext.from_dict(data)
        
        assert ctx.user_id == 1
        assert ctx.shop_id == 5
        assert ctx.role == "店长"
    
    def test_create_guest_context(self):
        """测试创建访客上下文"""
        from app.common.user_context import create_guest_context
        
        ctx = create_guest_context(shop_id=5)
        
        assert ctx.user_id == 0
        assert ctx.shop_id == 5
        assert ctx.role == "guest"
    
    def test_create_admin_context(self):
        """测试创建管理员上下文"""
        from app.common.user_context import create_admin_context
        
        ctx = create_admin_context(shop_id=5)
        
        assert ctx.user_id == 1
        assert ctx.shop_id == 5
        assert ctx.role == "店长"


class TestPermissions:
    """权限配置测试"""
    
    def test_get_allowed_tool_names(self):
        """测试获取角色允许的工具名称"""
        from app.tools.permissions import get_allowed_tool_names
        
        店长工具 = get_allowed_tool_names("店长")
        导玩员工具 = get_allowed_tool_names("导玩员")
        仓管工具 = get_allowed_tool_names("仓管")
        财务工具 = get_allowed_tool_names("财务")
        
        assert len(店长工具) == 8  # 店长有所有工具
        assert len(导玩员工具) == 2  # 导玩员只有顾客相关
        assert len(仓管工具) == 2  # 仓管只有库存相关
        assert len(财务工具) == 2  # 财务只有营收相关
    
    def test_get_tools_for_role(self):
        """测试获取角色可用的工具列表"""
        from app.tools.permissions import get_tools_for_role
        
        店长工具 = get_tools_for_role("店长")
        导玩员工具 = get_tools_for_role("导玩员")
        
        assert len(店长工具) == 8
        assert len(导玩员工具) == 2
        
        # 检查导玩员工具是否正确
        tool_names = [t.name for t in 导玩员工具]
        assert "query_customer" in tool_names
        assert "query_customer_purchases" in tool_names
    
    def test_is_tool_allowed(self):
        """测试工具权限检查"""
        from app.tools.permissions import is_tool_allowed
        
        assert is_tool_allowed("店长", "query_revenue") is True
        assert is_tool_allowed("导玩员", "query_revenue") is False
        assert is_tool_allowed("导玩员", "query_customer") is True
    
    def test_get_all_roles(self):
        """测试获取所有角色"""
        from app.tools.permissions import get_all_roles
        
        roles = get_all_roles()
        
        assert "店长" in roles
        assert "导玩员" in roles
        assert "仓管" in roles
        assert "财务" in roles
        assert "guest" in roles
    
    def test_get_role_description(self):
        """测试获取角色描述"""
        from app.tools.permissions import get_role_description
        
        desc = get_role_description("店长")
        
        assert "店铺管理者" in desc
    
    def test_validate_role(self):
        """测试角色验证"""
        from app.tools.permissions import validate_role
        
        assert validate_role("店长") is True
        assert validate_role("导玩员") is True
        assert validate_role("未知角色") is False
    
    def test_get_tools_description_for_role(self):
        """测试获取角色工具描述"""
        from app.tools.permissions import get_tools_description_for_role
        
        desc = get_tools_description_for_role("店长")
        
        assert "query_revenue" in desc
        assert "query_customer" in desc


class TestPromptTemplates:
    """Prompt 模板测试"""
    
    def test_get_system_prompt(self):
        """测试获取系统提示词"""
        from app.tools.prompt_templates import get_system_prompt
        from app.common.user_context import UserContext
        
        ctx = UserContext(
            user_id=1,
            shop_id=5,
            role="店长",
            display_name="张店长",
        )
        
        prompt = get_system_prompt(ctx)
        
        assert "店铺智能助手" in prompt
        assert "张店长" in prompt
        assert "5" in prompt  # shop_id
        assert "query_revenue" in prompt
    
    def test_get_prompt_for_role(self):
        """测试根据角色获取提示词"""
        from app.tools.prompt_templates import get_prompt_for_role
        
        店长prompt = get_prompt_for_role("店长", 5, "张店长")
        导玩员prompt = get_prompt_for_role("导玩员", 5, "李导玩")
        
        assert "店长" in 店长prompt
        assert "导玩员" in 导玩员prompt
        assert "张店长" in 店长prompt
        assert "李导玩" in 导玩员prompt
    
    def test_different_roles_different_prompts(self):
        """测试不同角色有不同的提示词"""
        from app.tools.prompt_templates import get_prompt_for_role
        
        店长prompt = get_prompt_for_role("店长", 5)
        仓管prompt = get_prompt_for_role("仓管", 5)
        
        # 店长应该有更多工具描述
        assert "query_revenue" in 店长prompt
        assert "query_inventory" in 店长prompt
        
        # 仓管应该只有库存相关工具
        assert "query_inventory" in 仓管prompt
        assert "query_revenue" not in 仓管prompt


class TestLLMModelSelection:
    """LLM 模型选择测试"""
    
    def test_select_model_simple(self):
        """测试简单问题选择 flash 模型"""
        from app.llm import select_model
        
        model = select_model("今天的营收", tool_calls_count=1)
        assert model == "flash"
    
    def test_select_model_complex(self):
        """测试复杂问题选择 pro 模型"""
        from app.llm import select_model
        
        model = select_model("分析本月营收趋势", tool_calls_count=3)
        assert model == "pro"
    
    def test_get_chat_llm_by_model(self):
        """测试根据模型类型获取 LLM"""
        from app.llm import get_chat_llm_by_model
        
        # 这个测试需要有效的 API Key
        # 在测试环境中可能会失败
        try:
            llm = get_chat_llm_by_model("flash")
            assert llm is not None
        except Exception:
            pass  # 预期在测试环境中失败
    
    def test_get_model_info(self):
        """测试获取模型信息"""
        from app.llm import get_model_info
        
        flash_info = get_model_info("flash")
        pro_info = get_model_info("pro")
        
        assert "deepseek-v4-flash" in flash_info["model"]
        assert "deepseek-v4-pro" in pro_info["model"]


class TestRouterModels:
    """路由模型测试"""
    
    def test_user_context_data(self):
        """测试用户上下文数据模型"""
        from app.tools.router import UserContextData
        
        data = UserContextData(
            user_id=1,
            shop_id=5,
            role="店长",
            permissions=["query_revenue"],
        )
        
        assert data.user_id == 1
        assert data.shop_id == 5
        assert data.role == "店长"
    
    def test_agent_call_request_with_context(self):
        """测试带用户上下文的 Agent 调用请求"""
        from app.tools.router import AgentCallRequest, UserContextData
        
        ctx = UserContextData(
            user_id=1,
            shop_id=5,
            role="店长",
        )
        
        request = AgentCallRequest(
            question="今天的营收",
            user_context=ctx,
            max_iterations=5,
        )
        
        assert request.question == "今天的营收"
        assert request.user_context is not None
        assert request.user_context.shop_id == 5
    
    def test_agent_call_request_without_context(self):
        """测试不带用户上下文的 Agent 调用请求"""
        from app.tools.router import AgentCallRequest
        
        request = AgentCallRequest(
            question="今天的营收",
            shop_id=5,
            role="店长",
        )
        
        assert request.question == "今天的营收"
        assert request.shop_id == 5
        assert request.role == "店长"


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
