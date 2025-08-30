# -*- coding: utf-8 -*-
"""
频道管理器
负责频道的添加、删除、更新和状态管理
"""

import re
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError
from telethon import TelegramClient
from telethon.tl.types import Channel as TelegramChannel, Chat
from telethon.errors import (
    ChannelPrivateError, ChannelInvalidError, 
    UsernameNotOccupiedError, FloodWaitError
)

from ..database.database_manager import DatabaseManager
from ..database.models import Channel, ChannelStatus, UserSettings
from ..utils.logger import LoggerMixin


class ChannelManager(LoggerMixin):
    """频道管理器"""
    
    def __init__(self, db_manager: DatabaseManager, telegram_client: TelegramClient):
        """
        初始化频道管理器
        
        Args:
            db_manager: 数据库管理器
            telegram_client: Telegram客户端
        """
        self.db_manager = db_manager
        self.client = telegram_client
        
        # 频道URL正则表达式
        self.channel_url_pattern = re.compile(
            r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]+)'
        )
        
        self.logger.info("频道管理器初始化完成")
    
    async def add_channel(self, channel_input: str, user_id: str) -> Dict[str, Any]:
        """
        添加频道到监控列表
        
        Args:
            channel_input: 频道链接或用户名
            user_id: 添加者的用户ID
        
        Returns:
            Dict: 操作结果
        """
        try:
            # 解析频道标识符
            channel_identifier = self._parse_channel_input(channel_input)
            if not channel_identifier:
                return {
                    "success": False,
                    "error": "无效的频道链接或用户名格式"
                }
            
            self.logger.info(f"用户 {user_id} 尝试添加频道: {channel_identifier}")
            
            # 获取频道信息
            channel_info = await self._get_channel_info(channel_identifier)
            if not channel_info:
                return {
                    "success": False,
                    "error": "无法获取频道信息，请检查频道是否存在或是否有访问权限"
                }
            
            # 检查频道是否已存在
            async with self.db_manager.get_async_session() as session:
                existing_channel = await session.execute(
                    select(Channel).where(Channel.channel_id == str(channel_info["id"]))
                )
                if existing_channel.scalar_one_or_none():
                    return {
                        "success": False,
                        "error": "频道已存在于监控列表中"
                    }
                
                # 创建新频道记录
                new_channel = Channel(
                    channel_id=str(channel_info["id"]),
                    channel_username=channel_info.get("username"),
                    channel_title=channel_info["title"],
                    channel_description=channel_info.get("about", ""),
                    status=ChannelStatus.ACTIVE,
                    added_by_user_id=user_id,
                    total_messages=0,
                    processed_messages=0
                )
                
                session.add(new_channel)
                await session.commit()
                
                self.logger.info(f"成功添加频道: {channel_info['title']} (ID: {channel_info['id']})")
                
                return {
                    "success": True,
                    "channel": {
                        "id": new_channel.id,
                        "channel_id": new_channel.channel_id,
                        "title": new_channel.channel_title,
                        "username": new_channel.channel_username,
                        "status": new_channel.status
                    }
                }
                
        except IntegrityError:
            return {
                "success": False,
                "error": "频道已存在"
            }
        except Exception as e:
            self.logger.error(f"添加频道失败: {e}")
            return {
                "success": False,
                "error": f"添加频道时发生错误: {str(e)}"
            }
    
    async def remove_channel(self, channel_id: str, user_id: str) -> Dict[str, Any]:
        """
        从监控列表中移除频道
        
        Args:
            channel_id: 频道ID（数据库ID或Telegram频道ID）
            user_id: 操作者的用户ID
        
        Returns:
            Dict: 操作结果
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 查找频道（支持数据库ID和Telegram频道ID）
                if channel_id.isdigit():
                    # 数据库ID
                    channel = await session.execute(
                        select(Channel).where(Channel.id == int(channel_id))
                    )
                else:
                    # Telegram频道ID
                    channel = await session.execute(
                        select(Channel).where(Channel.channel_id == channel_id)
                    )
                
                channel = channel.scalar_one_or_none()
                if not channel:
                    return {
                        "success": False,
                        "error": "频道不存在"
                    }
                
                # 检查权限（可选：只允许添加者删除）
                # if channel.added_by_user_id != user_id:
                #     return {
                #         "success": False,
                #         "error": "只有频道添加者可以删除频道"
                #     }
                
                # 标记为已删除而不是直接删除（保留历史数据）
                channel.status = ChannelStatus.DELETED
                channel.updated_at = datetime.utcnow()
                
                await session.commit()
                
                self.logger.info(f"用户 {user_id} 删除了频道: {channel.channel_title}")
                
                return {
                    "success": True,
                    "message": f"频道 '{channel.channel_title}' 已从监控列表中移除"
                }
                
        except Exception as e:
            self.logger.error(f"删除频道失败: {e}")
            return {
                "success": False,
                "error": f"删除频道时发生错误: {str(e)}"
            }
    
    async def list_channels(self, user_id: str, include_deleted: bool = False) -> Dict[str, Any]:
        """
        获取用户的频道列表
        
        Args:
            user_id: 用户ID
            include_deleted: 是否包含已删除的频道
        
        Returns:
            Dict: 频道列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 构建查询
                query = select(Channel).where(Channel.added_by_user_id == user_id)
                
                if not include_deleted:
                    query = query.where(Channel.status != ChannelStatus.DELETED)
                
                query = query.order_by(Channel.created_at.desc())
                
                result = await session.execute(query)
                channels = result.scalars().all()
                
                # 格式化频道信息
                channel_list = []
                for channel in channels:
                    channel_info = {
                        "id": channel.id,
                        "channel_id": channel.channel_id,
                        "title": channel.channel_title,
                        "username": channel.channel_username,
                        "status": channel.status,
                        "total_messages": channel.total_messages,
                        "processed_messages": channel.processed_messages,
                        "last_check_time": channel.last_check_time.isoformat() if channel.last_check_time else None,
                        "created_at": channel.created_at.isoformat()
                    }
                    channel_list.append(channel_info)
                
                return {
                    "success": True,
                    "channels": channel_list,
                    "total": len(channel_list)
                }
                
        except Exception as e:
            self.logger.error(f"获取频道列表失败: {e}")
            return {
                "success": False,
                "error": f"获取频道列表时发生错误: {str(e)}"
            }
    
    async def update_channel_status(self, channel_id: str, status: ChannelStatus) -> bool:
        """
        更新频道状态
        
        Args:
            channel_id: 频道ID
            status: 新状态
        
        Returns:
            bool: 是否更新成功
        """
        try:
            async with self.db_manager.get_async_session() as session:
                await session.execute(
                    update(Channel)
                    .where(Channel.channel_id == channel_id)
                    .values(status=status, updated_at=datetime.utcnow())
                )
                await session.commit()
                
                self.logger.info(f"频道 {channel_id} 状态更新为: {status}")
                return True
                
        except Exception as e:
            self.logger.error(f"更新频道状态失败: {e}")
            return False
    
    async def get_active_channels(self) -> List[Channel]:
        """
        获取所有活跃的频道
        
        Returns:
            List[Channel]: 活跃频道列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Channel).where(Channel.status == ChannelStatus.ACTIVE)
                )
                return result.scalars().all()
                
        except Exception as e:
            self.logger.error(f"获取活跃频道失败: {e}")
            return []
    
    def _parse_channel_input(self, channel_input: str) -> Optional[str]:
        """
        解析频道输入，提取频道标识符
        
        Args:
            channel_input: 用户输入的频道链接或用户名
        
        Returns:
            Optional[str]: 频道标识符
        """
        channel_input = channel_input.strip()
        
        # 匹配URL格式
        url_match = self.channel_url_pattern.match(channel_input)
        if url_match:
            return url_match.group(1)
        
        # 匹配@username格式
        if channel_input.startswith('@'):
            return channel_input[1:]
        
        # 直接是用户名
        if re.match(r'^[a-zA-Z0-9_]+$', channel_input):
            return channel_input
        
        return None
    
    async def _get_channel_info(self, channel_identifier: str) -> Optional[Dict[str, Any]]:
        """
        获取频道信息
        
        Args:
            channel_identifier: 频道标识符
        
        Returns:
            Optional[Dict]: 频道信息
        """
        try:
            # 获取频道实体
            entity = await self.client.get_entity(channel_identifier)
            
            if not isinstance(entity, (TelegramChannel, Chat)):
                return None
            
            # 提取频道信息
            channel_info = {
                "id": entity.id,
                "title": entity.title,
                "username": getattr(entity, 'username', None),
                "about": getattr(entity, 'about', ''),
                "participants_count": getattr(entity, 'participants_count', 0),
                "is_broadcast": getattr(entity, 'broadcast', False),
                "is_megagroup": getattr(entity, 'megagroup', False)
            }
            
            return channel_info
            
        except (ChannelPrivateError, ChannelInvalidError, UsernameNotOccupiedError) as e:
            self.logger.warning(f"无法访问频道 {channel_identifier}: {e}")
            return None
        except FloodWaitError as e:
            self.logger.warning(f"请求过于频繁，需要等待 {e.seconds} 秒")
            return None
        except Exception as e:
            self.logger.error(f"获取频道信息失败: {e}")
            return None
