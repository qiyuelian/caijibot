# -*- coding: utf-8 -*-
"""
用户权限管理器
管理用户权限和访问控制
"""

from typing import Dict, List, Set, Optional
from datetime import datetime
from enum import Enum

from ..database.database_manager import DatabaseManager
from ..config.settings import Settings
from ..utils.logger import LoggerMixin
from sqlalchemy import select, update


class UserRole(str, Enum):
    """用户角色枚举"""
    ADMIN = "admin"         # 管理员 - 所有权限
    OPERATOR = "operator"   # 操作员 - 大部分权限
    VIEWER = "viewer"       # 查看者 - 只读权限
    BANNED = "banned"       # 被禁用户


class UserManager(LoggerMixin):
    """用户权限管理器"""
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        初始化用户管理器
        
        Args:
            db_manager: 数据库管理器
            settings: 配置对象
        """
        self.db_manager = db_manager
        self.settings = settings
        
        # 权限配置
        self.role_permissions = {
            UserRole.ADMIN: {
                "can_add_channel", "can_remove_channel", "can_manage_settings",
                "can_manage_users", "can_view_stats", "can_search", "can_manage_storage",
                "can_manage_downloads", "can_manage_dedup", "can_manage_tags"
            },
            UserRole.OPERATOR: {
                "can_add_channel", "can_view_stats", "can_search", 
                "can_manage_downloads", "can_manage_tags"
            },
            UserRole.VIEWER: {
                "can_view_stats", "can_search"
            },
            UserRole.BANNED: set()
        }
        
        # 管理员用户ID列表（从配置或环境变量读取）
        self.admin_users = self._load_admin_users()
        
        # 用户会话缓存
        self.user_cache = {}
        
        self.logger.info("用户权限管理器初始化完成")
    
    def _load_admin_users(self) -> Set[int]:
        """加载管理员用户列表"""
        try:
            # 从环境变量或配置文件读取管理员用户ID
            admin_ids = getattr(self.settings, 'admin_user_ids', [])
            if isinstance(admin_ids, str):
                admin_ids = [int(id.strip()) for id in admin_ids.split(',') if id.strip()]
            
            return set(admin_ids)
            
        except Exception as e:
            self.logger.error(f"加载管理员用户列表失败: {e}")
            return set()
    
    async def check_user_permission(self, user_id: int, permission: str) -> bool:
        """
        检查用户权限
        
        Args:
            user_id: 用户ID
            permission: 权限名称
        
        Returns:
            bool: 是否有权限
        """
        try:
            # 获取用户角色
            role = await self.get_user_role(user_id)
            
            # 检查权限
            user_permissions = self.role_permissions.get(role, set())
            return permission in user_permissions
            
        except Exception as e:
            self.logger.error(f"检查用户权限失败: {e}")
            return False
    
    async def get_user_role(self, user_id: int) -> UserRole:
        """
        获取用户角色
        
        Args:
            user_id: 用户ID
        
        Returns:
            UserRole: 用户角色
        """
        try:
            # 检查缓存
            if user_id in self.user_cache:
                cache_entry = self.user_cache[user_id]
                # 缓存5分钟
                if (datetime.utcnow() - cache_entry["timestamp"]).seconds < 300:
                    return cache_entry["role"]
            
            # 检查是否为管理员
            if user_id in self.admin_users:
                role = UserRole.ADMIN
            else:
                # 从数据库获取用户角色（如果有用户表的话）
                # 目前简化为默认操作员权限
                role = UserRole.OPERATOR
            
            # 更新缓存
            self.user_cache[user_id] = {
                "role": role,
                "timestamp": datetime.utcnow()
            }
            
            return role
            
        except Exception as e:
            self.logger.error(f"获取用户角色失败: {e}")
            return UserRole.VIEWER  # 默认最低权限
    
    async def is_user_authorized(self, user_id: int) -> bool:
        """
        检查用户是否被授权使用机器人
        
        Args:
            user_id: 用户ID
        
        Returns:
            bool: 是否被授权
        """
        try:
            role = await self.get_user_role(user_id)
            return role != UserRole.BANNED
            
        except Exception as e:
            self.logger.error(f"检查用户授权失败: {e}")
            return False
    
    async def add_admin_user(self, user_id: int) -> bool:
        """
        添加管理员用户
        
        Args:
            user_id: 用户ID
        
        Returns:
            bool: 是否添加成功
        """
        try:
            self.admin_users.add(user_id)
            
            # 清除缓存
            if user_id in self.user_cache:
                del self.user_cache[user_id]
            
            self.logger.info(f"添加管理员用户: {user_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"添加管理员用户失败: {e}")
            return False
    
    async def remove_admin_user(self, user_id: int) -> bool:
        """
        移除管理员用户
        
        Args:
            user_id: 用户ID
        
        Returns:
            bool: 是否移除成功
        """
        try:
            self.admin_users.discard(user_id)
            
            # 清除缓存
            if user_id in self.user_cache:
                del self.user_cache[user_id]
            
            self.logger.info(f"移除管理员用户: {user_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"移除管理员用户失败: {e}")
            return False
    
    async def ban_user(self, user_id: int) -> bool:
        """
        禁用用户
        
        Args:
            user_id: 用户ID
        
        Returns:
            bool: 是否禁用成功
        """
        try:
            # 更新缓存为禁用状态
            self.user_cache[user_id] = {
                "role": UserRole.BANNED,
                "timestamp": datetime.utcnow()
            }
            
            self.logger.info(f"禁用用户: {user_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"禁用用户失败: {e}")
            return False
    
    async def get_user_stats(self) -> Dict[str, Any]:
        """
        获取用户统计信息
        
        Returns:
            Dict: 用户统计
        """
        try:
            # 统计各角色用户数量
            role_counts = {}
            for role in UserRole:
                role_counts[role.value] = 0
            
            # 统计缓存中的用户
            for user_info in self.user_cache.values():
                role = user_info["role"]
                role_counts[role.value] += 1
            
            # 管理员数量
            role_counts[UserRole.ADMIN.value] = len(self.admin_users)
            
            return {
                "total_users": len(self.user_cache),
                "admin_users": len(self.admin_users),
                "role_distribution": role_counts,
                "cache_size": len(self.user_cache)
            }
            
        except Exception as e:
            self.logger.error(f"获取用户统计失败: {e}")
            return {"error": str(e)}
    
    def get_permission_description(self, permission: str) -> str:
        """
        获取权限描述
        
        Args:
            permission: 权限名称
        
        Returns:
            str: 权限描述
        """
        descriptions = {
            "can_add_channel": "添加监控频道",
            "can_remove_channel": "移除监控频道",
            "can_manage_settings": "管理系统设置",
            "can_manage_users": "管理用户权限",
            "can_view_stats": "查看统计信息",
            "can_search": "搜索文件和消息",
            "can_manage_storage": "管理存储空间",
            "can_manage_downloads": "管理下载队列",
            "can_manage_dedup": "管理去重检测",
            "can_manage_tags": "管理标签系统"
        }
        
        return descriptions.get(permission, permission)
    
    async def log_user_action(self, user_id: int, action: str, details: str = ""):
        """
        记录用户操作日志
        
        Args:
            user_id: 用户ID
            action: 操作类型
            details: 操作详情
        """
        try:
            role = await self.get_user_role(user_id)
            self.logger.info(
                f"用户操作 - ID: {user_id}, 角色: {role.value}, "
                f"操作: {action}, 详情: {details}"
            )
            
        except Exception as e:
            self.logger.error(f"记录用户操作失败: {e}")
