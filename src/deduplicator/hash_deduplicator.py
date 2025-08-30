# -*- coding: utf-8 -*-
"""
哈希去重器
基于文件哈希值进行去重检测
"""

import hashlib
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import aiofiles

from ..database.database_manager import DatabaseManager
from ..database.models import Message, DuplicateRecord, MessageStatus
from ..utils.logger import LoggerMixin
from sqlalchemy import select, update


class HashDeduplicator(LoggerMixin):
    """哈希去重器"""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        初始化哈希去重器
        
        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.chunk_size = 8192  # 8KB chunks for file reading
        
        self.logger.info("哈希去重器初始化完成")
    
    async def calculate_file_hash(self, file_path: Path, algorithm: str = "md5") -> Optional[str]:
        """
        计算文件哈希值
        
        Args:
            file_path: 文件路径
            algorithm: 哈希算法 (md5, sha1, sha256)
        
        Returns:
            Optional[str]: 文件哈希值
        """
        if not file_path.exists():
            self.logger.warning(f"文件不存在: {file_path}")
            return None
        
        try:
            # 选择哈希算法
            if algorithm == "md5":
                hasher = hashlib.md5()
            elif algorithm == "sha1":
                hasher = hashlib.sha1()
            elif algorithm == "sha256":
                hasher = hashlib.sha256()
            else:
                self.logger.error(f"不支持的哈希算法: {algorithm}")
                return None
            
            # 异步读取文件并计算哈希
            async with aiofiles.open(file_path, 'rb') as f:
                while chunk := await f.read(self.chunk_size):
                    hasher.update(chunk)
            
            file_hash = hasher.hexdigest()
            self.logger.debug(f"计算文件哈希: {file_path.name} -> {file_hash}")
            return file_hash
            
        except Exception as e:
            self.logger.error(f"计算文件哈希失败: {e}")
            return None
    
    async def calculate_content_hash(self, content: bytes, algorithm: str = "md5") -> str:
        """
        计算内容哈希值
        
        Args:
            content: 文件内容
            algorithm: 哈希算法
        
        Returns:
            str: 内容哈希值
        """
        try:
            if algorithm == "md5":
                hasher = hashlib.md5()
            elif algorithm == "sha1":
                hasher = hashlib.sha1()
            elif algorithm == "sha256":
                hasher = hashlib.sha256()
            else:
                hasher = hashlib.md5()  # 默认使用MD5
            
            hasher.update(content)
            return hasher.hexdigest()
            
        except Exception as e:
            self.logger.error(f"计算内容哈希失败: {e}")
            return ""
    
    async def update_message_hash(self, message_id: int, file_path: Path) -> bool:
        """
        更新消息的文件哈希值
        
        Args:
            message_id: 消息ID
            file_path: 文件路径
        
        Returns:
            bool: 是否更新成功
        """
        try:
            # 计算文件哈希
            file_hash = await self.calculate_file_hash(file_path)
            if not file_hash:
                return False
            
            # 更新数据库
            async with self.db_manager.get_async_session() as session:
                await session.execute(
                    update(Message)
                    .where(Message.id == message_id)
                    .values(file_hash=file_hash)
                )
                await session.commit()
                
                self.logger.debug(f"更新消息 {message_id} 的哈希值: {file_hash}")
                return True
                
        except Exception as e:
            self.logger.error(f"更新消息哈希失败: {e}")
            return False
    
    async def find_duplicate_by_hash(self, file_hash: str) -> List[Message]:
        """
        根据哈希值查找重复文件
        
        Args:
            file_hash: 文件哈希值
        
        Returns:
            List[Message]: 重复的消息列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Message)
                    .where(
                        Message.file_hash == file_hash,
                        Message.status != MessageStatus.DUPLICATE
                    )
                    .order_by(Message.created_at.asc())
                )
                
                return result.scalars().all()
                
        except Exception as e:
            self.logger.error(f"查找重复文件失败: {e}")
            return []
    
    async def detect_duplicates(self, message: Message) -> List[Tuple[Message, float]]:
        """
        检测消息的重复文件
        
        Args:
            message: 要检测的消息
        
        Returns:
            List[Tuple[Message, float]]: 重复消息和相似度列表
        """
        if not message.file_hash:
            self.logger.debug(f"消息 {message.id} 没有文件哈希值")
            return []
        
        try:
            # 查找相同哈希的文件
            duplicates = await self.find_duplicate_by_hash(message.file_hash)
            
            # 排除自己
            duplicates = [msg for msg in duplicates if msg.id != message.id]
            
            # 哈希相同的文件相似度为1.0
            duplicate_pairs = [(msg, 1.0) for msg in duplicates]
            
            if duplicate_pairs:
                self.logger.info(f"消息 {message.id} 发现 {len(duplicate_pairs)} 个重复文件")
            
            return duplicate_pairs
            
        except Exception as e:
            self.logger.error(f"检测重复文件失败: {e}")
            return []
    
    async def mark_as_duplicate(
        self, 
        original_message: Message, 
        duplicate_message: Message,
        similarity_score: float = 1.0,
        action: str = "keep_original"
    ) -> bool:
        """
        标记消息为重复
        
        Args:
            original_message: 原始消息
            duplicate_message: 重复消息
            similarity_score: 相似度分数
            action: 处理动作
        
        Returns:
            bool: 是否标记成功
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 标记重复消息状态
                await session.execute(
                    update(Message)
                    .where(Message.id == duplicate_message.id)
                    .values(
                        status=MessageStatus.DUPLICATE,
                        is_duplicate=True,
                        original_message_id=original_message.id
                    )
                )
                
                # 创建去重记录
                duplicate_record = DuplicateRecord(
                    original_message_id=original_message.id,
                    duplicate_message_id=duplicate_message.id,
                    similarity_score=similarity_score,
                    similarity_type="hash",
                    action_taken=action,
                    reason="文件哈希值完全相同"
                )
                
                session.add(duplicate_record)
                await session.commit()
                
                self.logger.info(
                    f"标记重复文件: 原始={original_message.id}, 重复={duplicate_message.id}, "
                    f"相似度={similarity_score}"
                )
                
                return True
                
        except Exception as e:
            self.logger.error(f"标记重复文件失败: {e}")
            return False
    
    async def process_message_deduplication(self, message: Message) -> Dict[str, Any]:
        """
        处理单个消息的去重检测
        
        Args:
            message: 要处理的消息
        
        Returns:
            Dict: 处理结果
        """
        try:
            # 如果消息没有文件路径，跳过
            if not message.file_path:
                return {
                    "success": False,
                    "reason": "消息没有文件路径",
                    "duplicates_found": 0
                }
            
            file_path = Path(message.file_path)
            
            # 如果没有哈希值，先计算
            if not message.file_hash:
                success = await self.update_message_hash(message.id, file_path)
                if not success:
                    return {
                        "success": False,
                        "reason": "无法计算文件哈希值",
                        "duplicates_found": 0
                    }
                
                # 重新获取消息以获得更新的哈希值
                async with self.db_manager.get_async_session() as session:
                    result = await session.execute(
                        select(Message).where(Message.id == message.id)
                    )
                    message = result.scalar_one()
            
            # 检测重复文件
            duplicates = await self.detect_duplicates(message)
            
            if not duplicates:
                return {
                    "success": True,
                    "reason": "未发现重复文件",
                    "duplicates_found": 0
                }
            
            # 处理重复文件
            processed_count = 0
            for duplicate_msg, similarity in duplicates:
                # 选择保留策略：保留最早的文件
                if message.created_at < duplicate_msg.created_at:
                    # 当前消息更早，标记duplicate_msg为重复
                    success = await self.mark_as_duplicate(
                        message, duplicate_msg, similarity, "keep_original"
                    )
                else:
                    # duplicate_msg更早，标记当前消息为重复
                    success = await self.mark_as_duplicate(
                        duplicate_msg, message, similarity, "keep_original"
                    )
                
                if success:
                    processed_count += 1
            
            return {
                "success": True,
                "reason": f"处理了 {processed_count} 个重复文件",
                "duplicates_found": len(duplicates),
                "duplicates_processed": processed_count
            }
            
        except Exception as e:
            self.logger.error(f"处理消息去重失败: {e}")
            return {
                "success": False,
                "reason": f"处理出错: {str(e)}",
                "duplicates_found": 0
            }
    
    async def batch_process_deduplication(self, limit: int = 100) -> Dict[str, Any]:
        """
        批量处理去重检测
        
        Args:
            limit: 处理数量限制
        
        Returns:
            Dict: 批量处理结果
        """
        try:
            # 获取需要去重检测的消息
            async with self.db_manager.get_async_session() as session:
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
                    result = await self.process_message_deduplication(message)
                    total_processed += 1
                    
                    if result["success"]:
                        total_duplicates += result["duplicates_found"]
                    else:
                        errors.append(f"消息 {message.id}: {result['reason']}")
                    
                    # 避免过度占用资源
                    await asyncio.sleep(0.1)
                    
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
    
    async def get_deduplication_stats(self) -> Dict[str, Any]:
        """
        获取去重统计信息
        
        Returns:
            Dict: 统计信息
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 总消息数
                total_messages = await session.execute(
                    select(Message).where(Message.status == MessageStatus.COMPLETED)
                )
                total_count = len(total_messages.scalars().all())
                
                # 重复消息数
                duplicate_messages = await session.execute(
                    select(Message).where(Message.is_duplicate == True)
                )
                duplicate_count = len(duplicate_messages.scalars().all())
                
                # 去重记录数
                duplicate_records = await session.execute(select(DuplicateRecord))
                records_count = len(duplicate_records.scalars().all())
                
                # 有哈希值的消息数
                hashed_messages = await session.execute(
                    select(Message).where(Message.file_hash.isnot(None))
                )
                hashed_count = len(hashed_messages.scalars().all())
                
                return {
                    "total_messages": total_count,
                    "duplicate_messages": duplicate_count,
                    "unique_messages": total_count - duplicate_count,
                    "duplicate_records": records_count,
                    "hashed_messages": hashed_count,
                    "deduplication_rate": duplicate_count / total_count if total_count > 0 else 0
                }
                
        except Exception as e:
            self.logger.error(f"获取去重统计失败: {e}")
            return {"error": str(e)}
