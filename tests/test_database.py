# -*- coding: utf-8 -*-
"""
数据库模块测试
"""

import pytest
from datetime import datetime

from src.database.models import Channel, Message, Tag, MessageTag, MediaType, MessageStatus, ChannelStatus
from src.database.database_manager import DatabaseManager


class TestDatabaseManager:
    """数据库管理器测试"""
    
    @pytest.mark.asyncio
    async def test_database_initialization(self, test_db_manager):
        """测试数据库初始化"""
        # 检查数据库是否正确初始化
        assert test_db_manager is not None
        
        # 检查健康状态
        health = await test_db_manager.health_check()
        assert health is True
    
    @pytest.mark.asyncio
    async def test_session_management(self, test_db_manager):
        """测试会话管理"""
        # 测试获取会话
        async with test_db_manager.get_async_session() as session:
            assert session is not None
            
            # 测试简单查询
            from sqlalchemy import select
            result = await session.execute(select(Channel))
            channels = result.scalars().all()
            assert isinstance(channels, list)


class TestChannelModel:
    """频道模型测试"""
    
    @pytest.mark.asyncio
    async def test_create_channel(self, test_db_manager):
        """测试创建频道"""
        async with test_db_manager.get_async_session() as session:
            channel = Channel(
                channel_id="-1001234567890",
                channel_title="测试频道",
                channel_username="test_channel",
                status=ChannelStatus.ACTIVE
            )
            
            session.add(channel)
            await session.commit()
            await session.refresh(channel)
            
            assert channel.id is not None
            assert channel.channel_title == "测试频道"
            assert channel.status == ChannelStatus.ACTIVE
    
    @pytest.mark.asyncio
    async def test_channel_relationships(self, test_db_manager, sample_channel, sample_messages):
        """测试频道关系"""
        async with test_db_manager.get_async_session() as session:
            from sqlalchemy import select
            
            # 获取频道及其消息
            result = await session.execute(
                select(Channel).where(Channel.id == sample_channel.id)
            )
            channel = result.scalar_one()
            
            # 检查频道消息关系
            message_result = await session.execute(
                select(Message).where(Message.channel_id == channel.id)
            )
            messages = message_result.scalars().all()
            
            assert len(messages) == len(sample_messages)


class TestMessageModel:
    """消息模型测试"""
    
    @pytest.mark.asyncio
    async def test_create_message(self, test_db_manager, sample_channel):
        """测试创建消息"""
        async with test_db_manager.get_async_session() as session:
            message = Message(
                message_id=9999,
                channel_id=sample_channel.id,
                message_text="测试消息",
                media_type=MediaType.VIDEO,
                file_name="test.mp4",
                file_size=1024 * 1024,  # 1MB
                status=MessageStatus.PENDING
            )
            
            session.add(message)
            await session.commit()
            await session.refresh(message)
            
            assert message.id is not None
            assert message.media_type == MediaType.VIDEO
            assert message.status == MessageStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_message_status_updates(self, test_db_manager, sample_messages):
        """测试消息状态更新"""
        message = sample_messages[0]
        
        async with test_db_manager.get_async_session() as session:
            from sqlalchemy import update
            
            # 更新消息状态
            await session.execute(
                update(Message)
                .where(Message.id == message.id)
                .values(status=MessageStatus.COMPLETED)
            )
            await session.commit()
            
            # 验证更新
            from sqlalchemy import select
            result = await session.execute(
                select(Message).where(Message.id == message.id)
            )
            updated_message = result.scalar_one()
            
            assert updated_message.status == MessageStatus.COMPLETED


class TestTagModel:
    """标签模型测试"""
    
    @pytest.mark.asyncio
    async def test_create_tag(self, test_db_manager):
        """测试创建标签"""
        async with test_db_manager.get_async_session() as session:
            tag = Tag(
                name="测试标签",
                description="这是一个测试标签",
                color="#FF0000",
                usage_count=0
            )
            
            session.add(tag)
            await session.commit()
            await session.refresh(tag)
            
            assert tag.id is not None
            assert tag.name == "测试标签"
            assert tag.color == "#FF0000"
    
    @pytest.mark.asyncio
    async def test_tag_message_relationship(self, test_db_manager, sample_messages, sample_tags):
        """测试标签消息关系"""
        message = sample_messages[0]
        tag = sample_tags[0]
        
        async with test_db_manager.get_async_session() as session:
            # 创建标签消息关系
            message_tag = MessageTag(
                message_id=message.id,
                tag_id=tag.id
            )
            
            session.add(message_tag)
            await session.commit()
            
            # 验证关系
            from sqlalchemy import select
            result = await session.execute(
                select(MessageTag).where(
                    MessageTag.message_id == message.id,
                    MessageTag.tag_id == tag.id
                )
            )
            
            relationship = result.scalar_one_or_none()
            assert relationship is not None
            assert relationship.message_id == message.id
            assert relationship.tag_id == tag.id


class TestDatabasePerformance:
    """数据库性能测试"""
    
    @pytest.mark.asyncio
    async def test_bulk_insert_performance(self, test_db_manager, sample_channel):
        """测试批量插入性能"""
        import time
        
        # 创建大量测试消息
        messages = []
        for i in range(100):
            message = Message(
                message_id=10000 + i,
                channel_id=sample_channel.id,
                message_text=f"批量测试消息 {i}",
                media_type=MediaType.IMAGE,
                file_name=f"test_image_{i}.jpg",
                file_size=1024 * 1024,  # 1MB
                status=MessageStatus.PENDING
            )
            messages.append(message)
        
        # 测试批量插入时间
        start_time = time.time()
        
        async with test_db_manager.get_async_session() as session:
            session.add_all(messages)
            await session.commit()
        
        end_time = time.time()
        insert_time = end_time - start_time
        
        # 验证插入成功
        async with test_db_manager.get_async_session() as session:
            from sqlalchemy import select, func
            count_result = await session.execute(
                select(func.count(Message.id)).where(
                    Message.channel_id == sample_channel.id
                )
            )
            count = count_result.scalar()
            
            assert count >= 100  # 至少有100条消息
        
        # 性能断言（批量插入应该在合理时间内完成）
        assert insert_time < 5.0  # 应该在5秒内完成
        
        print(f"批量插入100条消息耗时: {insert_time:.2f}秒")
    
    @pytest.mark.asyncio
    async def test_query_performance(self, test_db_manager, sample_channel):
        """测试查询性能"""
        import time
        
        # 测试复杂查询性能
        start_time = time.time()
        
        async with test_db_manager.get_async_session() as session:
            from sqlalchemy import select, func
            
            # 复杂统计查询
            result = await session.execute(
                select(
                    Message.media_type,
                    func.count(Message.id).label('count'),
                    func.sum(Message.file_size).label('total_size')
                )
                .where(Message.channel_id == sample_channel.id)
                .group_by(Message.media_type)
            )
            
            stats = result.all()
        
        end_time = time.time()
        query_time = end_time - start_time
        
        # 性能断言
        assert query_time < 1.0  # 查询应该在1秒内完成
        
        print(f"复杂统计查询耗时: {query_time:.3f}秒")


@pytest.fixture
def mock_telegram_bot_update():
    """模拟Telegram Bot更新"""
    update = MagicMock()
    update.effective_user.id = 123456789
    update.effective_user.first_name = "测试用户"
    update.message.reply_text = AsyncMock()
    update.message.text = "/test"
    
    return update


@pytest.fixture
def mock_telegram_bot_context():
    """模拟Telegram Bot上下文"""
    context = MagicMock()
    context.args = []
    return context
