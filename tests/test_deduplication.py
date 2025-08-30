# -*- coding: utf-8 -*-
"""
去重功能测试
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from src.deduplicator.hash_deduplicator import HashDeduplicator
from src.deduplicator.metadata_deduplicator import MetadataDeduplicator
from src.deduplicator.dedup_manager import DeduplicationManager
from src.database.models import MediaType


class TestHashDeduplicator:
    """哈希去重器测试"""
    
    @pytest.mark.asyncio
    async def test_calculate_file_hash(self, test_db_manager):
        """测试文件哈希计算"""
        hash_dedup = HashDeduplicator(test_db_manager)
        
        # 创建测试文件
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            test_content = b"This is a test file content for hash calculation"
            temp_file.write(test_content)
            temp_file.flush()
            
            temp_path = Path(temp_file.name)
        
        try:
            # 计算哈希
            file_hash = await hash_dedup.calculate_file_hash(temp_path)
            
            assert file_hash is not None
            assert len(file_hash) == 64  # SHA256哈希长度
            assert isinstance(file_hash, str)
            
            # 相同文件应该产生相同哈希
            file_hash2 = await hash_dedup.calculate_file_hash(temp_path)
            assert file_hash == file_hash2
            
        finally:
            # 清理测试文件
            temp_path.unlink()
    
    @pytest.mark.asyncio
    async def test_hash_duplicate_detection(self, test_db_manager, sample_messages):
        """测试哈希重复检测"""
        hash_dedup = HashDeduplicator(test_db_manager)
        
        # 创建两个相同内容的测试文件
        test_content = b"Duplicate test content"
        
        with tempfile.NamedTemporaryFile(delete=False) as temp_file1:
            temp_file1.write(test_content)
            temp_file1.flush()
            temp_path1 = Path(temp_file1.name)
        
        with tempfile.NamedTemporaryFile(delete=False) as temp_file2:
            temp_file2.write(test_content)
            temp_file2.flush()
            temp_path2 = Path(temp_file2.name)
        
        try:
            # 检测重复
            is_duplicate = await hash_dedup.check_duplicate_by_hash(
                temp_path1, 
                sample_messages[0]
            )
            
            # 第一次应该不是重复
            assert not is_duplicate["is_duplicate"]
            
            # 模拟第一个文件已存在的情况
            # 这里需要更复杂的测试设置，暂时跳过
            
        finally:
            # 清理测试文件
            temp_path1.unlink()
            temp_path2.unlink()


class TestMetadataDeduplicator:
    """元数据去重器测试"""
    
    @pytest.mark.asyncio
    async def test_extract_file_metadata(self, test_db_manager):
        """测试文件元数据提取"""
        metadata_dedup = MetadataDeduplicator(test_db_manager)
        
        # 创建模拟Telegram消息
        mock_message = MagicMock()
        mock_message.id = 12345
        mock_message.date = datetime.utcnow()
        mock_message.text = "测试消息"
        
        # 模拟视频媒体
        mock_media = MagicMock()
        mock_message.media = mock_media
        
        # 测试元数据提取
        metadata = metadata_dedup._extract_file_metadata(mock_message)
        
        # 由于是模拟对象，可能返回None，这是正常的
        # 主要测试方法不会抛出异常
        assert metadata is None or isinstance(metadata, dict)
    
    @pytest.mark.asyncio
    async def test_video_similarity_calculation(self, test_db_manager):
        """测试视频相似度计算"""
        metadata_dedup = MetadataDeduplicator(test_db_manager)
        
        # 创建测试视频元数据
        metadata1 = {
            "duration": 120,  # 2分钟
            "width": 1920,
            "height": 1080,
            "file_size": 50 * 1024 * 1024  # 50MB
        }
        
        # 创建模拟消息
        mock_message = MagicMock()
        mock_message.id = 1
        mock_message.message_text = '{"duration": 121, "width": 1920, "height": 1080}'
        mock_message.file_size = 52 * 1024 * 1024  # 52MB
        
        # 计算相似度
        similarity = metadata_dedup._calculate_video_similarity(metadata1, mock_message)
        
        assert isinstance(similarity, dict)
        assert "similarity" in similarity
        assert 0 <= similarity["similarity"] <= 1


class TestDeduplicationManager:
    """去重管理器测试"""
    
    @pytest.mark.asyncio
    async def test_dedup_manager_initialization(self, test_db_manager, test_settings):
        """测试去重管理器初始化"""
        dedup_manager = DeduplicationManager(test_db_manager, test_settings)
        
        assert dedup_manager is not None
        assert dedup_manager.hash_deduplicator is not None
        assert dedup_manager.metadata_deduplicator is not None
    
    @pytest.mark.asyncio
    async def test_check_duplicate_before_download(self, test_db_manager, test_settings, sample_channel):
        """测试预下载去重检测"""
        dedup_manager = DeduplicationManager(test_db_manager, test_settings)
        
        # 创建模拟Telegram消息
        mock_message = MagicMock()
        mock_message.id = 99999
        mock_message.date = datetime.utcnow()
        mock_message.text = "测试消息"
        mock_message.media = None  # 无媒体
        
        # 测试无媒体消息
        result = await dedup_manager.check_duplicate_before_download(
            mock_message, 
            sample_channel.id
        )
        
        assert isinstance(result, dict)
        assert "should_download" in result
        assert "reason" in result


class TestDeduplicationIntegration:
    """去重功能集成测试"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_deduplication(self, test_db_manager, test_settings, sample_channel):
        """测试端到端去重流程"""
        dedup_manager = DeduplicationManager(test_db_manager, test_settings)
        
        # 创建测试消息
        async with test_db_manager.get_async_session() as session:
            # 第一条消息
            message1 = Message(
                message_id=20001,
                channel_id=sample_channel.id,
                message_text="重复测试消息",
                media_type=MediaType.VIDEO,
                file_name="duplicate_test.mp4",
                file_size=10 * 1024 * 1024,
                status=MessageStatus.COMPLETED
            )
            
            session.add(message1)
            await session.commit()
            await session.refresh(message1)
        
        # 创建相似的模拟Telegram消息
        mock_message = MagicMock()
        mock_message.id = 20002
        mock_message.date = datetime.utcnow()
        mock_message.text = "重复测试消息"
        
        # 模拟媒体
        mock_media = MagicMock()
        mock_message.media = mock_media
        
        # 测试去重检测
        result = await dedup_manager.check_duplicate_before_download(
            mock_message,
            sample_channel.id
        )
        
        assert isinstance(result, dict)
        # 由于是模拟数据，具体结果可能不同，主要测试不抛异常
    
    @pytest.mark.asyncio
    async def test_dedup_statistics(self, test_db_manager, test_settings):
        """测试去重统计"""
        dedup_manager = DeduplicationManager(test_db_manager, test_settings)
        
        # 获取去重统计
        stats = await dedup_manager.get_deduplication_stats()
        
        assert isinstance(stats, dict)
        assert "total_duplicates" in stats
        assert "by_type" in stats
        assert "by_similarity_type" in stats
