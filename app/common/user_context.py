"""
用户上下文模块
携带用户身份信息，用于权限隔离和动态 Prompt 注入
"""

from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class UserContext:
    """
    用户上下文
    
    Attributes:
        user_id: 用户 ID
        shop_id: 店铺 ID
        role: 角色名称（店长/导玩员/仓管/财务）
        permissions: 权限列表
        is_super_admin: 是否超级管理员
        username: 用户名（可选）
        display_name: 显示名称（可选）
        shop_name: 店铺名称（可选）
    """
    user_id: int
    shop_id: int
    role: str
    permissions: List[str] = field(default_factory=list)
    is_super_admin: bool = False
    username: Optional[str] = None
    display_name: Optional[str] = None
    shop_name: Optional[str] = None
    
    def has_permission(self, permission: str) -> bool:
        """
        检查是否有指定权限
        
        Args:
            permission: 权限编码
        
        Returns:
            是否有权限
        """
        if self.is_super_admin:
            return True
        return permission in self.permissions
    
    def has_any_permission(self, permissions: List[str]) -> bool:
        """
        检查是否有任意一个权限
        
        Args:
            permissions: 权限列表
        
        Returns:
            是否有任意一个权限
        """
        if self.is_super_admin:
            return True
        return any(p in self.permissions for p in permissions)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "user_id": self.user_id,
            "shop_id": self.shop_id,
            "role": self.role,
            "permissions": self.permissions,
            "is_super_admin": self.is_super_admin,
            "username": self.username,
            "display_name": self.display_name,
            "shop_name": self.shop_name,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "UserContext":
        """从字典创建"""
        return cls(
            user_id=data.get("user_id", 0),
            shop_id=data.get("shop_id", 1),
            role=data.get("role", "guest"),
            permissions=data.get("permissions", []),
            is_super_admin=data.get("is_super_admin", False),
            username=data.get("username"),
            display_name=data.get("display_name"),
            shop_name=data.get("shop_name"),
        )


def create_guest_context(shop_id: int = 1) -> UserContext:
    """
    创建访客上下文（用于测试或未登录场景）
    
    Args:
        shop_id: 店铺 ID
    
    Returns:
        访客上下文
    """
    return UserContext(
        user_id=0,
        shop_id=shop_id,
        role="guest",
        permissions=[],
        is_super_admin=False,
        username="guest",
        display_name="访客",
    )


def create_admin_context(shop_id: int = 1) -> UserContext:
    """
    创建管理员上下文（用于测试）
    
    Args:
        shop_id: 店铺 ID
    
    Returns:
        管理员上下文
    """
    return UserContext(
        user_id=1,
        shop_id=shop_id,
        role="店长",
        permissions=["*"],
        is_super_admin=False,
        username="admin",
        display_name="店长",
    )


def create_super_admin_context() -> UserContext:
    """
    创建超级管理员上下文
    
    Returns:
        超级管理员上下文
    """
    return UserContext(
        user_id=0,
        shop_id=0,
        role="超级管理员",
        permissions=["*"],
        is_super_admin=True,
        username="superadmin",
        display_name="超级管理员",
    )
