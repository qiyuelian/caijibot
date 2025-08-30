# -*- coding: utf-8 -*-
"""
存储监控器
监控存储空间使用情况和性能指标
"""

import asyncio
import shutil
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime, timedelta

from ..database.database_manager import DatabaseManager
from ..database.models import Message, MediaType, MessageStatus
from ..config.settings import Settings
from ..utils.logger import LoggerMixin
from sqlalchemy import select, func


class StorageMonitor(LoggerMixin):
    """存储监控器"""
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        初始化存储监控器
        
        Args:
            db_manager: 数据库管理器
            settings: 配置对象
        """
        self.db_manager = db_manager
        self.settings = settings
        self.storage_path = Path(settings.storage_path)
        
        # 监控状态
        self.is_monitoring = False
        self.last_check_time = None
        
        # 警告阈值
        self.space_warning_threshold = 0.8  # 80%使用率警告
        self.space_critical_threshold = 0.9  # 90%使用率严重警告
        
        self.logger.info("存储监控器初始化完成")
    
    async def start_monitoring(self, check_interval_minutes: int = 30):
        """
        开始存储监控
        
        Args:
            check_interval_minutes: 检查间隔（分钟）
        """
        if self.is_monitoring:
            self.logger.warning("存储监控器已在运行中")
            return
        
        self.is_monitoring = True
        self.logger.info(f"开始存储监控，检查间隔: {check_interval_minutes} 分钟")
        
        try:
            while self.is_monitoring:
                await self._perform_storage_check()
                self.last_check_time = datetime.utcnow()
                
                # 等待下次检查
                await asyncio.sleep(check_interval_minutes * 60)
                
        except Exception as e:
            self.logger.error(f"存储监控出错: {e}")
        finally:
            self.is_monitoring = False
    
    async def stop_monitoring(self):
        """停止存储监控"""
        self.is_monitoring = False
        self.logger.info("停止存储监控")
    
    async def _perform_storage_check(self):
        """执行存储检查"""
        try:
            # 检查磁盘空间
            disk_info = await self.get_disk_usage()
            
            # 检查存储使用情况
            storage_info = await self.get_storage_usage()
            
            # 检查是否需要警告
            usage_ratio = disk_info["used"] / disk_info["total"] if disk_info["total"] > 0 else 0
            
            if usage_ratio >= self.space_critical_threshold:
                self.logger.critical(
                    f"存储空间严重不足！使用率: {usage_ratio:.1%}, "
                    f"剩余: {disk_info['free'] / (1024**3):.1f} GB"
                )
                # TODO: 发送紧急通知
                
            elif usage_ratio >= self.space_warning_threshold:
                self.logger.warning(
                    f"存储空间不足警告！使用率: {usage_ratio:.1%}, "
                    f"剩余: {disk_info['free'] / (1024**3):.1f} GB"
                )
                # TODO: 发送警告通知
            
            # 记录监控日志
            self.logger.info(
                f"存储检查完成 - 磁盘使用率: {usage_ratio:.1%}, "
                f"项目文件: {storage_info['total_files']} 个, "
                f"占用空间: {storage_info['total_size_gb']:.1f} GB"
            )
            
        except Exception as e:
            self.logger.error(f"存储检查失败: {e}")
    
    async def get_disk_usage(self) -> Dict[str, int]:
        """
        获取磁盘使用情况
        
        Returns:
            Dict: 磁盘使用信息（字节）
        """
        try:
            usage = shutil.disk_usage(self.storage_path)
            
            return {
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "usage_ratio": usage.used / usage.total if usage.total > 0 else 0
            }
            
        except Exception as e:
            self.logger.error(f"获取磁盘使用情况失败: {e}")
            return {"total": 0, "used": 0, "free": 0, "usage_ratio": 0}
    
    async def get_storage_usage(self) -> Dict[str, Any]:
        """
        获取项目存储使用情况
        
        Returns:
            Dict: 存储使用信息
        """
        try:
            total_size = 0
            total_files = 0
            by_type = {}
            
            if self.storage_path.exists():
                for item in self.storage_path.rglob("*"):
                    if item.is_file():
                        file_size = item.stat().st_size
                        total_size += file_size
                        total_files += 1
                        
                        # 按文件类型统计
                        file_ext = item.suffix.lower()
                        if file_ext not in by_type:
                            by_type[file_ext] = {"count": 0, "size": 0}
                        
                        by_type[file_ext]["count"] += 1
                        by_type[file_ext]["size"] += file_size
            
            # 转换单位
            for ext_info in by_type.values():
                ext_info["size_mb"] = ext_info["size"] / (1024 * 1024)
            
            return {
                "total_files": total_files,
                "total_size": total_size,
                "total_size_mb": total_size / (1024 * 1024),
                "total_size_gb": total_size / (1024 * 1024 * 1024),
                "by_extension": by_type,
                "storage_path": str(self.storage_path)
            }
            
        except Exception as e:
            self.logger.error(f"获取存储使用情况失败: {e}")
            return {"error": str(e)}
    
    async def get_database_storage_stats(self) -> Dict[str, Any]:
        """
        获取数据库中的存储统计
        
        Returns:
            Dict: 数据库存储统计
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 按媒体类型统计
                type_stats = {}
                for media_type in MediaType:
                    # 文件数量
                    count_result = await session.execute(
                        select(func.count(Message.id)).where(
                            Message.media_type == media_type,
                            Message.status == MessageStatus.COMPLETED
                        )
                    )
                    file_count = count_result.scalar()
                    
                    # 文件大小总计
                    size_result = await session.execute(
                        select(func.sum(Message.file_size)).where(
                            Message.media_type == media_type,
                            Message.status == MessageStatus.COMPLETED
                        )
                    )
                    total_size = size_result.scalar() or 0
                    
                    type_stats[media_type.value] = {
                        "file_count": file_count,
                        "total_size": total_size,
                        "total_size_mb": total_size / (1024 * 1024)
                    }
                
                # 总体统计
                total_files = await session.execute(
                    select(func.count(Message.id)).where(
                        Message.status == MessageStatus.COMPLETED
                    )
                )
                total_files = total_files.scalar()
                
                total_size = await session.execute(
                    select(func.sum(Message.file_size)).where(
                        Message.status == MessageStatus.COMPLETED
                    )
                )
                total_size = total_size.scalar() or 0
                
                return {
                    "total_files": total_files,
                    "total_size": total_size,
                    "total_size_mb": total_size / (1024 * 1024),
                    "total_size_gb": total_size / (1024 * 1024 * 1024),
                    "by_media_type": type_stats
                }
                
        except Exception as e:
            self.logger.error(f"获取数据库存储统计失败: {e}")
            return {"error": str(e)}
    
    async def cleanup_old_files(self, days: int = 30) -> Dict[str, Any]:
        """
        清理旧文件
        
        Args:
            days: 保留天数
        
        Returns:
            Dict: 清理结果
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            deleted_count = 0
            freed_space = 0
            
            if self.storage_path.exists():
                for file_path in self.storage_path.rglob("*"):
                    if file_path.is_file():
                        # 检查文件修改时间
                        file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
                        
                        if file_time < cutoff_date:
                            file_size = file_path.stat().st_size
                            file_path.unlink()
                            deleted_count += 1
                            freed_space += file_size
                            
                            self.logger.debug(f"删除旧文件: {file_path.name}")
            
            self.logger.info(
                f"清理旧文件完成: 删除 {deleted_count} 个文件，"
                f"释放 {freed_space / (1024*1024):.1f} MB"
            )
            
            return {
                "deleted_files": deleted_count,
                "freed_space": freed_space,
                "freed_space_mb": freed_space / (1024 * 1024),
                "cutoff_date": cutoff_date.isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"清理旧文件失败: {e}")
            return {"error": str(e)}
    
    async def get_comprehensive_report(self) -> Dict[str, Any]:
        """
        获取综合存储报告
        
        Returns:
            Dict: 综合报告
        """
        try:
            # 获取各种统计信息
            disk_usage = await self.get_disk_usage()
            storage_usage = await self.get_storage_usage()
            db_stats = await self.get_database_storage_stats()
            
            # 计算一致性检查
            db_total_size = db_stats.get("total_size", 0)
            actual_total_size = storage_usage.get("total_size", 0)
            size_difference = abs(db_total_size - actual_total_size)
            
            return {
                "disk_usage": disk_usage,
                "storage_usage": storage_usage,
                "database_stats": db_stats,
                "consistency_check": {
                    "db_total_size": db_total_size,
                    "actual_total_size": actual_total_size,
                    "size_difference": size_difference,
                    "size_difference_mb": size_difference / (1024 * 1024),
                    "is_consistent": size_difference < (100 * 1024 * 1024)  # 100MB差异内认为一致
                },
                "monitoring_status": {
                    "is_monitoring": self.is_monitoring,
                    "last_check_time": self.last_check_time.isoformat() if self.last_check_time else None
                },
                "generated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"生成综合报告失败: {e}")
            return {"error": str(e)}
