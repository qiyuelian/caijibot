# -*- coding: utf-8 -*-
"""
预下载去重器
在下载文件前进行去重检测，避免下载重复文件
"""

import asyncio
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from sqlalchemy import select

from ..database.database_manager import DatabaseManager
from ..database.models import Message, MediaType, MessageStatus, DuplicateRecord
from ..utils.logger import LoggerMixin


class PreDownloadDeduplicator(LoggerMixin):
    """预下载去重器"""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        初始化预下载去重器
        
        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.logger.info("预下载去重器初始化完成")
    
    async def check_duplicate_before_download(self, telegram_message, channel_id: int) -> Dict[str, Any]:
        """
        在下载前检查是否为重复文件
        
        Args:
            telegram_message: Telegram消息对象
            channel_id: 频道ID
        
        Returns:
            Dict: 检测结果
        """
        try:
            # 提取文件信息
            file_info = self._extract_telegram_file_info(telegram_message)
            if not file_info:
                return {
                    "is_duplicate": False,
                    "should_download": True,
                    "reason": "无法提取文件信息"
                }
            
            # 检查各种重复情况
            duplicate_checks = [
                await self._check_by_file_size_and_name(file_info, channel_id),
                await self._check_by_telegram_file_id(file_info),
                await self._check_by_message_content(telegram_message, channel_id)
            ]
            
            # 如果任何一种检查发现重复，则跳过下载
            for check_result in duplicate_checks:
                if check_result["is_duplicate"]:
                    return check_result
            
            return {
                "is_duplicate": False,
                "should_download": True,
                "reason": "未发现重复，可以下载",
                "file_info": file_info
            }
            
        except Exception as e:
            self.logger.error(f"预下载去重检测失败: {e}")
            return {
                "is_duplicate": False,
                "should_download": True,
                "reason": f"检测出错，默认下载: {e}",
                "error": str(e)
            }
    
    def _extract_telegram_file_info(self, telegram_message) -> Optional[Dict[str, Any]]:
        """
        从Telegram消息中提取文件信息
        
        Args:
            telegram_message: Telegram消息对象
        
        Returns:
            Optional[Dict]: 文件信息
        """
        try:
            if not telegram_message.media:
                return None
            
            file_info = {
                "message_id": telegram_message.id,
                "message_date": telegram_message.date,
                "message_text": telegram_message.text or "",
                "file_name": None,
                "file_size": None,
                "mime_type": None,
                "telegram_file_id": None,
                "media_type": None
            }
            
            if isinstance(telegram_message.media, MessageMediaPhoto):
                photo = telegram_message.media.photo
                file_info.update({
                    "file_name": f"photo_{photo.id}.jpg",
                    "file_size": getattr(photo, 'size', 0),
                    "mime_type": "image/jpeg",
                    "telegram_file_id": str(photo.id),
                    "media_type": MediaType.IMAGE
                })
                
            elif isinstance(telegram_message.media, MessageMediaDocument):
                document = telegram_message.media.document
                
                # 获取文件名
                filename = f"document_{document.id}"
                for attr in document.attributes:
                    if hasattr(attr, 'file_name') and attr.file_name:
                        filename = attr.file_name
                        break
                
                # 判断媒体类型
                media_type = MediaType.DOCUMENT
                if document.mime_type:
                    if document.mime_type.startswith('image/'):
                        media_type = MediaType.IMAGE
                    elif document.mime_type.startswith('video/'):
                        media_type = MediaType.VIDEO
                    elif document.mime_type.startswith('audio/'):
                        media_type = MediaType.AUDIO
                
                file_info.update({
                    "file_name": filename,
                    "file_size": document.size,
                    "mime_type": document.mime_type,
                    "telegram_file_id": str(document.id),
                    "media_type": media_type
                })
            
            return file_info
            
        except Exception as e:
            self.logger.error(f"提取文件信息失败: {e}")
            return None
    
    async def _check_by_file_size_and_name(self, file_info: Dict[str, Any], channel_id: int) -> Dict[str, Any]:
        """
        通过文件大小和名称检查重复
        
        Args:
            file_info: 文件信息
            channel_id: 频道ID
        
        Returns:
            Dict: 检测结果
        """
        try:
            if not file_info.get("file_name") or not file_info.get("file_size"):
                return {"is_duplicate": False, "reason": "缺少文件名或大小信息"}
            
            async with self.db_manager.get_async_session() as session:
                # 查找相同文件名和大小的文件
                result = await session.execute(
                    select(Message).where(
                        Message.file_name == file_info["file_name"],
                        Message.file_size == file_info["file_size"],
                        Message.channel_id == channel_id,
                        Message.status != MessageStatus.DUPLICATE
                    )
                )
                
                existing_messages = result.scalars().all()
                
                if existing_messages:
                    original_msg = existing_messages[0]  # 取第一个作为原始文件
                    
                    self.logger.info(
                        f"发现重复文件 (文件名+大小): {file_info['file_name']} "
                        f"({file_info['file_size']} bytes), 原始消息: {original_msg.id}"
                    )
                    
                    return {
                        "is_duplicate": True,
                        "should_download": False,
                        "reason": "文件名和大小完全相同",
                        "original_message_id": original_msg.id,
                        "similarity_score": 1.0,
                        "duplicate_type": "file_name_size"
                    }
                
                return {"is_duplicate": False, "reason": "文件名和大小检查通过"}
                
        except Exception as e:
            self.logger.error(f"文件名大小检查失败: {e}")
            return {"is_duplicate": False, "reason": f"检查出错: {e}"}
    
    async def _check_by_telegram_file_id(self, file_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过Telegram文件ID检查重复
        
        Args:
            file_info: 文件信息
        
        Returns:
            Dict: 检测结果
        """
        try:
            telegram_file_id = file_info.get("telegram_file_id")
            if not telegram_file_id:
                return {"is_duplicate": False, "reason": "没有Telegram文件ID"}
            
            async with self.db_manager.get_async_session() as session:
                # 在消息文本中搜索相同的文件ID（简单实现）
                # 注意：这里需要一个更好的方式来存储和检索Telegram文件ID
                result = await session.execute(
                    select(Message).where(
                        Message.message_text.like(f"%{telegram_file_id}%"),
                        Message.status != MessageStatus.DUPLICATE
                    ).limit(10)  # 限制查询数量
                )
                
                existing_messages = result.scalars().all()
                
                # 进一步验证是否真的是相同文件
                for msg in existing_messages:
                    if (msg.file_size == file_info.get("file_size") and 
                        msg.media_type == file_info.get("media_type")):
                        
                        self.logger.info(
                            f"发现重复文件 (Telegram文件ID): {telegram_file_id}, "
                            f"原始消息: {msg.id}"
                        )
                        
                        return {
                            "is_duplicate": True,
                            "should_download": False,
                            "reason": "Telegram文件ID相同",
                            "original_message_id": msg.id,
                            "similarity_score": 1.0,
                            "duplicate_type": "telegram_file_id"
                        }
                
                return {"is_duplicate": False, "reason": "Telegram文件ID检查通过"}
                
        except Exception as e:
            self.logger.error(f"Telegram文件ID检查失败: {e}")
            return {"is_duplicate": False, "reason": f"检查出错: {e}"}
    
    async def _check_by_message_content(self, telegram_message, channel_id: int) -> Dict[str, Any]:
        """
        通过消息内容检查重复（适用于转发消息）
        
        Args:
            telegram_message: Telegram消息对象
            channel_id: 频道ID
        
        Returns:
            Dict: 检测结果
        """
        try:
            # 检查是否为转发消息
            if hasattr(telegram_message, 'forward') and telegram_message.forward:
                forward_info = telegram_message.forward
                
                # 如果有原始消息ID，检查是否已经采集过
                if hasattr(forward_info, 'channel_post') and forward_info.channel_post:
                    original_message_id = forward_info.channel_post
                    
                    async with self.db_manager.get_async_session() as session:
                        result = await session.execute(
                            select(Message).where(
                                Message.message_id == original_message_id,
                                Message.status != MessageStatus.DUPLICATE
                            )
                        )
                        
                        existing_msg = result.scalar_one_or_none()
                        
                        if existing_msg:
                            self.logger.info(
                                f"发现重复转发消息: 原始消息ID {original_message_id}, "
                                f"已存在消息: {existing_msg.id}"
                            )
                            
                            return {
                                "is_duplicate": True,
                                "should_download": False,
                                "reason": "转发的消息已存在",
                                "original_message_id": existing_msg.id,
                                "similarity_score": 1.0,
                                "duplicate_type": "forwarded_message"
                            }
            
            # 检查消息文本相似度（如果有文本）
            if telegram_message.text and len(telegram_message.text) > 20:
                similar_msg = await self._find_similar_text_message(
                    telegram_message.text, 
                    channel_id
                )
                
                if similar_msg:
                    return {
                        "is_duplicate": True,
                        "should_download": False,
                        "reason": "消息文本高度相似",
                        "original_message_id": similar_msg.id,
                        "similarity_score": 0.9,
                        "duplicate_type": "similar_text"
                    }
            
            return {"is_duplicate": False, "reason": "消息内容检查通过"}
            
        except Exception as e:
            self.logger.error(f"消息内容检查失败: {e}")
            return {"is_duplicate": False, "reason": f"检查出错: {e}"}
    
    async def _find_similar_text_message(self, text: str, channel_id: int) -> Optional[Message]:
        """
        查找相似文本的消息
        
        Args:
            text: 消息文本
            channel_id: 频道ID
        
        Returns:
            Optional[Message]: 相似的消息
        """
        try:
            # 简单的文本相似度检查：提取关键词
            keywords = [word.strip() for word in text.split() if len(word.strip()) > 3][:5]
            
            if not keywords:
                return None
            
            async with self.db_manager.get_async_session() as session:
                # 查找包含相同关键词的消息
                for keyword in keywords:
                    result = await session.execute(
                        select(Message).where(
                            Message.message_text.like(f"%{keyword}%"),
                            Message.channel_id == channel_id,
                            Message.status != MessageStatus.DUPLICATE
                        ).limit(5)
                    )
                    
                    messages = result.scalars().all()
                    
                    for msg in messages:
                        if msg.message_text and len(msg.message_text) > 20:
                            # 简单的相似度计算
                            similarity = self._calculate_text_similarity(text, msg.message_text)
                            if similarity > 0.8:  # 80%相似度阈值
                                return msg
                
                return None
                
        except Exception as e:
            self.logger.error(f"查找相似文本消息失败: {e}")
            return None
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """
        计算文本相似度（简单实现）
        
        Args:
            text1: 第一个文本
            text2: 第二个文本
        
        Returns:
            float: 相似度 (0-1)
        """
        try:
            # 转换为小写并分词
            words1 = set(text1.lower().split())
            words2 = set(text2.lower().split())
            
            if not words1 or not words2:
                return 0.0
            
            # 计算Jaccard相似度
            intersection = len(words1.intersection(words2))
            union = len(words1.union(words2))
            
            return intersection / union if union > 0 else 0.0
            
        except Exception:
            return 0.0
    
    async def mark_as_pre_download_duplicate(
        self, 
        telegram_message, 
        channel_id: int,
        duplicate_info: Dict[str, Any]
    ) -> bool:
        """
        标记为预下载检测到的重复消息
        
        Args:
            telegram_message: Telegram消息对象
            channel_id: 频道ID
            duplicate_info: 重复信息
        
        Returns:
            bool: 是否标记成功
        """
        try:
            file_info = self._extract_telegram_file_info(telegram_message)
            if not file_info:
                return False
            
            async with self.db_manager.get_async_session() as session:
                # 创建消息记录（标记为重复）
                new_message = Message(
                    message_id=telegram_message.id,
                    channel_id=channel_id,
                    message_text=file_info["message_text"],
                    media_type=file_info["media_type"],
                    file_name=file_info["file_name"],
                    file_size=file_info["file_size"],
                    status=MessageStatus.DUPLICATE,
                    is_duplicate=True,
                    original_message_id=duplicate_info.get("original_message_id"),
                    message_date=file_info["message_date"]
                )
                
                session.add(new_message)
                await session.flush()  # 获取新消息的ID
                
                # 创建去重记录
                duplicate_record = DuplicateRecord(
                    original_message_id=duplicate_info.get("original_message_id"),
                    duplicate_message_id=new_message.id,
                    similarity_score=duplicate_info.get("similarity_score", 1.0),
                    similarity_type=duplicate_info.get("duplicate_type", "pre_download"),
                    action_taken="skip_download",
                    reason=duplicate_info.get("reason", "预下载检测发现重复")
                )
                
                session.add(duplicate_record)
                await session.commit()
                
                self.logger.info(
                    f"标记预下载重复消息: {telegram_message.id}, "
                    f"原因: {duplicate_info.get('reason')}"
                )
                
                return True
                
        except Exception as e:
            self.logger.error(f"标记预下载重复消息失败: {e}")
            return False
