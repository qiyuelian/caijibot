# -*- coding: utf-8 -*-
"""
标签统计功能测试
"""

import pytest
from datetime import datetime

from src.statistics.tag_statistics import TagStatistics
from src.database.models import Message, Tag, MessageTag, MediaType, MessageStatus


class TestTagStatistics:
    """标签统计测试"""
    
    @pytest.mark.asyncio
    async def test_tag_statistics_initialization(self, test_db_manager):
        """测试标签统计管理器初始化"""
        tag_stats = TagStatistics(test_db_manager)
        
        assert tag_stats is not None
        assert tag_stats.db_manager == test_db_manager
    
    @pytest.mark.asyncio
    async def test_get_tag_media_stats(self, test_db_manager, sample_channel, sample_tags):
        """测试获取标签媒体统计"""
        tag_stats = TagStatistics(test_db_manager)
        
        # 创建测试消息和标签关系
        async with test_db_manager.get_async_session() as session:
            # 创建测试消息
            messages = [
                Message(
                    message_id=30001,
                    channel_id=sample_channel.id,
                    message_text="测试视频1",
                    media_type=MediaType.VIDEO,
                    file_name="test_video1.mp4",
                    file_size=10 * 1024 * 1024,
                    status=MessageStatus.COMPLETED
                ),
                Message(
                    message_id=30002,
                    channel_id=sample_channel.id,
                    message_text="测试图片1",
                    media_type=MediaType.IMAGE,
                    file_name="test_image1.jpg",
                    file_size=2 * 1024 * 1024,
                    status=MessageStatus.COMPLETED
                )
            ]
            
            for message in messages:
                session.add(message)
            
            await session.commit()
            
            # 刷新获取ID
            for message in messages:
                await session.refresh(message)
            
            # 创建标签关系
            tag = sample_tags[0]  # 使用第一个标签
            
            for message in messages:
                message_tag = MessageTag(
                    message_id=message.id,
                    tag_id=tag.id
                )
                session.add(message_tag)
            
            await session.commit()
        
        # 测试获取标签统计
        stats = await tag_stats.get_tag_media_stats(tag_name=tag.name)
        
        assert "error" not in stats
        assert "tag_info" in stats
        assert "media_stats" in stats
        assert stats["tag_info"]["name"] == tag.name
        assert stats["total_files"] == 2
        
        # 检查媒体统计
        media_stats = stats["media_stats"]
        assert media_stats["video"]["count"] == 1
        assert media_stats["image"]["count"] == 1
        assert media_stats["audio"]["count"] == 0
        assert media_stats["document"]["count"] == 0
    
    @pytest.mark.asyncio
    async def test_get_all_tags_media_summary(self, test_db_manager, sample_tags):
        """测试获取所有标签媒体摘要"""
        tag_stats = TagStatistics(test_db_manager)
        
        # 获取摘要
        summary = await tag_stats.get_all_tags_media_summary(limit=10)
        
        assert isinstance(summary, dict)
        assert "total_tags" in summary
        assert "tags_summary" in summary
        assert "overall_stats" in summary
        
        # 验证数据结构
        assert isinstance(summary["tags_summary"], list)
        assert isinstance(summary["overall_stats"], dict)
    
    @pytest.mark.asyncio
    async def test_get_media_type_by_tags(self, test_db_manager, sample_channel, sample_tags):
        """测试获取媒体类型标签分布"""
        tag_stats = TagStatistics(test_db_manager)
        
        # 创建测试数据
        async with test_db_manager.get_async_session() as session:
            # 创建视频消息
            video_message = Message(
                message_id=40001,
                channel_id=sample_channel.id,
                message_text="测试视频",
                media_type=MediaType.VIDEO,
                file_name="test_video.mp4",
                file_size=10 * 1024 * 1024,
                status=MessageStatus.COMPLETED
            )
            
            session.add(video_message)
            await session.commit()
            await session.refresh(video_message)
            
            # 创建标签关系
            tag = sample_tags[0]
            message_tag = MessageTag(
                message_id=video_message.id,
                tag_id=tag.id
            )
            session.add(message_tag)
            await session.commit()
        
        # 测试获取视频类型的标签分布
        distribution = await tag_stats.get_media_type_by_tags(MediaType.VIDEO, limit=5)
        
        assert "error" not in distribution
        assert "media_type" in distribution
        assert "total_count" in distribution
        assert "tag_distribution" in distribution
        
        assert distribution["media_type"] == "video"
        assert distribution["total_count"] >= 1
        assert isinstance(distribution["tag_distribution"], list)
    
    @pytest.mark.asyncio
    async def test_search_tags_by_media_count(self, test_db_manager, sample_channel, sample_tags):
        """测试按媒体数量搜索标签"""
        tag_stats = TagStatistics(test_db_manager)
        
        # 创建测试数据
        async with test_db_manager.get_async_session() as session:
            # 创建多个图片消息
            for i in range(3):
                image_message = Message(
                    message_id=50001 + i,
                    channel_id=sample_channel.id,
                    message_text=f"测试图片{i}",
                    media_type=MediaType.IMAGE,
                    file_name=f"test_image{i}.jpg",
                    file_size=2 * 1024 * 1024,
                    status=MessageStatus.COMPLETED
                )
                
                session.add(image_message)
                await session.commit()
                await session.refresh(image_message)
                
                # 关联到第一个标签
                tag = sample_tags[0]
                message_tag = MessageTag(
                    message_id=image_message.id,
                    tag_id=tag.id
                )
                session.add(message_tag)
            
            await session.commit()
        
        # 搜索包含图片的标签
        tags_with_images = await tag_stats.search_tags_by_media_count(
            MediaType.IMAGE, 
            min_count=1, 
            limit=10
        )
        
        assert isinstance(tags_with_images, list)
        if tags_with_images:
            tag_info = tags_with_images[0]
            assert "tag_name" in tag_info
            assert "media_count" in tag_info
            assert "media_type" in tag_info
            assert tag_info["media_type"] == "image"
            assert tag_info["media_count"] >= 1
    
    @pytest.mark.asyncio
    async def test_comprehensive_tag_report(self, test_db_manager, sample_tags):
        """测试标签综合报告"""
        tag_stats = TagStatistics(test_db_manager)
        
        tag = sample_tags[0]
        
        # 获取综合报告
        report = await tag_stats.get_comprehensive_tag_report(tag.name)
        
        assert isinstance(report, dict)
        
        if "error" not in report:
            assert "tag_name" in report
            assert "media_statistics" in report
            assert "timeline_statistics" in report
            assert "channel_distribution" in report
            assert report["tag_name"] == tag.name


class TestTagStatisticsPerformance:
    """标签统计性能测试"""
    
    @pytest.mark.asyncio
    async def test_large_dataset_performance(self, test_db_manager, sample_channel, sample_tags):
        """测试大数据集性能"""
        import time
        
        tag_stats = TagStatistics(test_db_manager)
        
        # 创建大量测试数据
        async with test_db_manager.get_async_session() as session:
            messages = []
            message_tags = []
            
            # 创建100条消息
            for i in range(100):
                message = Message(
                    message_id=60000 + i,
                    channel_id=sample_channel.id,
                    message_text=f"性能测试消息{i}",
                    media_type=MediaType.VIDEO if i % 2 == 0 else MediaType.IMAGE,
                    file_name=f"perf_test_{i}.{'mp4' if i % 2 == 0 else 'jpg'}",
                    file_size=(5 + i % 10) * 1024 * 1024,  # 5-14MB
                    status=MessageStatus.COMPLETED
                )
                messages.append(message)
            
            # 批量插入消息
            session.add_all(messages)
            await session.commit()
            
            # 刷新获取ID
            for message in messages:
                await session.refresh(message)
            
            # 创建标签关系
            tag = sample_tags[0]
            for message in messages:
                message_tag = MessageTag(
                    message_id=message.id,
                    tag_id=tag.id
                )
                message_tags.append(message_tag)
            
            # 批量插入关系
            session.add_all(message_tags)
            await session.commit()
        
        # 测试查询性能
        start_time = time.time()
        
        stats = await tag_stats.get_tag_media_stats(tag_name=tag.name)
        
        end_time = time.time()
        query_time = end_time - start_time
        
        # 性能断言
        assert query_time < 2.0  # 应该在2秒内完成
        assert "error" not in stats
        assert stats["total_files"] == 100
        
        print(f"大数据集标签统计查询耗时: {query_time:.3f}秒")
    
    @pytest.mark.asyncio
    async def test_concurrent_statistics_queries(self, test_db_manager, sample_tags):
        """测试并发统计查询"""
        import time
        
        tag_stats = TagStatistics(test_db_manager)
        
        # 并发执行多个统计查询
        start_time = time.time()
        
        tasks = []
        for tag in sample_tags:
            task = tag_stats.get_tag_media_stats(tag_name=tag.name)
            tasks.append(task)
        
        # 等待所有查询完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # 验证结果
        for result in results:
            assert not isinstance(result, Exception)
            assert isinstance(result, dict)
        
        # 性能断言
        assert total_time < 3.0  # 并发查询应该在3秒内完成
        
        print(f"并发统计查询耗时: {total_time:.3f}秒")
