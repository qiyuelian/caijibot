# -*- coding: utf-8 -*-
"""
pytest配置文件
提供测试夹具和配置
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.config.settings import Settings
from src.database.database_manager import DatabaseManager
from src.database.models import Channel, Message, Tag, MediaType, MessageStatus, ChannelStatus


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_settings():
    """测试配置"""
    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(
            # 数据库配置
            database_url=f"sqlite:///{temp_dir}/test.db",
            
            # 存储配置
            storage_path=f"{temp_dir}/storage",
            max_file_size_mb=100,
            max_storage_size_gb=10,
            
            # Telegram配置（测试用假值）
            bot_token="test_token",
            api_id=12345,
            api_hash="test_hash",
            
            # 功能配置
            enable_video_collection=True,
            enable_image_collection=True,
            auto_classification=True,
            enable_hash_dedup=True,
            enable_feature_dedup=True,
            
            # 测试专用配置
            max_concurrent_downloads=1,
            collection_interval_seconds=1,
            auto_download_mode="manual"
        )
        yield settings


@pytest.fixture
async def test_db_manager(test_settings):
    """测试数据库管理器"""
    db_manager = DatabaseManager(test_settings)
    await db_manager.initialize()
    yield db_manager
    await db_manager.close()


@pytest.fixture
async def sample_channel(test_db_manager):
    """示例频道"""
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
        yield channel


@pytest.fixture
async def sample_messages(test_db_manager, sample_channel):
    """示例消息"""
    async with test_db_manager.get_async_session() as session:
        messages = [
            Message(
                message_id=1001,
                channel_id=sample_channel.id,
                message_text="测试视频消息",
                media_type=MediaType.VIDEO,
                file_name="test_video.mp4",
                file_size=10 * 1024 * 1024,  # 10MB
                status=MessageStatus.COMPLETED
            ),
            Message(
                message_id=1002,
                channel_id=sample_channel.id,
                message_text="测试图片消息",
                media_type=MediaType.IMAGE,
                file_name="test_image.jpg",
                file_size=2 * 1024 * 1024,  # 2MB
                status=MessageStatus.COMPLETED
            ),
            Message(
                message_id=1003,
                channel_id=sample_channel.id,
                message_text="测试音频消息",
                media_type=MediaType.AUDIO,
                file_name="test_audio.mp3",
                file_size=5 * 1024 * 1024,  # 5MB
                status=MessageStatus.PENDING
            )
        ]
        
        for message in messages:
            session.add(message)
        
        await session.commit()
        
        # 刷新对象以获取ID
        for message in messages:
            await session.refresh(message)
        
        yield messages


@pytest.fixture
async def sample_tags(test_db_manager):
    """示例标签"""
    async with test_db_manager.get_async_session() as session:
        tags = [
            Tag(
                name="搞笑视频",
                description="有趣的搞笑视频内容",
                color="#FF5722",
                usage_count=10
            ),
            Tag(
                name="猫咪",
                description="可爱的猫咪相关内容",
                color="#4CAF50",
                usage_count=8
            ),
            Tag(
                name="音乐",
                description="音乐相关内容",
                color="#2196F3",
                usage_count=5
            )
        ]
        
        for tag in tags:
            session.add(tag)
        
        await session.commit()
        
        # 刷新对象以获取ID
        for tag in tags:
            await session.refresh(tag)
        
        yield tags


@pytest.fixture
def mock_telegram_client():
    """模拟Telegram客户端"""
    client = AsyncMock()
    
    # 模拟常用方法
    client.get_entity = AsyncMock()
    client.get_messages = AsyncMock()
    client.iter_messages = AsyncMock()
    client.download_media = AsyncMock()
    
    return client


@pytest.fixture
def mock_telegram_message():
    """模拟Telegram消息"""
    message = MagicMock()
    message.id = 12345
    message.text = "测试消息"
    message.date = asyncio.get_event_loop().run_until_complete(
        asyncio.coroutine(lambda: __import__('datetime').datetime.utcnow())()
    )
    message.media = None
    
    return message


@pytest.fixture
def mock_update_context():
    """模拟Telegram Bot更新和上下文"""
    update = MagicMock()
    context = MagicMock()
    
    # 模拟用户
    update.effective_user.id = 123456789
    update.effective_user.first_name = "测试用户"
    
    # 模拟消息
    update.message.reply_text = AsyncMock()
    update.message.text = "/test"
    
    # 模拟回调查询
    update.callback_query = MagicMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.data = "test_callback"
    
    # 模拟上下文
    context.args = []
    
    return update, context


# 测试工具函数
def create_test_file(path: Path, size_mb: int = 1):
    """创建测试文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # 创建指定大小的测试文件
    with open(path, 'wb') as f:
        f.write(b'0' * (size_mb * 1024 * 1024))
    
    return path


async def cleanup_test_data(db_manager: DatabaseManager):
    """清理测试数据"""
    try:
        async with db_manager.get_async_session() as session:
            # 删除所有测试数据
            from sqlalchemy import delete
            from src.database.models import MessageTag, DuplicateRecord
            
            await session.execute(delete(MessageTag))
            await session.execute(delete(DuplicateRecord))
            await session.execute(delete(Message))
            await session.execute(delete(Tag))
            await session.execute(delete(Channel))
            
            await session.commit()
    except Exception as e:
        print(f"清理测试数据失败: {e}")
