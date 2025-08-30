# -*- coding: utf-8 -*-
"""
自动分类器
负责对消息进行自动分类和标签管理
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload

from ..database.database_manager import DatabaseManager
from ..database.models import Message, MessageTag, Tag, MessageStatus
from ..config.settings import Settings
from ..utils.logger import LoggerMixin
from .rule_engine import RuleEngine


class AutoClassifier(LoggerMixin):
    """自动分类器"""
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        初始化自动分类器
        
        Args:
            db_manager: 数据库管理器
            settings: 配置对象
        """
        self.db_manager = db_manager
        self.settings = settings
        self.rule_engine = RuleEngine(db_manager)
        
        # 分类状态
        self.is_classifying = False
        self.classification_stats = {
            "processed": 0,
            "classified": 0,
            "errors": 0
        }
        
        self.logger.info("自动分类器初始化完成")
    
    async def start_auto_classification(self):
        """开始自动分类处理"""
        if self.is_classifying:
            self.logger.warning("自动分类器已在运行中")
            return
        
        if not self.settings.auto_classification:
            self.logger.info("自动分类功能已禁用")
            return
        
        self.is_classifying = True
        self.logger.info("开始自动分类处理")
        
        try:
            while self.is_classifying:
                # 获取待分类的消息
                pending_messages = await self._get_pending_messages()
                
                if pending_messages:
                    self.logger.info(f"找到 {len(pending_messages)} 条待分类消息")
                    
                    # 批量处理消息
                    for message in pending_messages:
                        if not self.is_classifying:
                            break
                        
                        await self._classify_single_message(message)
                        self.classification_stats["processed"] += 1
                        
                        # 避免过度占用资源
                        await asyncio.sleep(0.1)
                
                # 等待下一轮处理
                await asyncio.sleep(30)  # 每30秒检查一次
                
        except Exception as e:
            self.logger.error(f"自动分类处理出错: {e}")
        finally:
            self.is_classifying = False
    
    async def stop_auto_classification(self):
        """停止自动分类处理"""
        self.is_classifying = False
        self.logger.info("停止自动分类处理")
    
    async def classify_message(self, message_id: int) -> Dict[str, Any]:
        """
        对单条消息进行分类
        
        Args:
            message_id: 消息ID
        
        Returns:
            Dict: 分类结果
        """
        try:
            # 获取消息
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Message).where(Message.id == message_id)
                )
                message = result.scalar_one_or_none()
                
                if not message:
                    return {"success": False, "error": "消息不存在"}
            
            # 执行分类
            classification_result = await self._classify_single_message(message)
            
            return {
                "success": True,
                "message_id": message_id,
                "tags_added": len(classification_result.get("tags", [])),
                "tags": classification_result.get("tags", [])
            }
            
        except Exception as e:
            self.logger.error(f"分类消息失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def classify_batch(self, message_ids: List[int]) -> Dict[str, Any]:
        """
        批量分类消息
        
        Args:
            message_ids: 消息ID列表
        
        Returns:
            Dict: 批量分类结果
        """
        results = {
            "total": len(message_ids),
            "success": 0,
            "failed": 0,
            "details": []
        }
        
        for message_id in message_ids:
            result = await self.classify_message(message_id)
            if result["success"]:
                results["success"] += 1
            else:
                results["failed"] += 1
            
            results["details"].append({
                "message_id": message_id,
                "success": result["success"],
                "tags_added": result.get("tags_added", 0)
            })
        
        self.logger.info(f"批量分类完成: {results['success']}/{results['total']} 成功")
        return results
    
    async def _classify_single_message(self, message: Message) -> Dict[str, Any]:
        """
        对单条消息执行分类
        
        Args:
            message: 消息对象
        
        Returns:
            Dict: 分类结果
        """
        try:
            # 使用规则引擎进行分类
            matched_tags = await self.rule_engine.classify_message(message)
            
            if not matched_tags:
                # 没有匹配的标签，使用默认标签
                await self._apply_default_tags(message)
                return {"tags": [], "default_applied": True}
            
            # 应用匹配的标签
            applied_tags = []
            for tag, confidence in matched_tags:
                success = await self._apply_tag_to_message(
                    message.id, 
                    tag.id, 
                    confidence, 
                    is_auto_classified=True
                )
                if success:
                    applied_tags.append({
                        "tag_id": tag.id,
                        "tag_name": tag.name,
                        "confidence": confidence
                    })
            
            self.classification_stats["classified"] += 1
            
            self.logger.debug(f"消息 {message.id} 分类完成，应用了 {len(applied_tags)} 个标签")
            
            return {"tags": applied_tags, "default_applied": False}
            
        except Exception as e:
            self.logger.error(f"分类消息 {message.id} 失败: {e}")
            self.classification_stats["errors"] += 1
            return {"tags": [], "error": str(e)}
    
    async def _apply_tag_to_message(
        self, 
        message_id: int, 
        tag_id: int, 
        confidence: float = 1.0,
        is_auto_classified: bool = True,
        classified_by: str = "system"
    ) -> bool:
        """
        为消息应用标签
        
        Args:
            message_id: 消息ID
            tag_id: 标签ID
            confidence: 置信度
            is_auto_classified: 是否自动分类
            classified_by: 分类者
        
        Returns:
            bool: 是否成功应用
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 检查标签是否已存在
                existing = await session.execute(
                    select(MessageTag).where(
                        MessageTag.message_id == message_id,
                        MessageTag.tag_id == tag_id
                    )
                )
                
                if existing.scalar_one_or_none():
                    return False  # 标签已存在
                
                # 创建新的消息标签关联
                message_tag = MessageTag(
                    message_id=message_id,
                    tag_id=tag_id,
                    confidence=confidence,
                    is_auto_classified=is_auto_classified,
                    classified_by=classified_by
                )
                
                session.add(message_tag)
                
                # 更新标签使用统计
                await session.execute(
                    update(Tag)
                    .where(Tag.id == tag_id)
                    .values(usage_count=Tag.usage_count + 1)
                )
                
                await session.commit()
                return True
                
        except Exception as e:
            self.logger.error(f"应用标签失败: {e}")
            return False
    
    async def _apply_default_tags(self, message: Message) -> bool:
        """
        应用默认标签
        
        Args:
            message: 消息对象
        
        Returns:
            bool: 是否成功应用
        """
        try:
            # 获取或创建默认标签
            default_tag = await self._get_or_create_default_tag()
            if not default_tag:
                return False
            
            # 应用默认标签
            return await self._apply_tag_to_message(
                message.id,
                default_tag.id,
                confidence=1.0,
                is_auto_classified=True,
                classified_by="default"
            )
            
        except Exception as e:
            self.logger.error(f"应用默认标签失败: {e}")
            return False
    
    async def _get_or_create_default_tag(self) -> Optional[Tag]:
        """
        获取或创建默认标签
        
        Returns:
            Optional[Tag]: 默认标签对象
        """
        try:
            default_tag_names = self.settings.default_tags
            if not default_tag_names:
                default_tag_names = ["未分类"]
            
            async with self.db_manager.get_async_session() as session:
                # 尝试获取第一个默认标签
                for tag_name in default_tag_names:
                    result = await session.execute(
                        select(Tag).where(Tag.name == tag_name)
                    )
                    tag = result.scalar_one_or_none()
                    
                    if tag:
                        return tag
                
                # 如果不存在，创建第一个默认标签
                default_tag = Tag(
                    name=default_tag_names[0],
                    description="系统默认标签",
                    color="#808080"  # 灰色
                )
                
                session.add(default_tag)
                await session.commit()
                
                self.logger.info(f"创建默认标签: {default_tag_names[0]}")
                return default_tag
                
        except Exception as e:
            self.logger.error(f"获取或创建默认标签失败: {e}")
            return None
    
    async def _get_pending_messages(self, limit: int = 100) -> List[Message]:
        """
        获取待分类的消息
        
        Args:
            limit: 限制数量
        
        Returns:
            List[Message]: 待分类消息列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 查找已完成但未分类的消息
                result = await session.execute(
                    select(Message)
                    .where(
                        Message.status == MessageStatus.COMPLETED,
                        ~Message.tags.any()  # 没有标签的消息
                    )
                    .limit(limit)
                    .order_by(Message.created_at.asc())
                )
                
                return result.scalars().all()
                
        except Exception as e:
            self.logger.error(f"获取待分类消息失败: {e}")
            return []
    
    async def remove_message_tag(self, message_id: int, tag_id: int) -> bool:
        """
        移除消息标签
        
        Args:
            message_id: 消息ID
            tag_id: 标签ID
        
        Returns:
            bool: 是否成功移除
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 删除消息标签关联
                await session.execute(
                    delete(MessageTag).where(
                        MessageTag.message_id == message_id,
                        MessageTag.tag_id == tag_id
                    )
                )
                
                # 更新标签使用统计
                await session.execute(
                    update(Tag)
                    .where(Tag.id == tag_id)
                    .values(usage_count=Tag.usage_count - 1)
                )
                
                await session.commit()
                
                self.logger.info(f"移除消息 {message_id} 的标签 {tag_id}")
                return True
                
        except Exception as e:
            self.logger.error(f"移除消息标签失败: {e}")
            return False
    
    async def get_message_tags(self, message_id: int) -> List[Dict[str, Any]]:
        """
        获取消息的所有标签
        
        Args:
            message_id: 消息ID
        
        Returns:
            List[Dict]: 标签信息列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(MessageTag)
                    .options(selectinload(MessageTag.tag))
                    .where(MessageTag.message_id == message_id)
                    .order_by(MessageTag.confidence.desc())
                )
                
                message_tags = result.scalars().all()
                
                tags_info = []
                for mt in message_tags:
                    tags_info.append({
                        "tag_id": mt.tag.id,
                        "tag_name": mt.tag.name,
                        "tag_color": mt.tag.color,
                        "confidence": mt.confidence,
                        "is_auto_classified": mt.is_auto_classified,
                        "classified_by": mt.classified_by,
                        "created_at": mt.created_at.isoformat()
                    })
                
                return tags_info
                
        except Exception as e:
            self.logger.error(f"获取消息标签失败: {e}")
            return []
    
    async def get_classification_stats(self) -> Dict[str, Any]:
        """
        获取分类统计信息
        
        Returns:
            Dict: 统计信息
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 获取总消息数
                total_messages = await session.execute(
                    select(Message).where(Message.status == MessageStatus.COMPLETED)
                )
                total_count = len(total_messages.scalars().all())
                
                # 获取已分类消息数
                classified_messages = await session.execute(
                    select(Message)
                    .where(
                        Message.status == MessageStatus.COMPLETED,
                        Message.tags.any()
                    )
                )
                classified_count = len(classified_messages.scalars().all())
                
                # 获取自动分类数
                auto_classified = await session.execute(
                    select(MessageTag).where(MessageTag.is_auto_classified == True)
                )
                auto_count = len(auto_classified.scalars().all())
                
                return {
                    "total_messages": total_count,
                    "classified_messages": classified_count,
                    "auto_classified": auto_count,
                    "manual_classified": classified_count - auto_count,
                    "classification_rate": classified_count / total_count if total_count > 0 else 0,
                    "runtime_stats": self.classification_stats.copy(),
                    "is_running": self.is_classifying
                }
                
        except Exception as e:
            self.logger.error(f"获取分类统计失败: {e}")
            return {
                "error": str(e),
                "runtime_stats": self.classification_stats.copy(),
                "is_running": self.is_classifying
            }
