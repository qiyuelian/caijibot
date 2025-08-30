# -*- coding: utf-8 -*-
"""
文件管理器
负责文件的组织、存储和管理
"""

import os
import shutil
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..database.database_manager import DatabaseManager
from ..database.models import Message, MediaType, MessageStatus
from ..config.settings import Settings
from ..utils.logger import LoggerMixin
from sqlalchemy import select, update


class FileManager(LoggerMixin):
    """文件管理器"""
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        初始化文件管理器
        
        Args:
            db_manager: 数据库管理器
            settings: 配置对象
        """
        self.db_manager = db_manager
        self.settings = settings
        
        # 存储路径配置
        self.base_storage_path = Path(settings.storage_path)
        self.temp_path = self.base_storage_path / "temp"
        
        # 按类型组织的存储路径
        self.storage_paths = {
            MediaType.VIDEO: self.base_storage_path / "videos",
            MediaType.IMAGE: self.base_storage_path / "images", 
            MediaType.AUDIO: self.base_storage_path / "audio",
            MediaType.DOCUMENT: self.base_storage_path / "documents"
        }
        
        self.logger.info("文件管理器初始化完成")
    
    async def initialize_storage(self):
        """初始化存储目录结构"""
        try:
            # 创建基础目录
            self.base_storage_path.mkdir(parents=True, exist_ok=True)
            self.temp_path.mkdir(parents=True, exist_ok=True)
            
            # 创建分类存储目录
            for media_type, path in self.storage_paths.items():
                path.mkdir(parents=True, exist_ok=True)
                
                # 创建按日期分组的子目录
                today = datetime.now()
                year_month_path = path / f"{today.year}" / f"{today.month:02d}"
                year_month_path.mkdir(parents=True, exist_ok=True)
            
            self.logger.info("存储目录结构初始化完成")
            
        except Exception as e:
            self.logger.error(f"初始化存储目录失败: {e}")
            raise
    
    def get_storage_path(self, media_type: MediaType, message_date: datetime = None) -> Path:
        """
        获取指定媒体类型的存储路径
        
        Args:
            media_type: 媒体类型
            message_date: 消息日期（用于按日期分组）
        
        Returns:
            Path: 存储路径
        """
        base_path = self.storage_paths.get(media_type, self.storage_paths[MediaType.DOCUMENT])
        
        if message_date:
            # 按年月分组
            year_month_path = base_path / f"{message_date.year}" / f"{message_date.month:02d}"
            year_month_path.mkdir(parents=True, exist_ok=True)
            return year_month_path
        
        return base_path
    
    def generate_safe_filename(self, original_filename: str, message_id: int) -> str:
        """
        生成安全的文件名
        
        Args:
            original_filename: 原始文件名
            message_id: 消息ID
        
        Returns:
            str: 安全的文件名
        """
        try:
            # 清理文件名中的非法字符
            safe_name = "".join(c for c in original_filename if c.isalnum() or c in ".-_()[]")
            
            # 如果文件名为空或过长，使用默认名称
            if not safe_name or len(safe_name) > 200:
                file_ext = Path(original_filename).suffix if original_filename else ""
                safe_name = f"file_{message_id}{file_ext}"
            
            # 确保文件名唯一性
            return f"{message_id}_{safe_name}"
            
        except Exception as e:
            self.logger.error(f"生成安全文件名失败: {e}")
            return f"file_{message_id}"
    
    async def organize_file(self, message: Message, temp_file_path: Path) -> Optional[Path]:
        """
        组织文件到正确的存储位置
        
        Args:
            message: 消息对象
            temp_file_path: 临时文件路径
        
        Returns:
            Optional[Path]: 最终文件路径
        """
        try:
            if not temp_file_path.exists():
                self.logger.error(f"临时文件不存在: {temp_file_path}")
                return None
            
            # 获取目标存储路径
            target_dir = self.get_storage_path(message.media_type, message.message_date)
            
            # 生成安全的文件名
            safe_filename = self.generate_safe_filename(message.file_name, message.id)
            target_path = target_dir / safe_filename
            
            # 如果目标文件已存在，添加序号
            counter = 1
            original_target = target_path
            while target_path.exists():
                stem = original_target.stem
                suffix = original_target.suffix
                target_path = original_target.parent / f"{stem}_{counter}{suffix}"
                counter += 1
            
            # 移动文件到目标位置
            shutil.move(str(temp_file_path), str(target_path))
            
            # 更新消息的文件路径
            await self._update_message_file_path(message.id, target_path)
            
            self.logger.info(f"文件组织完成: {temp_file_path.name} -> {target_path}")
            return target_path
            
        except Exception as e:
            self.logger.error(f"组织文件失败: {e}")
            return None
    
    async def _update_message_file_path(self, message_id: int, file_path: Path):
        """更新消息的文件路径"""
        try:
            async with self.db_manager.get_async_session() as session:
                await session.execute(
                    update(Message)
                    .where(Message.id == message_id)
                    .values(
                        file_path=str(file_path),
                        status=MessageStatus.COMPLETED
                    )
                )
                await session.commit()
        except Exception as e:
            self.logger.error(f"更新消息文件路径失败: {e}")
    
    async def get_storage_stats(self) -> Dict[str, Any]:
        """
        获取存储统计信息
        
        Returns:
            Dict: 存储统计
        """
        try:
            stats = {
                "total_files": 0,
                "total_size_bytes": 0,
                "by_type": {},
                "by_date": {},
                "storage_paths": {}
            }
            
            # 统计各类型文件
            for media_type, path in self.storage_paths.items():
                if path.exists():
                    type_stats = await self._get_directory_stats(path)
                    stats["by_type"][media_type.value] = type_stats
                    stats["total_files"] += type_stats["file_count"]
                    stats["total_size_bytes"] += type_stats["total_size"]
                    stats["storage_paths"][media_type.value] = str(path)
            
            # 转换大小单位
            stats["total_size_mb"] = stats["total_size_bytes"] / (1024 * 1024)
            stats["total_size_gb"] = stats["total_size_mb"] / 1024
            
            return stats
            
        except Exception as e:
            self.logger.error(f"获取存储统计失败: {e}")
            return {"error": str(e)}
    
    async def _get_directory_stats(self, directory: Path) -> Dict[str, Any]:
        """
        获取目录统计信息
        
        Args:
            directory: 目录路径
        
        Returns:
            Dict: 目录统计
        """
        try:
            file_count = 0
            total_size = 0
            
            if directory.exists():
                for file_path in directory.rglob("*"):
                    if file_path.is_file():
                        file_count += 1
                        total_size += file_path.stat().st_size
            
            return {
                "file_count": file_count,
                "total_size": total_size,
                "size_mb": total_size / (1024 * 1024)
            }
            
        except Exception as e:
            self.logger.error(f"获取目录统计失败: {e}")
            return {"file_count": 0, "total_size": 0, "size_mb": 0}
    
    async def cleanup_temp_files(self, max_age_hours: int = 24) -> Dict[str, Any]:
        """
        清理临时文件
        
        Args:
            max_age_hours: 最大保留时间（小时）
        
        Returns:
            Dict: 清理结果
        """
        try:
            if not self.temp_path.exists():
                return {"deleted_files": 0, "freed_space": 0}
            
            deleted_count = 0
            freed_space = 0
            current_time = datetime.now()
            
            for temp_file in self.temp_path.rglob("*"):
                if temp_file.is_file():
                    # 检查文件年龄
                    file_time = datetime.fromtimestamp(temp_file.stat().st_mtime)
                    age_hours = (current_time - file_time).total_seconds() / 3600
                    
                    if age_hours > max_age_hours:
                        file_size = temp_file.stat().st_size
                        temp_file.unlink()
                        deleted_count += 1
                        freed_space += file_size
                        
                        self.logger.debug(f"删除过期临时文件: {temp_file.name}")
            
            self.logger.info(f"临时文件清理完成: 删除 {deleted_count} 个文件，释放 {freed_space / (1024*1024):.1f} MB")
            
            return {
                "deleted_files": deleted_count,
                "freed_space": freed_space,
                "freed_space_mb": freed_space / (1024 * 1024)
            }
            
        except Exception as e:
            self.logger.error(f"清理临时文件失败: {e}")
            return {"error": str(e)}
    
    async def move_file(self, source_path: Path, target_path: Path) -> bool:
        """
        移动文件
        
        Args:
            source_path: 源文件路径
            target_path: 目标文件路径
        
        Returns:
            bool: 是否移动成功
        """
        try:
            if not source_path.exists():
                self.logger.error(f"源文件不存在: {source_path}")
                return False
            
            # 确保目标目录存在
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 移动文件
            shutil.move(str(source_path), str(target_path))
            
            self.logger.info(f"文件移动成功: {source_path.name} -> {target_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"移动文件失败: {e}")
            return False
    
    async def delete_file(self, file_path: Path, update_database: bool = True, message_id: int = None) -> bool:
        """
        删除文件
        
        Args:
            file_path: 文件路径
            update_database: 是否更新数据库
            message_id: 消息ID（用于更新数据库）
        
        Returns:
            bool: 是否删除成功
        """
        try:
            if not file_path.exists():
                self.logger.warning(f"文件不存在: {file_path}")
                return True  # 文件不存在也算删除成功
            
            # 删除文件
            file_path.unlink()
            
            # 更新数据库
            if update_database and message_id:
                async with self.db_manager.get_async_session() as session:
                    await session.execute(
                        update(Message)
                        .where(Message.id == message_id)
                        .values(
                            file_path=None,
                            status=MessageStatus.DELETED
                        )
                    )
                    await session.commit()
            
            self.logger.info(f"文件删除成功: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"删除文件失败: {e}")
            return False
    
    async def get_file_info(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        获取文件信息
        
        Args:
            file_path: 文件路径
        
        Returns:
            Optional[Dict]: 文件信息
        """
        try:
            if not file_path.exists():
                return None
            
            stat = file_path.stat()
            
            return {
                "name": file_path.name,
                "size": stat.st_size,
                "size_mb": stat.st_size / (1024 * 1024),
                "created_time": datetime.fromtimestamp(stat.st_ctime),
                "modified_time": datetime.fromtimestamp(stat.st_mtime),
                "extension": file_path.suffix.lower(),
                "is_file": file_path.is_file(),
                "absolute_path": str(file_path.absolute())
            }
            
        except Exception as e:
            self.logger.error(f"获取文件信息失败: {e}")
            return None
