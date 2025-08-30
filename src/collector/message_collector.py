# -*- coding: utf-8 -*-
"""
消息采集器
负责从Telegram频道采集消息和媒体文件
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, AsyncGenerator

from telethon import TelegramClient
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument, 
    DocumentAttributeVideo, DocumentAttributeFilename
)
from telethon.errors import FloodWaitError, ChannelPrivateError
from sqlalchemy import select, update

from ..database.database_manager import DatabaseManager
from ..database.models import Channel, Message, MediaType, MessageStatus, ChannelStatus
from ..config.settings import Settings
from ..utils.logger import LoggerMixin


class MessageCollector(LoggerMixin):
    """消息采集器"""
    
    def __init__(self, db_manager: DatabaseManager, telegram_client: TelegramClient, settings: Settings, dedup_manager=None, download_manager=None):
        """
        初始化消息采集器

        Args:
            db_manager: 数据库管理器
            telegram_client: Telegram客户端
            settings: 配置对象
            dedup_manager: 去重管理器（可选）
            download_manager: 下载管理器（可选）
        """
        self.db_manager = db_manager
        self.client = telegram_client
        self.settings = settings
        self.dedup_manager = dedup_manager
        self.download_manager = download_manager

        # 采集状态
        self.is_collecting = False
        self.collection_tasks = {}

        self.logger.info("消息采集器初始化完成")
    
    async def start_collection(self):
        """开始采集所有活跃频道的消息"""
        if self.is_collecting:
            self.logger.warning("采集器已在运行中")
            return
        
        self.is_collecting = True
        self.logger.info("开始消息采集")
        
        try:
            while self.is_collecting:
                # 获取活跃频道列表
                active_channels = await self._get_active_channels()
                
                # 为每个频道创建采集任务
                for channel in active_channels:
                    if channel.channel_id not in self.collection_tasks:
                        task = asyncio.create_task(
                            self._collect_channel_messages(channel)
                        )
                        self.collection_tasks[channel.channel_id] = task
                
                # 清理已完成的任务
                completed_tasks = [
                    channel_id for channel_id, task in self.collection_tasks.items()
                    if task.done()
                ]
                for channel_id in completed_tasks:
                    del self.collection_tasks[channel_id]
                
                # 等待下一次检查
                await asyncio.sleep(self.settings.collection_interval_seconds)
                
        except Exception as e:
            self.logger.error(f"采集过程中出错: {e}")
        finally:
            self.is_collecting = False
            # 取消所有采集任务
            for task in self.collection_tasks.values():
                task.cancel()
            self.collection_tasks.clear()
    
    async def stop_collection(self):
        """停止消息采集"""
        self.is_collecting = False
        self.logger.info("停止消息采集")
    
    async def collect_channel_history(self, channel_id: str, days: int = None) -> Dict[str, Any]:
        """
        采集频道历史消息
        
        Args:
            channel_id: 频道ID
            days: 采集天数，None表示采集所有历史消息
        
        Returns:
            Dict: 采集结果
        """
        try:
            # 获取频道信息
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Channel).where(Channel.channel_id == channel_id)
                )
                channel = result.scalar_one_or_none()
                
                if not channel:
                    return {"success": False, "error": "频道不存在"}
            
            # 计算时间范围
            offset_date = None
            if days:
                offset_date = datetime.utcnow() - timedelta(days=days)
            
            self.logger.info(f"开始采集频道 {channel.channel_title} 的历史消息")
            
            # 采集消息
            collected_count = 0
            processed_count = 0
            
            async for message in self._iterate_channel_messages(channel, offset_date):
                collected_count += 1
                
                # 处理消息
                if await self._process_message(message, channel):
                    processed_count += 1
                
                # 每处理100条消息更新一次进度
                if collected_count % 100 == 0:
                    self.logger.info(f"已采集 {collected_count} 条消息，处理 {processed_count} 条")
            
            # 更新频道统计
            await self._update_channel_stats(channel.channel_id, collected_count)
            
            self.logger.info(f"频道 {channel.channel_title} 历史消息采集完成: {collected_count}/{processed_count}")
            
            return {
                "success": True,
                "collected": collected_count,
                "processed": processed_count
            }
            
        except Exception as e:
            self.logger.error(f"采集频道历史消息失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _collect_channel_messages(self, channel: Channel):
        """
        采集单个频道的新消息
        
        Args:
            channel: 频道对象
        """
        try:
            self.logger.debug(f"开始采集频道 {channel.channel_title} 的新消息")
            
            # 获取频道实体
            entity = await self.client.get_entity(int(channel.channel_id))
            
            # 获取最后处理的消息ID
            last_message_id = channel.last_message_id or 0
            
            # 获取新消息
            new_messages = []
            async for message in self.client.iter_messages(
                entity, 
                min_id=last_message_id,
                limit=100  # 每次最多处理100条新消息
            ):
                new_messages.append(message)
            
            # 按时间顺序处理消息（从旧到新）
            new_messages.reverse()
            
            processed_count = 0
            for message in new_messages:
                if await self._process_message(message, channel):
                    processed_count += 1
                
                # 更新最后处理的消息ID
                if message.id > last_message_id:
                    last_message_id = message.id
            
            # 更新频道的最后检查时间和消息ID
            if new_messages:
                await self._update_channel_last_check(channel.channel_id, last_message_id)
                self.logger.info(f"频道 {channel.channel_title} 处理了 {processed_count} 条新消息")
            
        except ChannelPrivateError:
            self.logger.warning(f"频道 {channel.channel_title} 已私有或无访问权限")
            await self._update_channel_status(channel.channel_id, ChannelStatus.ERROR)
        except FloodWaitError as e:
            self.logger.warning(f"请求过于频繁，等待 {e.seconds} 秒")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            self.logger.error(f"采集频道 {channel.channel_title} 消息失败: {e}")
    
    async def _iterate_channel_messages(
        self, 
        channel: Channel, 
        offset_date: Optional[datetime] = None
    ) -> AsyncGenerator[Any, None]:
        """
        迭代频道消息
        
        Args:
            channel: 频道对象
            offset_date: 起始日期
        
        Yields:
            消息对象
        """
        try:
            entity = await self.client.get_entity(int(channel.channel_id))
            
            async for message in self.client.iter_messages(
                entity,
                offset_date=offset_date,
                reverse=True  # 从旧到新
            ):
                yield message
                
        except Exception as e:
            self.logger.error(f"迭代频道消息失败: {e}")
    
    async def _process_message(self, message, channel: Channel) -> bool:
        """
        处理单条消息

        Args:
            message: Telegram消息对象
            channel: 频道对象

        Returns:
            bool: 是否成功处理
        """
        try:
            # 检查消息是否包含媒体
            if not message.media:
                return False

            # 确定媒体类型
            media_type = self._get_media_type(message.media)
            if not media_type:
                return False

            # 检查是否启用了该类型的采集
            if media_type == MediaType.VIDEO and not self.settings.enable_video_collection:
                return False
            if media_type == MediaType.IMAGE and not self.settings.enable_image_collection:
                return False

            # 获取文件信息
            file_info = self._extract_file_info(message.media)
            if not file_info:
                return False

            # 检查文件大小限制
            if file_info["size"] > self.settings.max_file_size_bytes:
                self.logger.debug(f"文件过大，跳过: {file_info['name']} ({file_info['size']} bytes)")
                return False

            # 检查消息是否已存在
            async with self.db_manager.get_async_session() as session:
                existing = await session.execute(
                    select(Message).where(
                        Message.message_id == message.id,
                        Message.channel_id == channel.id
                    )
                )
                if existing.scalar_one_or_none():
                    return False  # 消息已存在

                # 预下载去重检测
                should_download = True
                duplicate_info = None

                if self.dedup_manager:
                    dedup_result = await self.dedup_manager.check_duplicate_before_download(
                        message, channel.id
                    )

                    if dedup_result.get("is_duplicate"):
                        # 发现重复，不下载
                        should_download = False
                        duplicate_info = dedup_result
                        self.logger.info(
                            f"预下载检测发现重复文件: {file_info['name']}, "
                            f"原因: {dedup_result.get('reason')}"
                        )
                    elif dedup_result.get("needs_manual_review"):
                        # 需要人工审核，先下载但标记
                        should_download = True
                        self.logger.warning(
                            f"文件需要人工审核: {file_info['name']}, "
                            f"原因: {dedup_result.get('reason')}"
                        )

                # 创建消息记录
                new_message = Message(
                    message_id=message.id,
                    channel_id=channel.id,
                    message_text=message.text or "",
                    media_type=media_type,
                    file_name=file_info["name"],
                    file_size=file_info["size"],
                    status=MessageStatus.DUPLICATE if not should_download else MessageStatus.PENDING,
                    is_duplicate=not should_download,
                    original_message_id=duplicate_info.get("original_message_id") if duplicate_info else None,
                    message_date=message.date
                )

                session.add(new_message)
                await session.commit()

                # 如果发现重复，创建去重记录
                if duplicate_info and not should_download:
                    from ..database.models import DuplicateRecord
                    duplicate_record = DuplicateRecord(
                        original_message_id=duplicate_info.get("original_message_id"),
                        duplicate_message_id=new_message.id,
                        similarity_score=duplicate_info.get("similarity_score", 1.0),
                        similarity_type=duplicate_info.get("duplicate_type", "metadata"),
                        action_taken="skip_download",
                        reason=duplicate_info.get("reason", "预下载检测发现重复")
                    )
                    session.add(duplicate_record)
                    await session.commit()

                # 根据下载模式决定是否自动下载
                if should_download:
                    download_decision = await self._make_download_decision(new_message)

                    if download_decision["should_download"] and self.download_manager:
                        # 添加延迟以避免过于频繁的下载
                        if self.settings.auto_download_delay_seconds > 0:
                            await asyncio.sleep(self.settings.auto_download_delay_seconds)

                        # 加入下载队列
                        await self.download_manager.add_download_task(
                            new_message,
                            priority=download_decision.get("priority", 0)
                        )
                        action = f"已加入下载队列 ({download_decision['reason']})"
                    else:
                        action = f"等待手动下载 ({download_decision['reason']})"
                else:
                    action = "跳过下载（重复文件）"

                self.logger.debug(f"添加新消息: {file_info['name']} ({media_type}) - {action}")
                return True

        except Exception as e:
            self.logger.error(f"处理消息失败: {e}")
            return False

    async def _make_download_decision(self, message: Message) -> Dict[str, Any]:
        """
        做出下载决策

        Args:
            message: 消息对象

        Returns:
            Dict: 下载决策信息
        """
        try:
            mode = self.settings.auto_download_mode

            if mode == "manual":
                return {
                    "should_download": False,
                    "reason": "手动下载模式",
                    "priority": 0
                }

            elif mode == "auto":
                # 检查基本限制
                if message.file_size and message.file_size > self.settings.max_file_size_bytes:
                    return {
                        "should_download": False,
                        "reason": "文件超过最大大小限制",
                        "priority": 0
                    }

                return {
                    "should_download": True,
                    "reason": "自动下载模式",
                    "priority": 1
                }

            elif mode == "selective":
                return self._evaluate_selective_download(message)

            return {
                "should_download": False,
                "reason": "未知下载模式",
                "priority": 0
            }

        except Exception as e:
            self.logger.error(f"做出下载决策失败: {e}")
            return {
                "should_download": False,
                "reason": f"决策出错: {e}",
                "priority": 0
            }

    def _evaluate_selective_download(self, message: Message) -> Dict[str, Any]:
        """
        评估选择性下载

        Args:
            message: 消息对象

        Returns:
            Dict: 下载决策信息
        """
        try:
            media_type = message.media_type

            # 选择性下载规则
            rules = {
                MediaType.IMAGE: {"auto": True, "max_mb": 10, "priority": 1},
                MediaType.VIDEO: {"auto": True, "max_mb": 50, "priority": 2},
                MediaType.AUDIO: {"auto": True, "max_mb": 20, "priority": 1},
                MediaType.DOCUMENT: {"auto": False, "max_mb": 10, "priority": 0}
            }

            rule = rules.get(media_type)
            if not rule:
                return {
                    "should_download": False,
                    "reason": f"媒体类型 {media_type} 没有选择性下载规则",
                    "priority": 0
                }

            # 检查是否启用自动下载
            if not rule["auto"]:
                return {
                    "should_download": False,
                    "reason": f"{media_type.value} 类型未启用自动下载",
                    "priority": 0
                }

            # 检查文件大小限制
            max_size_bytes = rule["max_mb"] * 1024 * 1024
            if message.file_size and message.file_size > max_size_bytes:
                return {
                    "should_download": False,
                    "reason": f"文件大小 ({message.file_size / (1024*1024):.1f} MB) 超过 {media_type.value} 类型限制 ({rule['max_mb']} MB)",
                    "priority": 0
                }

            # 通过所有检查，可以自动下载
            return {
                "should_download": True,
                "reason": f"{media_type.value} 类型选择性自动下载",
                "priority": rule["priority"]
            }

        except Exception as e:
            self.logger.error(f"评估选择性下载失败: {e}")
            return {
                "should_download": False,
                "reason": f"评估出错: {e}",
                "priority": 0
            }
    
    def _get_media_type(self, media) -> Optional[MediaType]:
        """
        确定媒体类型
        
        Args:
            media: 媒体对象
        
        Returns:
            Optional[MediaType]: 媒体类型
        """
        if isinstance(media, MessageMediaPhoto):
            return MediaType.IMAGE
        
        elif isinstance(media, MessageMediaDocument):
            document = media.document
            
            # 检查文档属性
            for attr in document.attributes:
                if isinstance(attr, DocumentAttributeVideo):
                    return MediaType.VIDEO
            
            # 根据MIME类型判断
            if document.mime_type:
                if document.mime_type.startswith('image/'):
                    return MediaType.IMAGE
                elif document.mime_type.startswith('video/'):
                    return MediaType.VIDEO
                elif document.mime_type.startswith('audio/'):
                    return MediaType.AUDIO
                else:
                    return MediaType.DOCUMENT
        
        return None
    
    def _extract_file_info(self, media) -> Optional[Dict[str, Any]]:
        """
        提取文件信息
        
        Args:
            media: 媒体对象
        
        Returns:
            Optional[Dict]: 文件信息
        """
        try:
            if isinstance(media, MessageMediaPhoto):
                return {
                    "name": f"photo_{media.photo.id}.jpg",
                    "size": getattr(media.photo, 'size', 0),
                    "mime_type": "image/jpeg"
                }
            
            elif isinstance(media, MessageMediaDocument):
                document = media.document
                
                # 获取文件名
                filename = f"document_{document.id}"
                for attr in document.attributes:
                    if isinstance(attr, DocumentAttributeFilename):
                        filename = attr.file_name
                        break
                
                return {
                    "name": filename,
                    "size": document.size,
                    "mime_type": document.mime_type
                }
            
            return None
            
        except Exception as e:
            self.logger.error(f"提取文件信息失败: {e}")
            return None
    
    async def _get_active_channels(self) -> List[Channel]:
        """获取活跃频道列表"""
        try:
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Channel).where(Channel.status == ChannelStatus.ACTIVE)
                )
                return result.scalars().all()
        except Exception as e:
            self.logger.error(f"获取活跃频道失败: {e}")
            return []
    
    async def _update_channel_stats(self, channel_id: str, message_count: int):
        """更新频道统计信息"""
        try:
            async with self.db_manager.get_async_session() as session:
                await session.execute(
                    update(Channel)
                    .where(Channel.channel_id == channel_id)
                    .values(
                        total_messages=Channel.total_messages + message_count,
                        updated_at=datetime.utcnow()
                    )
                )
                await session.commit()
        except Exception as e:
            self.logger.error(f"更新频道统计失败: {e}")
    
    async def _update_channel_last_check(self, channel_id: str, last_message_id: int):
        """更新频道最后检查时间和消息ID"""
        try:
            async with self.db_manager.get_async_session() as session:
                await session.execute(
                    update(Channel)
                    .where(Channel.channel_id == channel_id)
                    .values(
                        last_message_id=last_message_id,
                        last_check_time=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                )
                await session.commit()
        except Exception as e:
            self.logger.error(f"更新频道检查时间失败: {e}")
    
    async def _update_channel_status(self, channel_id: str, status: ChannelStatus):
        """更新频道状态"""
        try:
            async with self.db_manager.get_async_session() as session:
                await session.execute(
                    update(Channel)
                    .where(Channel.channel_id == channel_id)
                    .values(status=status, updated_at=datetime.utcnow())
                )
                await session.commit()
        except Exception as e:
            self.logger.error(f"更新频道状态失败: {e}")
