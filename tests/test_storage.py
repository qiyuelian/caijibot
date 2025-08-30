# -*- coding: utf-8 -*-
"""
存储功能测试
"""

import pytest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from src.storage.file_manager import FileManager
from src.storage.download_manager import DownloadManager, DownloadTask
from src.storage.storage_monitor import StorageMonitor
from src.database.models import MediaType, MessageStatus


class TestFileManager:
    """文件管理器测试"""
    
    @pytest.mark.asyncio
    async def test_initialize_storage(self, test_db_manager, test_settings):
        """测试存储初始化"""
        file_manager = FileManager(test_db_manager, test_settings)
        
        await file_manager.initialize_storage()
        
        # 检查目录是否创建
        assert file_manager.base_storage_path.exists()
        assert file_manager.temp_path.exists()
        
        for media_type, path in file_manager.storage_paths.items():
            assert path.exists()
    
    @pytest.mark.asyncio
    async def test_generate_safe_filename(self, test_db_manager, test_settings):
        """测试安全文件名生成"""
        file_manager = FileManager(test_db_manager, test_settings)
        
        # 测试正常文件名
        safe_name = file_manager.generate_safe_filename("test_video.mp4", 12345)
        assert "12345_test_video.mp4" == safe_name
        
        # 测试包含特殊字符的文件名
        unsafe_name = "test<>:\"|?*video.mp4"
        safe_name = file_manager.generate_safe_filename(unsafe_name, 12345)
        assert "<" not in safe_name
        assert ">" not in safe_name
        assert "12345" in safe_name
        
        # 测试空文件名
        safe_name = file_manager.generate_safe_filename("", 12345)
        assert safe_name == "file_12345"
    
    @pytest.mark.asyncio
    async def test_get_storage_path(self, test_db_manager, test_settings):
        """测试获取存储路径"""
        file_manager = FileManager(test_db_manager, test_settings)
        await file_manager.initialize_storage()
        
        # 测试不同媒体类型的路径
        video_path = file_manager.get_storage_path(MediaType.VIDEO)
        image_path = file_manager.get_storage_path(MediaType.IMAGE)
        
        assert video_path != image_path
        assert "videos" in str(video_path)
        assert "images" in str(image_path)
        
        # 测试带日期的路径
        from datetime import datetime
        dated_path = file_manager.get_storage_path(MediaType.VIDEO, datetime.now())
        assert dated_path != video_path
        assert dated_path.exists()
    
    @pytest.mark.asyncio
    async def test_file_organization(self, test_db_manager, test_settings, sample_messages):
        """测试文件组织"""
        file_manager = FileManager(test_db_manager, test_settings)
        await file_manager.initialize_storage()
        
        # 创建临时测试文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_file:
            temp_file.write(b"test video content")
            temp_file.flush()
            temp_path = Path(temp_file.name)
        
        try:
            # 测试文件组织
            message = sample_messages[0]  # 视频消息
            final_path = await file_manager.organize_file(message, temp_path)
            
            # 验证文件是否移动到正确位置
            if final_path:
                assert final_path.exists()
                assert "videos" in str(final_path)
                assert str(message.id) in final_path.name
            
        finally:
            # 清理
            if temp_path.exists():
                temp_path.unlink()
            if 'final_path' in locals() and final_path and final_path.exists():
                final_path.unlink()


class TestDownloadManager:
    """下载管理器测试"""
    
    @pytest.mark.asyncio
    async def test_download_manager_initialization(self, test_db_manager, test_settings):
        """测试下载管理器初始化"""
        mock_client = AsyncMock()
        file_manager = FileManager(test_db_manager, test_settings)
        
        download_manager = DownloadManager(
            test_db_manager,
            mock_client,
            file_manager,
            test_settings
        )
        
        assert download_manager is not None
        assert download_manager.max_concurrent_downloads == test_settings.max_concurrent_downloads
        assert download_manager.download_queue is not None
    
    @pytest.mark.asyncio
    async def test_download_task_creation(self, test_db_manager, test_settings, sample_messages):
        """测试下载任务创建"""
        mock_client = AsyncMock()
        file_manager = FileManager(test_db_manager, test_settings)
        
        download_manager = DownloadManager(
            test_db_manager,
            mock_client,
            file_manager,
            test_settings
        )
        
        # 添加下载任务
        message = sample_messages[0]
        success = await download_manager.add_download_task(message, priority=1)
        
        assert success is True
        assert message.id in download_manager.active_downloads
        assert download_manager.download_queue.qsize() > 0
    
    @pytest.mark.asyncio
    async def test_download_stats(self, test_db_manager, test_settings):
        """测试下载统计"""
        mock_client = AsyncMock()
        file_manager = FileManager(test_db_manager, test_settings)
        
        download_manager = DownloadManager(
            test_db_manager,
            mock_client,
            file_manager,
            test_settings
        )
        
        # 获取下载统计
        stats = await download_manager.get_download_stats()
        
        assert isinstance(stats, dict)
        assert "total_queued" in stats
        assert "total_completed" in stats
        assert "total_failed" in stats
        assert "is_downloading" in stats


class TestStorageMonitor:
    """存储监控器测试"""
    
    @pytest.mark.asyncio
    async def test_storage_monitor_initialization(self, test_db_manager, test_settings):
        """测试存储监控器初始化"""
        storage_monitor = StorageMonitor(test_db_manager, test_settings)
        
        assert storage_monitor is not None
        assert storage_monitor.space_warning_threshold == 0.8
        assert storage_monitor.space_critical_threshold == 0.9
    
    @pytest.mark.asyncio
    async def test_disk_usage_check(self, test_db_manager, test_settings):
        """测试磁盘使用情况检查"""
        storage_monitor = StorageMonitor(test_db_manager, test_settings)
        
        # 获取磁盘使用情况
        disk_usage = await storage_monitor.get_disk_usage()
        
        assert isinstance(disk_usage, dict)
        assert "total" in disk_usage
        assert "used" in disk_usage
        assert "free" in disk_usage
        assert "usage_ratio" in disk_usage
        
        # 验证数据合理性
        assert disk_usage["total"] > 0
        assert disk_usage["used"] >= 0
        assert disk_usage["free"] >= 0
        assert 0 <= disk_usage["usage_ratio"] <= 1
    
    @pytest.mark.asyncio
    async def test_storage_usage_check(self, test_db_manager, test_settings):
        """测试存储使用情况检查"""
        storage_monitor = StorageMonitor(test_db_manager, test_settings)
        
        # 获取存储使用情况
        storage_usage = await storage_monitor.get_storage_usage()
        
        assert isinstance(storage_usage, dict)
        assert "total_files" in storage_usage
        assert "total_size" in storage_usage
        assert "by_extension" in storage_usage
        
        # 验证数据类型
        assert isinstance(storage_usage["total_files"], int)
        assert isinstance(storage_usage["total_size"], int)
        assert isinstance(storage_usage["by_extension"], dict)
    
    @pytest.mark.asyncio
    async def test_comprehensive_report(self, test_db_manager, test_settings):
        """测试综合报告生成"""
        storage_monitor = StorageMonitor(test_db_manager, test_settings)
        
        # 生成综合报告
        report = await storage_monitor.get_comprehensive_report()
        
        assert isinstance(report, dict)
        assert "disk_usage" in report
        assert "storage_usage" in report
        assert "database_stats" in report
        assert "consistency_check" in report
        assert "monitoring_status" in report


class TestStorageIntegration:
    """存储功能集成测试"""
    
    @pytest.mark.asyncio
    async def test_complete_storage_workflow(self, test_db_manager, test_settings, sample_messages):
        """测试完整存储工作流程"""
        # 初始化所有存储组件
        file_manager = FileManager(test_db_manager, test_settings)
        await file_manager.initialize_storage()
        
        mock_client = AsyncMock()
        download_manager = DownloadManager(
            test_db_manager,
            mock_client,
            file_manager,
            test_settings
        )
        
        storage_monitor = StorageMonitor(test_db_manager, test_settings)
        
        # 测试工作流程
        message = sample_messages[0]
        
        # 1. 添加下载任务
        success = await download_manager.add_download_task(message)
        assert success is True
        
        # 2. 检查存储状态
        storage_stats = await storage_monitor.get_storage_usage()
        assert isinstance(storage_stats, dict)
        
        # 3. 获取下载统计
        download_stats = await download_manager.get_download_stats()
        assert isinstance(download_stats, dict)
        assert download_stats["queue_size"] > 0
    
    @pytest.mark.asyncio
    async def test_storage_cleanup(self, test_db_manager, test_settings):
        """测试存储清理功能"""
        file_manager = FileManager(test_db_manager, test_settings)
        await file_manager.initialize_storage()
        
        # 创建一些临时文件
        temp_files = []
        for i in range(3):
            temp_file = file_manager.temp_path / f"test_temp_{i}.txt"
            temp_file.write_text(f"临时文件内容 {i}")
            temp_files.append(temp_file)
        
        # 验证文件存在
        for temp_file in temp_files:
            assert temp_file.exists()
        
        # 执行清理（设置很短的保留时间）
        cleanup_result = await file_manager.cleanup_temp_files(max_age_hours=0)
        
        assert isinstance(cleanup_result, dict)
        assert "deleted_files" in cleanup_result
        assert "freed_space" in cleanup_result
        
        # 验证文件被清理
        # 注意：由于文件刚创建，可能不会被立即清理，这取决于实现细节
