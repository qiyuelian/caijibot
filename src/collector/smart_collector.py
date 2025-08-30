# -*- coding: utf-8 -*-
"""
智能采集器
集成预下载去重检测的消息采集器
"""

import asyncio
from typing import Dict, Any, List
from datetime import datetime

from telethon import TelegramClient

from ..database.database_manager import DatabaseManager
from ..database.models import Channel, Message, MediaType, MessageStatus
from ..config.settings import Settings
from ..deduplicator.dedup_manager import DeduplicationManager
from ..utils.logger import LoggerMixin
from .message_collector import MessageCollector


class SmartCollector(LoggerMixin):
    """智能采集器 - 带预下载去重检测"""
    
    def __init__(
        self, 
        db_manager: DatabaseManager, 
        telegram_client: TelegramClient, 
        settings: Settings,
        dedup_manager: DeduplicationManager
    ):
        """
        初始化智能采集器
        
        Args:
            db_manager: 数据库管理器
            telegram_client: Telegram客户端
            settings: 配置对象
            dedup_manager: 去重管理器
        """
        self.db_manager = db_manager
        self.client = telegram_client
        self.settings = settings
        self.dedup_manager = dedup_manager
        
        # 初始化基础消息采集器
        self.message_collector = MessageCollector(
            db_manager, 
            telegram_client, 
            settings, 
            dedup_manager
        )
        
        # 统计信息
        self.collection_stats = {
            "processed": 0,
            "downloaded": 0,
            "skipped_duplicates": 0,
            "needs_review": 0,
            "errors": 0
        }
        
        self.logger.info("智能采集器初始化完成")
    
    async def collect_channel_with_dedup(self, channel_id: str, limit: int = 100) -> Dict[str, Any]:
        """
        采集频道消息并进行预下载去重检测
        
        Args:
            channel_id: 频道ID
            limit: 采集数量限制
        
        Returns:
            Dict: 采集结果
        """
        try:
            # 获取频道信息
            async with self.db_manager.get_async_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Channel).where(Channel.channel_id == channel_id)
                )
                channel = result.scalar_one_or_none()
                
                if not channel:
                    return {"success": False, "error": "频道不存在"}
            
            # 获取频道实体
            entity = await self.client.get_entity(int(channel_id))
            
            self.logger.info(f"开始智能采集频道: {channel.channel_title}")
            
            # 重置统计
            self.collection_stats = {
                "processed": 0,
                "downloaded": 0,
                "skipped_duplicates": 0,
                "needs_review": 0,
                "errors": 0
            }
            
            # 获取最后处理的消息ID
            last_message_id = channel.last_message_id or 0
            
            # 采集新消息
            async for message in self.client.iter_messages(
                entity, 
                min_id=last_message_id,
                limit=limit
            ):
                try:
                    result = await self._process_message_with_dedup(message, channel)
                    self.collection_stats["processed"] += 1
                    
                    if result["action"] == "downloaded":
                        self.collection_stats["downloaded"] += 1
                    elif result["action"] == "skipped_duplicate":
                        self.collection_stats["skipped_duplicates"] += 1
                    elif result["action"] == "needs_review":
                        self.collection_stats["needs_review"] += 1
                    
                    # 更新最后处理的消息ID
                    if message.id > last_message_id:
                        last_message_id = message.id
                    
                    # 避免过度占用资源
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    self.collection_stats["errors"] += 1
                    self.logger.error(f"处理消息 {message.id} 失败: {e}")
            
            # 更新频道的最后检查时间
            await self._update_channel_last_check(channel.channel_id, last_message_id)
            
            self.logger.info(
                f"频道 {channel.channel_title} 智能采集完成: "
                f"处理 {self.collection_stats['processed']} 条, "
                f"下载 {self.collection_stats['downloaded']} 条, "
                f"跳过重复 {self.collection_stats['skipped_duplicates']} 条, "
                f"需要审核 {self.collection_stats['needs_review']} 条"
            )
            
            return {
                "success": True,
                "stats": self.collection_stats.copy(),
                "channel_name": channel.channel_title
            }
            
        except Exception as e:
            self.logger.error(f"智能采集频道失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _process_message_with_dedup(self, telegram_message, channel: Channel) -> Dict[str, Any]:
        """
        处理单条消息并进行去重检测
        
        Args:
            telegram_message: Telegram消息对象
            channel: 频道对象
        
        Returns:
            Dict: 处理结果
        """
        try:
            # 检查消息是否包含媒体
            if not telegram_message.media:
                return {"action": "skipped", "reason": "无媒体内容"}
            
            # 预下载去重检测
            dedup_result = await self.dedup_manager.check_duplicate_before_download(
                telegram_message, 
                channel.id
            )
            
            if dedup_result.get("is_duplicate"):
                # 发现重复，记录但不下载
                await self._record_duplicate_message(telegram_message, channel, dedup_result)
                return {
                    "action": "skipped_duplicate",
                    "reason": dedup_result.get("reason"),
                    "original_message_id": dedup_result.get("original_message_id")
                }
            
            elif dedup_result.get("needs_manual_review"):
                # 需要人工审核
                await self._record_review_needed_message(telegram_message, channel, dedup_result)
                return {
                    "action": "needs_review",
                    "reason": dedup_result.get("reason"),
                    "similarity_score": dedup_result.get("similarity_score")
                }
            
            else:
                # 正常处理消息（这里可以继续下载流程）
                success = await self.message_collector._process_message(telegram_message, channel)
                if success:
                    return {"action": "downloaded", "reason": "新文件，已添加到下载队列"}
                else:
                    return {"action": "failed", "reason": "处理失败"}
            
        except Exception as e:
            self.logger.error(f"处理消息失败: {e}")
            return {"action": "error", "reason": str(e)}
    
    async def _record_duplicate_message(
        self, 
        telegram_message, 
        channel: Channel, 
        dedup_result: Dict[str, Any]
    ):
        """记录重复消息"""
        try:
            # 提取文件信息
            file_info = self.message_collector._extract_file_info(telegram_message.media)
            if not file_info:
                return
            
            async with self.db_manager.get_async_session() as session:
                # 创建重复消息记录
                duplicate_message = Message(
                    message_id=telegram_message.id,
                    channel_id=channel.id,
                    message_text=telegram_message.text or "",
                    media_type=self.message_collector._get_media_type(telegram_message.media),
                    file_name=file_info["name"],
                    file_size=file_info["size"],
                    status=MessageStatus.DUPLICATE,
                    is_duplicate=True,
                    original_message_id=dedup_result.get("original_message_id"),
                    message_date=telegram_message.date
                )
                
                session.add(duplicate_message)
                await session.flush()
                
                # 创建去重记录
                from ..database.models import DuplicateRecord
                duplicate_record = DuplicateRecord(
                    original_message_id=dedup_result.get("original_message_id"),
                    duplicate_message_id=duplicate_message.id,
                    similarity_score=dedup_result.get("similarity_score", 1.0),
                    similarity_type=dedup_result.get("duplicate_type", "metadata"),
                    action_taken="skip_download",
                    reason=dedup_result.get("reason", "预下载检测发现重复")
                )
                
                session.add(duplicate_record)
                await session.commit()
                
        except Exception as e:
            self.logger.error(f"记录重复消息失败: {e}")
    
    async def _record_review_needed_message(
        self, 
        telegram_message, 
        channel: Channel, 
        dedup_result: Dict[str, Any]
    ):
        """记录需要审核的消息"""
        try:
            # 提取文件信息
            file_info = self.message_collector._extract_file_info(telegram_message.media)
            if not file_info:
                return
            
            async with self.db_manager.get_async_session() as session:
                # 创建消息记录，标记为需要审核
                review_message = Message(
                    message_id=telegram_message.id,
                    channel_id=channel.id,
                    message_text=telegram_message.text or "",
                    media_type=self.message_collector._get_media_type(telegram_message.media),
                    file_name=file_info["name"],
                    file_size=file_info["size"],
                    status=MessageStatus.PENDING,  # 暂时标记为待处理
                    message_date=telegram_message.date
                )
                
                # 在消息文本中添加审核标记
                review_info = {
                    "needs_manual_review": True,
                    "similarity_score": dedup_result.get("similarity_score"),
                    "original_message_id": dedup_result.get("original_message_id"),
                    "reason": dedup_result.get("reason")
                }
                
                review_message.message_text += f"\n[REVIEW_NEEDED: {review_info}]"
                
                session.add(review_message)
                await session.commit()
                
                self.logger.warning(
                    f"消息 {telegram_message.id} 需要人工审核: "
                    f"相似度 {dedup_result.get('similarity_score', 0):.1%}"
                )
                
        except Exception as e:
            self.logger.error(f"记录审核消息失败: {e}")
    
    async def _update_channel_last_check(self, channel_id: str, last_message_id: int):
        """更新频道最后检查时间"""
        try:
            async with self.db_manager.get_async_session() as session:
                from sqlalchemy import update
                await session.execute(
                    update(Channel)
                    .where(Channel.channel_id == channel_id)
                    .values(
                        last_message_id=last_message_id,
                        last_check_time=datetime.utcnow()
                    )
                )
                await session.commit()
        except Exception as e:
            self.logger.error(f"更新频道检查时间失败: {e}")
    
    async def get_review_needed_messages(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取需要人工审核的消息列表
        
        Args:
            limit: 限制数量
        
        Returns:
            List[Dict]: 需要审核的消息列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Message)
                    .where(Message.message_text.like("%[REVIEW_NEEDED:%"))
                    .limit(limit)
                    .order_by(Message.created_at.desc())
                )
                
                messages = result.scalars().all()
                
                review_list = []
                for msg in messages:
                    # 解析审核信息
                    import re
                    review_match = re.search(r'\[REVIEW_NEEDED: (.+)\]', msg.message_text)
                    review_info = {}
                    if review_match:
                        try:
                            review_info = eval(review_match.group(1))
                        except:
                            pass
                    
                    review_list.append({
                        "message_id": msg.id,
                        "telegram_message_id": msg.message_id,
                        "file_name": msg.file_name,
                        "file_size": msg.file_size,
                        "media_type": msg.media_type,
                        "similarity_score": review_info.get("similarity_score", 0),
                        "reason": review_info.get("reason", ""),
                        "created_at": msg.created_at.isoformat()
                    })
                
                return review_list
                
        except Exception as e:
            self.logger.error(f"获取审核消息列表失败: {e}")
            return []
