# -*- coding: utf-8 -*-
"""
标签管理器
负责标签的创建、更新、删除和查询
"""

import random
from typing import List, Dict, Any, Optional
from datetime import datetime

from sqlalchemy import select, update, delete, func
from sqlalchemy.exc import IntegrityError

from ..database.database_manager import DatabaseManager
from ..database.models import Tag, MessageTag, ClassificationRule
from ..utils.logger import LoggerMixin


class TagManager(LoggerMixin):
    """标签管理器"""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        初始化标签管理器
        
        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        
        # 预定义颜色列表
        self.default_colors = [
            "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
            "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9",
            "#F8C471", "#82E0AA", "#F1948A", "#85C1E9", "#D7BDE2"
        ]
        
        self.logger.info("标签管理器初始化完成")
    
    async def create_tag(
        self, 
        name: str, 
        description: str = None, 
        color: str = None
    ) -> Optional[Tag]:
        """
        创建新标签
        
        Args:
            name: 标签名称
            description: 标签描述
            color: 标签颜色（HEX格式）
        
        Returns:
            Optional[Tag]: 创建的标签对象
        """
        try:
            # 如果没有指定颜色，随机选择一个
            if not color:
                color = random.choice(self.default_colors)
            
            async with self.db_manager.get_async_session() as session:
                new_tag = Tag(
                    name=name.strip(),
                    description=description.strip() if description else None,
                    color=color
                )
                
                session.add(new_tag)
                await session.commit()
                
                self.logger.info(f"创建新标签: {name}")
                return new_tag
                
        except IntegrityError:
            self.logger.warning(f"标签名称已存在: {name}")
            return None
        except Exception as e:
            self.logger.error(f"创建标签失败: {e}")
            return None
    
    async def get_tag(self, tag_id: int) -> Optional[Tag]:
        """
        根据ID获取标签
        
        Args:
            tag_id: 标签ID
        
        Returns:
            Optional[Tag]: 标签对象
        """
        try:
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Tag).where(Tag.id == tag_id)
                )
                return result.scalar_one_or_none()
                
        except Exception as e:
            self.logger.error(f"获取标签失败: {e}")
            return None
    
    async def get_tag_by_name(self, name: str) -> Optional[Tag]:
        """
        根据名称获取标签
        
        Args:
            name: 标签名称
        
        Returns:
            Optional[Tag]: 标签对象
        """
        try:
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Tag).where(Tag.name == name.strip())
                )
                return result.scalar_one_or_none()
                
        except Exception as e:
            self.logger.error(f"根据名称获取标签失败: {e}")
            return None
    
    async def update_tag(
        self, 
        tag_id: int, 
        name: str = None, 
        description: str = None, 
        color: str = None
    ) -> bool:
        """
        更新标签信息
        
        Args:
            tag_id: 标签ID
            name: 新名称
            description: 新描述
            color: 新颜色
        
        Returns:
            bool: 是否更新成功
        """
        try:
            update_data = {"updated_at": datetime.utcnow()}
            
            if name is not None:
                update_data["name"] = name.strip()
            if description is not None:
                update_data["description"] = description.strip() if description else None
            if color is not None:
                update_data["color"] = color
            
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    update(Tag)
                    .where(Tag.id == tag_id)
                    .values(**update_data)
                )
                
                await session.commit()
                
                if result.rowcount > 0:
                    self.logger.info(f"更新标签 {tag_id}")
                    return True
                else:
                    self.logger.warning(f"标签 {tag_id} 不存在")
                    return False
                    
        except IntegrityError:
            self.logger.warning(f"标签名称已存在: {name}")
            return False
        except Exception as e:
            self.logger.error(f"更新标签失败: {e}")
            return False
    
    async def delete_tag(self, tag_id: int, force: bool = False) -> Dict[str, Any]:
        """
        删除标签
        
        Args:
            tag_id: 标签ID
            force: 是否强制删除（即使有关联数据）
        
        Returns:
            Dict: 删除结果
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 检查标签是否存在
                tag = await session.execute(
                    select(Tag).where(Tag.id == tag_id)
                )
                tag = tag.scalar_one_or_none()
                
                if not tag:
                    return {"success": False, "error": "标签不存在"}
                
                # 检查是否有关联的消息标签
                message_tags_count = await session.execute(
                    select(func.count(MessageTag.id)).where(MessageTag.tag_id == tag_id)
                )
                message_tags_count = message_tags_count.scalar()
                
                # 检查是否有关联的分类规则
                rules_count = await session.execute(
                    select(func.count(ClassificationRule.id)).where(ClassificationRule.tag_id == tag_id)
                )
                rules_count = rules_count.scalar()
                
                if (message_tags_count > 0 or rules_count > 0) and not force:
                    return {
                        "success": False,
                        "error": "标签有关联数据，无法删除",
                        "message_tags": message_tags_count,
                        "rules": rules_count
                    }
                
                # 如果强制删除，先删除关联数据
                if force:
                    # 删除消息标签关联
                    await session.execute(
                        delete(MessageTag).where(MessageTag.tag_id == tag_id)
                    )
                    
                    # 删除分类规则
                    await session.execute(
                        delete(ClassificationRule).where(ClassificationRule.tag_id == tag_id)
                    )
                
                # 删除标签
                await session.execute(
                    delete(Tag).where(Tag.id == tag_id)
                )
                
                await session.commit()
                
                self.logger.info(f"删除标签 {tag.name} (ID: {tag_id})")
                
                return {
                    "success": True,
                    "deleted_message_tags": message_tags_count if force else 0,
                    "deleted_rules": rules_count if force else 0
                }
                
        except Exception as e:
            self.logger.error(f"删除标签失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def list_tags(
        self, 
        limit: int = None, 
        offset: int = 0,
        order_by: str = "usage_count"
    ) -> List[Dict[str, Any]]:
        """
        获取标签列表
        
        Args:
            limit: 限制数量
            offset: 偏移量
            order_by: 排序字段 (name, usage_count, created_at)
        
        Returns:
            List[Dict]: 标签信息列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                query = select(Tag)
                
                # 排序
                if order_by == "name":
                    query = query.order_by(Tag.name)
                elif order_by == "created_at":
                    query = query.order_by(Tag.created_at.desc())
                else:  # usage_count
                    query = query.order_by(Tag.usage_count.desc())
                
                # 分页
                if offset > 0:
                    query = query.offset(offset)
                if limit:
                    query = query.limit(limit)
                
                result = await session.execute(query)
                tags = result.scalars().all()
                
                # 格式化标签信息
                tags_info = []
                for tag in tags:
                    tags_info.append({
                        "id": tag.id,
                        "name": tag.name,
                        "description": tag.description,
                        "color": tag.color,
                        "usage_count": tag.usage_count,
                        "created_at": tag.created_at.isoformat(),
                        "updated_at": tag.updated_at.isoformat()
                    })
                
                return tags_info
                
        except Exception as e:
            self.logger.error(f"获取标签列表失败: {e}")
            return []
    
    async def search_tags(self, keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        搜索标签
        
        Args:
            keyword: 搜索关键词
            limit: 限制数量
        
        Returns:
            List[Dict]: 匹配的标签列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Tag)
                    .where(
                        Tag.name.ilike(f"%{keyword}%") |
                        Tag.description.ilike(f"%{keyword}%")
                    )
                    .order_by(Tag.usage_count.desc())
                    .limit(limit)
                )
                
                tags = result.scalars().all()
                
                tags_info = []
                for tag in tags:
                    tags_info.append({
                        "id": tag.id,
                        "name": tag.name,
                        "description": tag.description,
                        "color": tag.color,
                        "usage_count": tag.usage_count
                    })
                
                return tags_info
                
        except Exception as e:
            self.logger.error(f"搜索标签失败: {e}")
            return []
    
    async def get_tag_stats(self) -> Dict[str, Any]:
        """
        获取标签统计信息
        
        Returns:
            Dict: 统计信息
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 总标签数
                total_tags = await session.execute(select(func.count(Tag.id)))
                total_tags = total_tags.scalar()
                
                # 使用中的标签数
                used_tags = await session.execute(
                    select(func.count(Tag.id)).where(Tag.usage_count > 0)
                )
                used_tags = used_tags.scalar()
                
                # 最常用的标签
                popular_tags = await session.execute(
                    select(Tag)
                    .where(Tag.usage_count > 0)
                    .order_by(Tag.usage_count.desc())
                    .limit(10)
                )
                popular_tags = popular_tags.scalars().all()
                
                # 最近创建的标签
                recent_tags = await session.execute(
                    select(Tag)
                    .order_by(Tag.created_at.desc())
                    .limit(5)
                )
                recent_tags = recent_tags.scalars().all()
                
                return {
                    "total_tags": total_tags,
                    "used_tags": used_tags,
                    "unused_tags": total_tags - used_tags,
                    "popular_tags": [
                        {
                            "id": tag.id,
                            "name": tag.name,
                            "usage_count": tag.usage_count,
                            "color": tag.color
                        }
                        for tag in popular_tags
                    ],
                    "recent_tags": [
                        {
                            "id": tag.id,
                            "name": tag.name,
                            "created_at": tag.created_at.isoformat(),
                            "color": tag.color
                        }
                        for tag in recent_tags
                    ]
                }
                
        except Exception as e:
            self.logger.error(f"获取标签统计失败: {e}")
            return {"error": str(e)}
    
    async def merge_tags(self, source_tag_id: int, target_tag_id: int) -> Dict[str, Any]:
        """
        合并标签（将源标签的所有关联转移到目标标签）
        
        Args:
            source_tag_id: 源标签ID
            target_tag_id: 目标标签ID
        
        Returns:
            Dict: 合并结果
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 检查两个标签是否存在
                source_tag = await session.execute(
                    select(Tag).where(Tag.id == source_tag_id)
                )
                source_tag = source_tag.scalar_one_or_none()
                
                target_tag = await session.execute(
                    select(Tag).where(Tag.id == target_tag_id)
                )
                target_tag = target_tag.scalar_one_or_none()
                
                if not source_tag or not target_tag:
                    return {"success": False, "error": "标签不存在"}
                
                if source_tag_id == target_tag_id:
                    return {"success": False, "error": "不能合并相同的标签"}
                
                # 更新消息标签关联
                message_tags_updated = await session.execute(
                    update(MessageTag)
                    .where(MessageTag.tag_id == source_tag_id)
                    .values(tag_id=target_tag_id)
                )
                
                # 更新分类规则
                rules_updated = await session.execute(
                    update(ClassificationRule)
                    .where(ClassificationRule.tag_id == source_tag_id)
                    .values(tag_id=target_tag_id)
                )
                
                # 更新目标标签的使用统计
                await session.execute(
                    update(Tag)
                    .where(Tag.id == target_tag_id)
                    .values(usage_count=Tag.usage_count + source_tag.usage_count)
                )
                
                # 删除源标签
                await session.execute(
                    delete(Tag).where(Tag.id == source_tag_id)
                )
                
                await session.commit()
                
                self.logger.info(f"合并标签: {source_tag.name} -> {target_tag.name}")
                
                return {
                    "success": True,
                    "source_tag": source_tag.name,
                    "target_tag": target_tag.name,
                    "message_tags_updated": message_tags_updated.rowcount,
                    "rules_updated": rules_updated.rowcount
                }
                
        except Exception as e:
            self.logger.error(f"合并标签失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_or_create_tag(self, name: str, description: str = None, color: str = None) -> Tag:
        """
        获取或创建标签
        
        Args:
            name: 标签名称
            description: 标签描述
            color: 标签颜色
        
        Returns:
            Tag: 标签对象
        """
        # 先尝试获取现有标签
        existing_tag = await self.get_tag_by_name(name)
        if existing_tag:
            return existing_tag
        
        # 如果不存在，创建新标签
        new_tag = await self.create_tag(name, description, color)
        return new_tag
