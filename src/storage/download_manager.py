# -*- coding: utf-8 -*-
"""
下载管理器
负责文件的下载、队列管理和进度跟踪
"""

import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
import aiofiles

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from ..database.database_manager import DatabaseManager
from ..database.models import Message, MessageStatus
from ..config.settings import Settings
from ..utils.logger import LoggerMixin
from .file_manager import FileManager
from sqlalchemy import select, update


class DownloadTask:
    """下载任务"""
    
    def __init__(self, message: Message, priority: int = 0):
        self.message = message
        self.priority = priority
        self.created_at = datetime.utcnow()
        self.status = "pending"  # pending, downloading, completed, failed
        self.progress = 0.0
        self.error = None
        self.download_path = None


class DownloadManager(LoggerMixin):
    """下载管理器"""
    
    def __init__(
        self, 
        db_manager: DatabaseManager, 
        telegram_client: TelegramClient,
        file_manager: FileManager,
        settings: Settings
    ):
        """
        初始化下载管理器
        
        Args:
            db_manager: 数据库管理器
            telegram_client: Telegram客户端
            file_manager: 文件管理器
            settings: 配置对象
        """
        self.db_manager = db_manager
        self.client = telegram_client
        self.file_manager = file_manager
        self.settings = settings
        
        # 下载队列和状态
        self.download_queue = asyncio.Queue()
        self.active_downloads = {}  # message_id -> DownloadTask
        self.download_history = []  # 下载历史
        
        # 下载控制
        self.is_downloading = False
        self.max_concurrent_downloads = settings.max_concurrent_downloads
        self.download_semaphore = asyncio.Semaphore(self.max_concurrent_downloads)
        
        # 统计信息
        self.download_stats = {
            "total_queued": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_bytes_downloaded": 0,
            "start_time": None
        }
        
        self.logger.info(f"下载管理器初始化完成，最大并发下载数: {self.max_concurrent_downloads}")
    
    async def start_download_worker(self):
        """启动下载工作器"""
        if self.is_downloading:
            self.logger.warning("下载管理器已在运行中")
            return
        
        self.is_downloading = True
        self.download_stats["start_time"] = datetime.utcnow()
        self.logger.info("启动下载工作器")
        
        try:
            # 创建多个下载工作器
            workers = []
            for i in range(self.max_concurrent_downloads):
                worker = asyncio.create_task(self._download_worker(f"worker-{i}"))
                workers.append(worker)
            
            # 等待所有工作器完成
            await asyncio.gather(*workers, return_exceptions=True)
            
        except Exception as e:
            self.logger.error(f"下载工作器出错: {e}")
        finally:
            self.is_downloading = False
    
    async def stop_download_worker(self):
        """停止下载工作器"""
        self.is_downloading = False
        self.logger.info("停止下载工作器")
    
    async def add_download_task(self, message: Message, priority: int = 0) -> bool:
        """
        添加下载任务
        
        Args:
            message: 消息对象
            priority: 优先级（数字越大优先级越高）
        
        Returns:
            bool: 是否添加成功
        """
        try:
            # 检查消息是否已在下载队列中
            if message.id in self.active_downloads:
                self.logger.debug(f"消息 {message.id} 已在下载队列中")
                return False
            
            # 创建下载任务
            task = DownloadTask(message, priority)
            
            # 添加到队列
            await self.download_queue.put(task)
            self.active_downloads[message.id] = task
            self.download_stats["total_queued"] += 1
            
            self.logger.debug(f"添加下载任务: {message.file_name} (优先级: {priority})")
            return True
            
        except Exception as e:
            self.logger.error(f"添加下载任务失败: {e}")
            return False
    
    async def _download_worker(self, worker_name: str):
        """
        下载工作器
        
        Args:
            worker_name: 工作器名称
        """
        self.logger.info(f"下载工作器 {worker_name} 启动")
        
        while self.is_downloading:
            try:
                # 从队列获取任务（超时1秒）
                try:
                    task = await asyncio.wait_for(self.download_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # 执行下载
                async with self.download_semaphore:
                    await self._execute_download_task(task, worker_name)
                
                # 标记任务完成
                self.download_queue.task_done()
                
            except Exception as e:
                self.logger.error(f"下载工作器 {worker_name} 出错: {e}")
                await asyncio.sleep(1)
        
        self.logger.info(f"下载工作器 {worker_name} 停止")
    
    async def _execute_download_task(self, task: DownloadTask, worker_name: str):
        """
        执行下载任务
        
        Args:
            task: 下载任务
            worker_name: 工作器名称
        """
        message = task.message
        
        try:
            task.status = "downloading"
            self.logger.info(f"[{worker_name}] 开始下载: {message.file_name}")
            
            # 生成临时文件路径
            temp_filename = f"temp_{message.id}_{message.file_name}"
            temp_path = self.file_manager.temp_path / temp_filename
            
            # 下载文件
            download_path = await self._download_file_from_telegram(
                message.message_id,
                message.channel_id,
                temp_path,
                progress_callback=lambda current, total: self._update_progress(task, current, total)
            )
            
            if download_path:
                # 组织文件到正确位置
                final_path = await self.file_manager.organize_file(message, download_path)
                
                if final_path:
                    task.status = "completed"
                    task.download_path = final_path
                    task.progress = 1.0
                    
                    self.download_stats["total_completed"] += 1
                    self.download_stats["total_bytes_downloaded"] += message.file_size or 0
                    
                    self.logger.info(f"[{worker_name}] 下载完成: {message.file_name}")
                else:
                    raise Exception("文件组织失败")
            else:
                raise Exception("下载失败")
                
        except FloodWaitError as e:
            self.logger.warning(f"下载限流，等待 {e.seconds} 秒")
            task.status = "pending"  # 重新排队
            await self.download_queue.put(task)
            await asyncio.sleep(e.seconds)
            
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            self.download_stats["total_failed"] += 1
            
            self.logger.error(f"[{worker_name}] 下载失败: {message.file_name}, 错误: {e}")
            
            # 更新数据库状态
            await self._update_message_status(message.id, MessageStatus.FAILED, str(e))
        
        finally:
            # 从活跃下载中移除
            if message.id in self.active_downloads:
                del self.active_downloads[message.id]
            
            # 添加到历史记录
            self.download_history.append(task)
            
            # 保持历史记录在合理大小
            if len(self.download_history) > 1000:
                self.download_history = self.download_history[-500:]
    
    async def _download_file_from_telegram(
        self, 
        message_id: int, 
        channel_id: int, 
        download_path: Path,
        progress_callback: Optional[Callable] = None
    ) -> Optional[Path]:
        """
        从Telegram下载文件
        
        Args:
            message_id: 消息ID
            channel_id: 频道ID
            download_path: 下载路径
            progress_callback: 进度回调函数
        
        Returns:
            Optional[Path]: 下载的文件路径
        """
        try:
            # 获取频道实体
            channel_entity = await self.client.get_entity(int(channel_id))
            
            # 获取消息
            telegram_message = await self.client.get_messages(channel_entity, ids=message_id)
            if not telegram_message or not telegram_message.media:
                return None
            
            # 下载文件
            downloaded_path = await self.client.download_media(
                telegram_message.media,
                file=str(download_path),
                progress_callback=progress_callback
            )
            
            if downloaded_path:
                return Path(downloaded_path)
            else:
                return None
                
        except Exception as e:
            self.logger.error(f"从Telegram下载文件失败: {e}")
            return None
    
    def _update_progress(self, task: DownloadTask, current: int, total: int):
        """更新下载进度"""
        if total > 0:
            task.progress = current / total
    
    async def _update_message_status(self, message_id: int, status: MessageStatus, error: str = None):
        """更新消息状态"""
        try:
            update_data = {"status": status}
            if error:
                update_data["error_message"] = error
            
            async with self.db_manager.get_async_session() as session:
                await session.execute(
                    update(Message)
                    .where(Message.id == message_id)
                    .values(**update_data)
                )
                await session.commit()
        except Exception as e:
            self.logger.error(f"更新消息状态失败: {e}")
    
    async def get_download_stats(self) -> Dict[str, Any]:
        """
        获取下载统计信息
        
        Returns:
            Dict: 下载统计
        """
        try:
            # 基础统计
            stats = self.download_stats.copy()
            
            # 当前状态
            stats.update({
                "is_downloading": self.is_downloading,
                "queue_size": self.download_queue.qsize(),
                "active_downloads": len(self.active_downloads),
                "max_concurrent": self.max_concurrent_downloads
            })
            
            # 计算下载速度
            if stats["start_time"]:
                runtime = datetime.utcnow() - stats["start_time"]
                runtime_seconds = runtime.total_seconds()
                
                if runtime_seconds > 0:
                    stats["download_rate_mbps"] = (
                        stats["total_bytes_downloaded"] / (1024 * 1024) / runtime_seconds
                    )
                    stats["files_per_minute"] = stats["total_completed"] / (runtime_seconds / 60)
                
                stats["runtime_seconds"] = runtime_seconds
            
            # 转换字节单位
            stats["total_mb_downloaded"] = stats["total_bytes_downloaded"] / (1024 * 1024)
            stats["total_gb_downloaded"] = stats["total_mb_downloaded"] / 1024
            
            return stats
            
        except Exception as e:
            self.logger.error(f"获取下载统计失败: {e}")
            return {"error": str(e)}
    
    async def get_active_downloads_info(self) -> List[Dict[str, Any]]:
        """
        获取当前活跃下载信息
        
        Returns:
            List[Dict]: 活跃下载列表
        """
        try:
            active_info = []
            
            for message_id, task in self.active_downloads.items():
                active_info.append({
                    "message_id": message_id,
                    "file_name": task.message.file_name,
                    "file_size": task.message.file_size,
                    "media_type": task.message.media_type,
                    "status": task.status,
                    "progress": task.progress,
                    "priority": task.priority,
                    "started_at": task.created_at.isoformat()
                })
            
            # 按优先级和开始时间排序
            active_info.sort(key=lambda x: (-x["priority"], x["started_at"]))
            
            return active_info
            
        except Exception as e:
            self.logger.error(f"获取活跃下载信息失败: {e}")
            return []
    
    async def pause_downloads(self):
        """暂停所有下载"""
        self.is_downloading = False
        self.logger.info("暂停所有下载")
    
    async def resume_downloads(self):
        """恢复下载"""
        if not self.is_downloading:
            self.is_downloading = True
            # 重新启动工作器
            asyncio.create_task(self.start_download_worker())
            self.logger.info("恢复下载")
    
    async def clear_failed_downloads(self) -> int:
        """
        清理失败的下载任务
        
        Returns:
            int: 清理的任务数量
        """
        try:
            cleared_count = 0
            
            # 清理活跃下载中的失败任务
            failed_tasks = [
                message_id for message_id, task in self.active_downloads.items()
                if task.status == "failed"
            ]
            
            for message_id in failed_tasks:
                del self.active_downloads[message_id]
                cleared_count += 1
            
            # 清理历史记录中的失败任务
            self.download_history = [
                task for task in self.download_history
                if task.status != "failed"
            ]
            
            self.logger.info(f"清理了 {cleared_count} 个失败的下载任务")
            return cleared_count
            
        except Exception as e:
            self.logger.error(f"清理失败下载任务出错: {e}")
            return 0
    
    async def retry_failed_downloads(self) -> int:
        """
        重试失败的下载
        
        Returns:
            int: 重试的任务数量
        """
        try:
            # 获取失败的消息
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Message).where(
                        Message.status == MessageStatus.FAILED,
                        Message.file_path.is_(None)
                    ).limit(50)  # 限制重试数量
                )
                
                failed_messages = result.scalars().all()
            
            retry_count = 0
            for message in failed_messages:
                # 重新添加到下载队列
                success = await self.add_download_task(message, priority=1)  # 高优先级
                if success:
                    retry_count += 1
                    
                    # 重置消息状态
                    await self._update_message_status(message.id, MessageStatus.PENDING)
            
            self.logger.info(f"重试了 {retry_count} 个失败的下载任务")
            return retry_count
            
        except Exception as e:
            self.logger.error(f"重试失败下载出错: {e}")
            return 0
    
    async def queue_pending_downloads(self, limit: int = 100) -> int:
        """
        将待下载的消息加入队列
        
        Args:
            limit: 限制数量
        
        Returns:
            int: 加入队列的任务数量
        """
        try:
            # 获取待下载的消息
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Message).where(
                        Message.status == MessageStatus.PENDING,
                        Message.is_duplicate == False
                    ).limit(limit).order_by(Message.created_at.asc())
                )
                
                pending_messages = result.scalars().all()
            
            queued_count = 0
            for message in pending_messages:
                success = await self.add_download_task(message)
                if success:
                    queued_count += 1
            
            self.logger.info(f"将 {queued_count} 个消息加入下载队列")
            return queued_count
            
        except Exception as e:
            self.logger.error(f"队列待下载消息失败: {e}")
            return 0
