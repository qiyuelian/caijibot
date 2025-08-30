# -*- coding: utf-8 -*-
"""
元数据去重器
基于文件元数据进行去重检测，无需下载文件
"""

import asyncio
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument, 
    DocumentAttributeVideo, DocumentAttributeImageSize,
    DocumentAttributeFilename
)
from sqlalchemy import select, and_, or_

from ..database.database_manager import DatabaseManager
from ..database.models import Message, MediaType, MessageStatus, DuplicateRecord
from ..utils.logger import LoggerMixin


class MetadataDeduplicator(LoggerMixin):
    """元数据去重器"""
    
    def __init__(self, db_manager: DatabaseManager, similarity_threshold: float = 0.95):
        """
        初始化元数据去重器
        
        Args:
            db_manager: 数据库管理器
            similarity_threshold: 相似度阈值
        """
        self.db_manager = db_manager
        self.similarity_threshold = similarity_threshold
        self.logger.info("元数据去重器初始化完成")
    
    async def check_duplicate_by_metadata(self, telegram_message, channel_id: int) -> Dict[str, Any]:
        """
        基于元数据检查重复文件
        
        Args:
            telegram_message: Telegram消息对象
            channel_id: 频道ID
        
        Returns:
            Dict: 检测结果
        """
        try:
            # 提取文件元数据
            metadata = self._extract_file_metadata(telegram_message)
            if not metadata:
                return {
                    "is_duplicate": False,
                    "should_download": True,
                    "reason": "无法提取文件元数据"
                }
            
            # 根据媒体类型进行不同的检测
            if metadata["media_type"] == MediaType.VIDEO:
                return await self._check_video_duplicate(metadata, channel_id)
            elif metadata["media_type"] == MediaType.IMAGE:
                return await self._check_image_duplicate(metadata, channel_id)
            else:
                return await self._check_file_duplicate(metadata, channel_id)
                
        except Exception as e:
            self.logger.error(f"元数据去重检测失败: {e}")
            return {
                "is_duplicate": False,
                "should_download": True,
                "reason": f"检测出错，默认下载: {e}",
                "error": str(e)
            }
    
    def _extract_file_metadata(self, telegram_message) -> Optional[Dict[str, Any]]:
        """
        从Telegram消息中提取文件元数据
        
        Args:
            telegram_message: Telegram消息对象
        
        Returns:
            Optional[Dict]: 文件元数据
        """
        try:
            if not telegram_message.media:
                return None
            
            metadata = {
                "message_id": telegram_message.id,
                "message_date": telegram_message.date,
                "message_text": telegram_message.text or "",
                "file_name": None,
                "file_size": None,
                "mime_type": None,
                "media_type": None,
                # 视频特有属性
                "duration": None,
                "width": None,
                "height": None,
                "fps": None,
                # 图片特有属性
                "image_width": None,
                "image_height": None,
                # Telegram特有标识
                "telegram_file_id": None,
                "telegram_file_unique_id": None
            }
            
            if isinstance(telegram_message.media, MessageMediaPhoto):
                photo = telegram_message.media.photo
                metadata.update({
                    "file_name": f"photo_{photo.id}.jpg",
                    "file_size": getattr(photo, 'size', 0),
                    "mime_type": "image/jpeg",
                    "media_type": MediaType.IMAGE,
                    "telegram_file_id": str(photo.id),
                    "telegram_file_unique_id": getattr(photo, 'file_unique_id', None)
                })
                
                # 获取图片尺寸
                if hasattr(photo, 'sizes') and photo.sizes:
                    largest_size = max(photo.sizes, key=lambda s: getattr(s, 'size', 0))
                    if hasattr(largest_size, 'w') and hasattr(largest_size, 'h'):
                        metadata.update({
                            "image_width": largest_size.w,
                            "image_height": largest_size.h
                        })
                
            elif isinstance(telegram_message.media, MessageMediaDocument):
                document = telegram_message.media.document
                
                # 基本信息
                metadata.update({
                    "file_size": document.size,
                    "mime_type": document.mime_type,
                    "telegram_file_id": str(document.id),
                    "telegram_file_unique_id": getattr(document, 'file_unique_id', None)
                })
                
                # 解析文档属性
                filename = f"document_{document.id}"
                for attr in document.attributes:
                    if isinstance(attr, DocumentAttributeFilename):
                        filename = attr.file_name
                    elif isinstance(attr, DocumentAttributeVideo):
                        metadata.update({
                            "duration": attr.duration,
                            "width": attr.w,
                            "height": attr.h,
                            "media_type": MediaType.VIDEO
                        })
                        # 有些视频属性可能包含fps信息
                        if hasattr(attr, 'fps'):
                            metadata["fps"] = attr.fps
                    elif isinstance(attr, DocumentAttributeImageSize):
                        metadata.update({
                            "image_width": attr.w,
                            "image_height": attr.h,
                            "media_type": MediaType.IMAGE
                        })
                
                metadata["file_name"] = filename
                
                # 根据MIME类型确定媒体类型（如果还没确定）
                if not metadata["media_type"]:
                    if document.mime_type:
                        if document.mime_type.startswith('image/'):
                            metadata["media_type"] = MediaType.IMAGE
                        elif document.mime_type.startswith('video/'):
                            metadata["media_type"] = MediaType.VIDEO
                        elif document.mime_type.startswith('audio/'):
                            metadata["media_type"] = MediaType.AUDIO
                        else:
                            metadata["media_type"] = MediaType.DOCUMENT
                    else:
                        metadata["media_type"] = MediaType.DOCUMENT
            
            return metadata
            
        except Exception as e:
            self.logger.error(f"提取文件元数据失败: {e}")
            return None
    
    async def _check_video_duplicate(self, metadata: Dict[str, Any], channel_id: int) -> Dict[str, Any]:
        """
        检查视频重复（基于时长、分辨率等）
        
        Args:
            metadata: 视频元数据
            channel_id: 频道ID
        
        Returns:
            Dict: 检测结果
        """
        try:
            duration = metadata.get("duration")
            width = metadata.get("width")
            height = metadata.get("height")
            file_size = metadata.get("file_size")
            
            if not duration:
                return {"is_duplicate": False, "reason": "视频没有时长信息"}
            
            async with self.db_manager.get_async_session() as session:
                # 查找相同时长的视频
                query = select(Message).where(
                    Message.media_type == MediaType.VIDEO,
                    Message.channel_id == channel_id,
                    Message.status != MessageStatus.DUPLICATE
                )
                
                # 添加时长条件（允许1秒误差）
                duration_conditions = []
                for delta in range(-1, 2):  # -1, 0, 1秒误差
                    target_duration = duration + delta
                    duration_conditions.append(
                        Message.message_text.like(f'%"duration": {target_duration}%')
                    )
                
                if duration_conditions:
                    query = query.where(or_(*duration_conditions))
                
                result = await session.execute(query.limit(20))
                potential_duplicates = result.scalars().all()
                
                # 详细比较每个潜在重复项
                for msg in potential_duplicates:
                    similarity_info = self._calculate_video_similarity(metadata, msg)
                    
                    if similarity_info["is_similar"]:
                        self.logger.info(
                            f"发现相似视频: 时长={duration}s, 分辨率={width}x{height}, "
                            f"原始消息: {msg.id}, 相似度: {similarity_info['similarity']:.3f}"
                        )
                        
                        # 如果相似度很高，直接标记为重复
                        if similarity_info["similarity"] >= 0.98:
                            return {
                                "is_duplicate": True,
                                "should_download": False,
                                "reason": f"视频高度相似 (相似度: {similarity_info['similarity']:.3f})",
                                "original_message_id": msg.id,
                                "similarity_score": similarity_info["similarity"],
                                "duplicate_type": "video_metadata",
                                "details": similarity_info["details"]
                            }
                        # 如果相似度较高，需要人工审核
                        elif similarity_info["similarity"] >= self.similarity_threshold:
                            return {
                                "is_duplicate": False,
                                "should_download": True,
                                "needs_manual_review": True,
                                "reason": f"视频可能重复，需要人工审核 (相似度: {similarity_info['similarity']:.3f})",
                                "original_message_id": msg.id,
                                "similarity_score": similarity_info["similarity"],
                                "duplicate_type": "video_metadata_similar",
                                "details": similarity_info["details"]
                            }
                
                return {"is_duplicate": False, "reason": "未发现相似视频"}
                
        except Exception as e:
            self.logger.error(f"视频重复检测失败: {e}")
            return {"is_duplicate": False, "reason": f"检测出错: {e}"}
    
    def _calculate_video_similarity(self, metadata1: Dict[str, Any], message2: Message) -> Dict[str, Any]:
        """
        计算两个视频的相似度
        
        Args:
            metadata1: 第一个视频的元数据
            message2: 第二个视频的消息记录
        
        Returns:
            Dict: 相似度信息
        """
        try:
            # 从消息记录中提取视频信息（简化实现，实际应该存储在单独字段中）
            # 这里假设我们在message_text中存储了一些元数据信息
            
            similarity_scores = []
            details = {}
            
            # 1. 时长相似度（最重要）
            duration1 = metadata1.get("duration")
            if duration1 and message2.message_text:
                # 简单解析（实际应该有更好的存储方式）
                import re
                duration_match = re.search(r'"duration":\s*(\d+)', message2.message_text)
                if duration_match:
                    duration2 = int(duration_match.group(1))
                    duration_diff = abs(duration1 - duration2)
                    duration_similarity = max(0, 1 - duration_diff / max(duration1, duration2))
                    similarity_scores.append(duration_similarity * 0.5)  # 50%权重
                    details["duration_similarity"] = duration_similarity
                    details["duration1"] = duration1
                    details["duration2"] = duration2
            
            # 2. 分辨率相似度
            width1, height1 = metadata1.get("width"), metadata1.get("height")
            if width1 and height1 and message2.message_text:
                width_match = re.search(r'"width":\s*(\d+)', message2.message_text)
                height_match = re.search(r'"height":\s*(\d+)', message2.message_text)
                
                if width_match and height_match:
                    width2, height2 = int(width_match.group(1)), int(height_match.group(1))
                    
                    # 计算分辨率相似度
                    width_similarity = 1 - abs(width1 - width2) / max(width1, width2)
                    height_similarity = 1 - abs(height1 - height2) / max(height1, height2)
                    resolution_similarity = (width_similarity + height_similarity) / 2
                    
                    similarity_scores.append(resolution_similarity * 0.3)  # 30%权重
                    details["resolution_similarity"] = resolution_similarity
                    details["resolution1"] = f"{width1}x{height1}"
                    details["resolution2"] = f"{width2}x{height2}"
            
            # 3. 文件大小相似度
            size1 = metadata1.get("file_size")
            size2 = message2.file_size
            if size1 and size2:
                size_diff = abs(size1 - size2)
                size_similarity = max(0, 1 - size_diff / max(size1, size2))
                similarity_scores.append(size_similarity * 0.2)  # 20%权重
                details["size_similarity"] = size_similarity
                details["size1"] = size1
                details["size2"] = size2
            
            # 计算总相似度
            total_similarity = sum(similarity_scores) if similarity_scores else 0
            
            return {
                "is_similar": total_similarity >= self.similarity_threshold,
                "similarity": total_similarity,
                "details": details
            }
            
        except Exception as e:
            self.logger.error(f"计算视频相似度失败: {e}")
            return {"is_similar": False, "similarity": 0.0, "details": {}}
    
    async def _check_image_duplicate(self, metadata: Dict[str, Any], channel_id: int) -> Dict[str, Any]:
        """
        检查图片重复（基于尺寸、文件大小等）
        
        Args:
            metadata: 图片元数据
            channel_id: 频道ID
        
        Returns:
            Dict: 检测结果
        """
        try:
            width = metadata.get("image_width") or metadata.get("width")
            height = metadata.get("image_height") or metadata.get("height")
            file_size = metadata.get("file_size")
            
            if not (width and height and file_size):
                return {"is_duplicate": False, "reason": "图片元数据不完整"}
            
            async with self.db_manager.get_async_session() as session:
                # 查找相同尺寸和相似大小的图片
                result = await session.execute(
                    select(Message).where(
                        Message.media_type == MediaType.IMAGE,
                        Message.channel_id == channel_id,
                        Message.file_size.between(
                            int(file_size * 0.9),  # 允许10%的大小差异
                            int(file_size * 1.1)
                        ),
                        Message.status != MessageStatus.DUPLICATE
                    ).limit(10)
                )
                
                potential_duplicates = result.scalars().all()
                
                for msg in potential_duplicates:
                    # 简单的图片相似度检查
                    if (msg.file_size and 
                        abs(msg.file_size - file_size) / file_size < 0.05):  # 5%大小差异
                        
                        self.logger.info(
                            f"发现相似图片: 尺寸={width}x{height}, 大小={file_size}, "
                            f"原始消息: {msg.id}"
                        )
                        
                        return {
                            "is_duplicate": True,
                            "should_download": False,
                            "reason": "图片尺寸和大小高度相似",
                            "original_message_id": msg.id,
                            "similarity_score": 0.95,
                            "duplicate_type": "image_metadata"
                        }
                
                return {"is_duplicate": False, "reason": "未发现相似图片"}
                
        except Exception as e:
            self.logger.error(f"图片重复检测失败: {e}")
            return {"is_duplicate": False, "reason": f"检测出错: {e}"}
    
    async def _check_file_duplicate(self, metadata: Dict[str, Any], channel_id: int) -> Dict[str, Any]:
        """
        检查普通文件重复（基于文件名和大小）
        
        Args:
            metadata: 文件元数据
            channel_id: 频道ID
        
        Returns:
            Dict: 检测结果
        """
        try:
            file_name = metadata.get("file_name")
            file_size = metadata.get("file_size")
            
            if not (file_name and file_size):
                return {"is_duplicate": False, "reason": "文件信息不完整"}
            
            async with self.db_manager.get_async_session() as session:
                # 查找相同文件名和大小的文件
                result = await session.execute(
                    select(Message).where(
                        Message.file_name == file_name,
                        Message.file_size == file_size,
                        Message.channel_id == channel_id,
                        Message.status != MessageStatus.DUPLICATE
                    )
                )
                
                existing_msg = result.scalar_one_or_none()
                
                if existing_msg:
                    self.logger.info(
                        f"发现重复文件: {file_name} ({file_size} bytes), "
                        f"原始消息: {existing_msg.id}"
                    )
                    
                    return {
                        "is_duplicate": True,
                        "should_download": False,
                        "reason": "文件名和大小完全相同",
                        "original_message_id": existing_msg.id,
                        "similarity_score": 1.0,
                        "duplicate_type": "file_exact"
                    }
                
                return {"is_duplicate": False, "reason": "未发现重复文件"}
                
        except Exception as e:
            self.logger.error(f"文件重复检测失败: {e}")
            return {"is_duplicate": False, "reason": f"检测出错: {e}"}
    
    async def send_manual_review_notification(
        self, 
        telegram_message, 
        channel_id: int, 
        similarity_info: Dict[str, Any],
        bot_instance
    ):
        """
        发送人工审核通知
        
        Args:
            telegram_message: Telegram消息对象
            channel_id: 频道ID
            similarity_info: 相似度信息
            bot_instance: 机器人实例
        """
        try:
            # 获取频道信息
            async with self.db_manager.get_async_session() as session:
                from ..database.models import Channel
                result = await session.execute(
                    select(Channel).where(Channel.id == channel_id)
                )
                channel = result.scalar_one_or_none()
                
                channel_name = channel.channel_title if channel else f"频道ID: {channel_id}"
            
            # 构建通知消息
            metadata = self._extract_file_metadata(telegram_message)
            details = similarity_info.get("details", {})
            
            notification_text = f"""
🔍 **需要人工审核的重复文件**

📺 **频道**: {channel_name}
📄 **文件**: {metadata.get('file_name', 'Unknown')}
📊 **相似度**: {similarity_info.get('similarity_score', 0):.1%}

🎬 **视频信息**:
• 时长: {metadata.get('duration', 'Unknown')}秒
• 分辨率: {metadata.get('width', '?')}x{metadata.get('height', '?')}
• 大小: {metadata.get('file_size', 0) / (1024*1024):.1f} MB

🔄 **对比信息**:
• 时长相似度: {details.get('duration_similarity', 0):.1%}
• 分辨率相似度: {details.get('resolution_similarity', 0):.1%}
• 大小相似度: {details.get('size_similarity', 0):.1%}

💡 请手动确认是否为重复文件
            """
            
            # 这里应该发送给管理员或特定用户
            # 暂时记录日志
            self.logger.warning(f"需要人工审核: {notification_text}")
            
            # TODO: 实际发送通知给用户
            # await bot_instance.send_message(admin_user_id, notification_text)
            
        except Exception as e:
            self.logger.error(f"发送人工审核通知失败: {e}")
