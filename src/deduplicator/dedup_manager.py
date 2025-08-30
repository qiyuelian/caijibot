# -*- coding: utf-8 -*-
"""
去重管理器
统一管理所有类型的去重检测
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..database.database_manager import DatabaseManager
from ..database.models import Message, MediaType, MessageStatus
from ..config.settings import Settings
from ..utils.logger import LoggerMixin
from .hash_deduplicator import HashDeduplicator
from .image_deduplicator import ImageDeduplicator
from .video_deduplicator import VideoDeduplicator
from .metadata_deduplicator import MetadataDeduplicator
from sqlalchemy import select


class DeduplicationManager(LoggerMixin):
    """去重管理器"""
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        初始化去重管理器
        
        Args:
            db_manager: 数据库管理器
            settings: 配置对象
        """
        self.db_manager = db_manager
        self.settings = settings
        
        # 初始化各种去重器
        self.hash_deduplicator = HashDeduplicator(db_manager)
        self.image_deduplicator = ImageDeduplicator(
            db_manager,
            settings.duplicate_threshold
        )
        self.video_deduplicator = VideoDeduplicator(
            db_manager,
            settings.duplicate_threshold
        )
        self.metadata_deduplicator = MetadataDeduplicator(
            db_manager,
            settings.duplicate_threshold
        )
        
        # 去重状态
        self.is_deduplicating = False
        self.dedup_stats = {
            "processed": 0,
            "duplicates_found": 0,
            "errors": 0,
            "start_time": None
        }
        
        self.logger.info("去重管理器初始化完成")

    async def check_duplicate_before_download(self, telegram_message, channel_id: int) -> Dict[str, Any]:
        """
        在下载前检查是否为重复文件（基于元数据）

        Args:
            telegram_message: Telegram消息对象
            channel_id: 频道ID

        Returns:
            Dict: 检测结果
        """
        try:
            # 使用元数据去重器进行预检测
            result = await self.metadata_deduplicator.check_duplicate_by_metadata(
                telegram_message,
                channel_id
            )

            # 如果需要人工审核，发送通知
            if result.get("needs_manual_review"):
                # TODO: 发送人工审核通知
                self.logger.warning(
                    f"消息 {telegram_message.id} 需要人工审核: {result.get('reason')}"
                )

            return result

        except Exception as e:
            self.logger.error(f"预下载去重检测失败: {e}")
            return {
                "is_duplicate": False,
                "should_download": True,
                "reason": f"检测出错，默认下载: {e}",
                "error": str(e)
            }
    
    async def start_auto_deduplication(self):
        """开始自动去重处理"""
        if self.is_deduplicating:
            self.logger.warning("去重管理器已在运行中")
            return
        
        if not (self.settings.enable_hash_dedup or self.settings.enable_feature_dedup):
            self.logger.info("去重功能已禁用")
            return
        
        self.is_deduplicating = True
        self.dedup_stats["start_time"] = datetime.utcnow()
        self.logger.info("开始自动去重处理")
        
        try:
            while self.is_deduplicating:
                # 获取待去重的消息
                pending_messages = await self._get_pending_messages()
                
                if pending_messages:
                    self.logger.info(f"找到 {len(pending_messages)} 条待去重消息")
                    
                    # 批量处理消息
                    for message in pending_messages:
                        if not self.is_deduplicating:
                            break
                        
                        await self._process_single_message_deduplication(message)
                        self.dedup_stats["processed"] += 1
                        
                        # 避免过度占用资源
                        await asyncio.sleep(0.5)
                
                # 等待下一轮处理
                await asyncio.sleep(60)  # 每分钟检查一次
                
        except Exception as e:
            self.logger.error(f"自动去重处理出错: {e}")
        finally:
            self.is_deduplicating = False
    
    async def stop_auto_deduplication(self):
        """停止自动去重处理"""
        self.is_deduplicating = False
        self.logger.info("停止自动去重处理")
    
    async def process_message_deduplication(self, message_id: int) -> Dict[str, Any]:
        """
        处理单条消息的去重检测
        
        Args:
            message_id: 消息ID
        
        Returns:
            Dict: 处理结果
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
            
            # 执行去重检测
            result = await self._process_single_message_deduplication(message)
            
            return {
                "success": True,
                "message_id": message_id,
                "result": result
            }
            
        except Exception as e:
            self.logger.error(f"处理消息去重失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _process_single_message_deduplication(self, message: Message) -> Dict[str, Any]:
        """
        处理单条消息的去重检测
        
        Args:
            message: 消息对象
        
        Returns:
            Dict: 处理结果
        """
        try:
            results = {
                "hash_dedup": None,
                "feature_dedup": None,
                "total_duplicates": 0
            }
            
            # 1. 哈希去重（如果启用）
            if self.settings.enable_hash_dedup:
                hash_result = await self.hash_deduplicator.process_message_deduplication(message)
                results["hash_dedup"] = hash_result
                
                if hash_result["success"]:
                    results["total_duplicates"] += hash_result["duplicates_found"]
            
            # 2. 特征去重（如果启用且不是重复文件）
            if self.settings.enable_feature_dedup and not message.is_duplicate:
                if message.media_type == MediaType.IMAGE:
                    feature_result = await self.image_deduplicator.process_image_deduplication(message)
                elif message.media_type == MediaType.VIDEO:
                    feature_result = await self.video_deduplicator.process_video_deduplication(message)
                else:
                    feature_result = {"success": True, "reason": "不支持的媒体类型", "duplicates_found": 0}
                
                results["feature_dedup"] = feature_result
                
                if feature_result["success"]:
                    results["total_duplicates"] += feature_result["duplicates_found"]
            
            # 更新统计
            if results["total_duplicates"] > 0:
                self.dedup_stats["duplicates_found"] += results["total_duplicates"]
            
            self.logger.debug(f"消息 {message.id} 去重完成，发现 {results['total_duplicates']} 个重复")
            
            return results
            
        except Exception as e:
            self.logger.error(f"处理消息 {message.id} 去重失败: {e}")
            self.dedup_stats["errors"] += 1
            return {
                "hash_dedup": None,
                "feature_dedup": None,
                "total_duplicates": 0,
                "error": str(e)
            }
    
    async def batch_process_deduplication(
        self, 
        media_type: Optional[str] = None, 
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        批量处理去重检测
        
        Args:
            media_type: 媒体类型过滤 (image, video, 或 None 表示全部)
            limit: 处理数量限制
        
        Returns:
            Dict: 批量处理结果
        """
        try:
            # 获取待处理消息
            async with self.db_manager.get_async_session() as session:
                query = select(Message).where(
                    Message.status == MessageStatus.COMPLETED,
                    Message.file_path.isnot(None),
                    Message.is_duplicate == False
                )
                
                if media_type:
                    if media_type == "image":
                        query = query.where(Message.media_type == MediaType.IMAGE)
                    elif media_type == "video":
                        query = query.where(Message.media_type == MediaType.VIDEO)
                
                query = query.limit(limit).order_by(Message.created_at.asc())
                
                result = await session.execute(query)
                messages = result.scalars().all()
            
            if not messages:
                return {
                    "success": True,
                    "processed": 0,
                    "duplicates_found": 0,
                    "message": "没有需要处理的消息"
                }
            
            # 批量处理
            total_processed = 0
            total_duplicates = 0
            errors = []
            
            for message in messages:
                try:
                    result = await self._process_single_message_deduplication(message)
                    total_processed += 1
                    total_duplicates += result["total_duplicates"]
                    
                    if "error" in result:
                        errors.append(f"消息 {message.id}: {result['error']}")
                    
                    # 避免过度占用资源
                    await asyncio.sleep(0.3)
                    
                except Exception as e:
                    errors.append(f"消息 {message.id}: {str(e)}")
            
            self.logger.info(
                f"批量去重完成: 处理 {total_processed} 条消息, "
                f"发现 {total_duplicates} 个重复文件, "
                f"错误 {len(errors)} 个"
            )
            
            return {
                "success": True,
                "processed": total_processed,
                "duplicates_found": total_duplicates,
                "errors": errors[:10]  # 只返回前10个错误
            }
            
        except Exception as e:
            self.logger.error(f"批量去重处理失败: {e}")
            return {
                "success": False,
                "processed": 0,
                "duplicates_found": 0,
                "error": str(e)
            }
    
    async def _get_pending_messages(self, limit: int = 50) -> List[Message]:
        """
        获取待去重的消息
        
        Args:
            limit: 限制数量
        
        Returns:
            List[Message]: 待去重消息列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 查找已完成但未去重的消息
                result = await session.execute(
                    select(Message)
                    .where(
                        Message.status == MessageStatus.COMPLETED,
                        Message.file_path.isnot(None),
                        Message.is_duplicate == False
                    )
                    .limit(limit)
                    .order_by(Message.created_at.asc())
                )
                
                return result.scalars().all()
                
        except Exception as e:
            self.logger.error(f"获取待去重消息失败: {e}")
            return []
    
    async def get_deduplication_stats(self) -> Dict[str, Any]:
        """
        获取去重统计信息
        
        Returns:
            Dict: 统计信息
        """
        try:
            # 获取基础统计
            hash_stats = await self.hash_deduplicator.get_deduplication_stats()
            
            # 合并运行时统计
            combined_stats = hash_stats.copy()
            combined_stats.update({
                "is_running": self.is_deduplicating,
                "runtime_stats": self.dedup_stats.copy(),
                "settings": {
                    "hash_dedup_enabled": self.settings.enable_hash_dedup,
                    "feature_dedup_enabled": self.settings.enable_feature_dedup,
                    "duplicate_threshold": self.settings.duplicate_threshold
                }
            })
            
            # 计算运行时间
            if self.dedup_stats["start_time"]:
                runtime = datetime.utcnow() - self.dedup_stats["start_time"]
                combined_stats["runtime_seconds"] = runtime.total_seconds()
            
            return combined_stats
            
        except Exception as e:
            self.logger.error(f"获取去重统计失败: {e}")
            return {
                "error": str(e),
                "is_running": self.is_deduplicating,
                "runtime_stats": self.dedup_stats.copy()
            }
    
    async def get_duplicate_files_report(self, limit: int = 100) -> Dict[str, Any]:
        """
        获取重复文件报告
        
        Args:
            limit: 限制数量
        
        Returns:
            Dict: 重复文件报告
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 获取重复消息
                result = await session.execute(
                    select(Message)
                    .where(Message.is_duplicate == True)
                    .limit(limit)
                    .order_by(Message.created_at.desc())
                )
                
                duplicate_messages = result.scalars().all()
                
                # 按原始消息分组
                duplicate_groups = {}
                for msg in duplicate_messages:
                    original_id = msg.original_message_id
                    if original_id not in duplicate_groups:
                        duplicate_groups[original_id] = []
                    duplicate_groups[original_id].append({
                        "id": msg.id,
                        "file_name": msg.file_name,
                        "file_size": msg.file_size,
                        "created_at": msg.created_at.isoformat(),
                        "media_type": msg.media_type
                    })
                
                # 统计信息
                total_duplicates = len(duplicate_messages)
                total_groups = len(duplicate_groups)
                
                # 计算节省的空间
                space_saved = sum(msg.file_size or 0 for msg in duplicate_messages)
                
                return {
                    "success": True,
                    "total_duplicates": total_duplicates,
                    "duplicate_groups": total_groups,
                    "space_saved_bytes": space_saved,
                    "space_saved_mb": space_saved / (1024 * 1024),
                    "duplicate_groups_detail": dict(list(duplicate_groups.items())[:20])  # 只返回前20组
                }
                
        except Exception as e:
            self.logger.error(f"获取重复文件报告失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def cleanup_duplicate_files(self, confirm: bool = False) -> Dict[str, Any]:
        """
        清理重复文件（删除重复文件，保留原始文件）
        
        Args:
            confirm: 是否确认删除
        
        Returns:
            Dict: 清理结果
        """
        if not confirm:
            return {
                "success": False,
                "error": "需要确认删除操作",
                "message": "请设置 confirm=True 来确认删除重复文件"
            }
        
        try:
            async with self.db_manager.get_async_session() as session:
                # 获取所有重复消息
                result = await session.execute(
                    select(Message).where(Message.is_duplicate == True)
                )
                
                duplicate_messages = result.scalars().all()
                
                deleted_count = 0
                space_freed = 0
                errors = []
                
                for msg in duplicate_messages:
                    try:
                        if msg.file_path:
                            file_path = Path(msg.file_path)
                            if file_path.exists():
                                file_size = file_path.stat().st_size
                                file_path.unlink()  # 删除文件
                                space_freed += file_size
                                deleted_count += 1
                                
                                self.logger.info(f"删除重复文件: {file_path}")
                    except Exception as e:
                        errors.append(f"删除文件失败 {msg.file_path}: {e}")
                
                return {
                    "success": True,
                    "deleted_files": deleted_count,
                    "space_freed_bytes": space_freed,
                    "space_freed_mb": space_freed / (1024 * 1024),
                    "errors": errors[:10]
                }
                
        except Exception as e:
            self.logger.error(f"清理重复文件失败: {e}")
            return {"success": False, "error": str(e)}
