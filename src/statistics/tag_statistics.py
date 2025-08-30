# -*- coding: utf-8 -*-
"""
标签统计管理器
提供按标签统计媒体类型数量的功能
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from ..database.database_manager import DatabaseManager
from ..database.models import Message, Tag, MessageTag, MediaType, MessageStatus, Channel
from ..utils.logger import LoggerMixin


class TagStatistics(LoggerMixin):
    """标签统计管理器"""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        初始化标签统计管理器
        
        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.logger.info("标签统计管理器初始化完成")
    
    async def get_tag_media_stats(self, tag_name: str = None, tag_id: int = None) -> Dict[str, Any]:
        """
        获取指定标签下的媒体统计
        
        Args:
            tag_name: 标签名称
            tag_id: 标签ID
        
        Returns:
            Dict: 媒体统计信息
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 查找标签
                if tag_id:
                    tag_result = await session.execute(
                        select(Tag).where(Tag.id == tag_id)
                    )
                elif tag_name:
                    tag_result = await session.execute(
                        select(Tag).where(Tag.name == tag_name)
                    )
                else:
                    return {"error": "必须提供标签名称或ID"}
                
                tag = tag_result.scalar_one_or_none()
                if not tag:
                    return {"error": f"未找到标签: {tag_name or tag_id}"}
                
                # 获取该标签下的所有消息
                messages_result = await session.execute(
                    select(Message)
                    .join(MessageTag, Message.id == MessageTag.message_id)
                    .where(
                        MessageTag.tag_id == tag.id,
                        Message.status == MessageStatus.COMPLETED
                    )
                )
                messages = messages_result.scalars().all()
                
                # 按媒体类型统计
                media_stats = {}
                total_files = 0
                total_size = 0
                
                for media_type in MediaType:
                    type_messages = [msg for msg in messages if msg.media_type == media_type]
                    type_count = len(type_messages)
                    type_size = sum(msg.file_size or 0 for msg in type_messages)
                    
                    media_stats[media_type.value] = {
                        "count": type_count,
                        "size_bytes": type_size,
                        "size_mb": type_size / (1024 * 1024),
                        "avg_size_mb": (type_size / type_count / (1024 * 1024)) if type_count > 0 else 0
                    }
                    
                    total_files += type_count
                    total_size += type_size
                
                return {
                    "tag_info": {
                        "id": tag.id,
                        "name": tag.name,
                        "description": tag.description,
                        "color": tag.color
                    },
                    "total_files": total_files,
                    "total_size_bytes": total_size,
                    "total_size_mb": total_size / (1024 * 1024),
                    "total_size_gb": total_size / (1024 * 1024 * 1024),
                    "media_stats": media_stats,
                    "generated_at": datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            self.logger.error(f"获取标签媒体统计失败: {e}")
            return {"error": str(e)}
    
    async def get_all_tags_media_summary(self, limit: int = 50) -> Dict[str, Any]:
        """
        获取所有标签的媒体统计摘要
        
        Args:
            limit: 限制标签数量
        
        Returns:
            Dict: 所有标签的媒体统计摘要
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 获取所有有内容的标签
                tags_result = await session.execute(
                    select(Tag)
                    .where(Tag.usage_count > 0)
                    .order_by(Tag.usage_count.desc())
                    .limit(limit)
                )
                tags = tags_result.scalars().all()
                
                summary = {
                    "total_tags": len(tags),
                    "tags_summary": [],
                    "overall_stats": {
                        "total_videos": 0,
                        "total_images": 0,
                        "total_audio": 0,
                        "total_documents": 0
                    }
                }
                
                for tag in tags:
                    # 获取该标签的媒体统计
                    tag_stats = await self.get_tag_media_stats(tag_id=tag.id)
                    
                    if "error" not in tag_stats:
                        media_stats = tag_stats["media_stats"]
                        
                        tag_summary = {
                            "tag_name": tag.name,
                            "tag_id": tag.id,
                            "videos": media_stats.get("video", {}).get("count", 0),
                            "images": media_stats.get("image", {}).get("count", 0),
                            "audio": media_stats.get("audio", {}).get("count", 0),
                            "documents": media_stats.get("document", {}).get("count", 0),
                            "total_files": tag_stats["total_files"],
                            "total_size_mb": tag_stats["total_size_mb"]
                        }
                        
                        summary["tags_summary"].append(tag_summary)
                        
                        # 累计总体统计
                        summary["overall_stats"]["total_videos"] += tag_summary["videos"]
                        summary["overall_stats"]["total_images"] += tag_summary["images"]
                        summary["overall_stats"]["total_audio"] += tag_summary["audio"]
                        summary["overall_stats"]["total_documents"] += tag_summary["documents"]
                
                return summary
                
        except Exception as e:
            self.logger.error(f"获取所有标签媒体摘要失败: {e}")
            return {"error": str(e)}
    
    async def get_media_type_by_tags(self, media_type: MediaType, limit: int = 20) -> Dict[str, Any]:
        """
        获取指定媒体类型在各标签下的分布
        
        Args:
            media_type: 媒体类型
            limit: 限制标签数量
        
        Returns:
            Dict: 媒体类型在各标签下的分布
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 查询指定媒体类型的消息及其标签
                result = await session.execute(
                    select(Tag, func.count(Message.id).label('message_count'))
                    .join(MessageTag, Tag.id == MessageTag.tag_id)
                    .join(Message, MessageTag.message_id == Message.id)
                    .where(
                        Message.media_type == media_type,
                        Message.status == MessageStatus.COMPLETED
                    )
                    .group_by(Tag.id)
                    .order_by(func.count(Message.id).desc())
                    .limit(limit)
                )
                
                tag_distribution = []
                total_count = 0
                
                for tag, count in result:
                    tag_distribution.append({
                        "tag_id": tag.id,
                        "tag_name": tag.name,
                        "tag_color": tag.color,
                        "count": count,
                        "percentage": 0  # 稍后计算
                    })
                    total_count += count
                
                # 计算百分比
                for item in tag_distribution:
                    if total_count > 0:
                        item["percentage"] = (item["count"] / total_count) * 100
                
                return {
                    "media_type": media_type.value,
                    "total_count": total_count,
                    "tag_distribution": tag_distribution,
                    "generated_at": datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            self.logger.error(f"获取媒体类型标签分布失败: {e}")
            return {"error": str(e)}
    
    async def get_tag_timeline_stats(self, tag_name: str, days: int = 30) -> Dict[str, Any]:
        """
        获取标签的时间线统计
        
        Args:
            tag_name: 标签名称
            days: 统计天数
        
        Returns:
            Dict: 时间线统计
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 查找标签
                tag_result = await session.execute(
                    select(Tag).where(Tag.name == tag_name)
                )
                tag = tag_result.scalar_one_or_none()
                
                if not tag:
                    return {"error": f"未找到标签: {tag_name}"}
                
                # 计算时间范围
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=days)
                
                # 获取时间范围内的消息
                messages_result = await session.execute(
                    select(Message)
                    .join(MessageTag, Message.id == MessageTag.message_id)
                    .where(
                        MessageTag.tag_id == tag.id,
                        Message.message_date >= start_date,
                        Message.message_date <= end_date,
                        Message.status == MessageStatus.COMPLETED
                    )
                    .order_by(Message.message_date.asc())
                )
                messages = messages_result.scalars().all()
                
                # 按日期分组统计
                daily_stats = {}
                for msg in messages:
                    date_key = msg.message_date.strftime('%Y-%m-%d')
                    
                    if date_key not in daily_stats:
                        daily_stats[date_key] = {
                            "total": 0,
                            "videos": 0,
                            "images": 0,
                            "audio": 0,
                            "documents": 0
                        }
                    
                    daily_stats[date_key]["total"] += 1
                    daily_stats[date_key][msg.media_type.value + "s"] += 1
                
                return {
                    "tag_name": tag_name,
                    "period_days": days,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "total_messages": len(messages),
                    "daily_stats": daily_stats,
                    "generated_at": datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            self.logger.error(f"获取标签时间线统计失败: {e}")
            return {"error": str(e)}
    
    async def search_tags_by_media_count(
        self, 
        media_type: MediaType, 
        min_count: int = 1,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        按媒体数量搜索标签
        
        Args:
            media_type: 媒体类型
            min_count: 最小数量
            limit: 限制数量
        
        Returns:
            List[Dict]: 标签列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 查询包含指定媒体类型且数量大于最小值的标签
                result = await session.execute(
                    select(Tag, func.count(Message.id).label('media_count'))
                    .join(MessageTag, Tag.id == MessageTag.tag_id)
                    .join(Message, MessageTag.message_id == Message.id)
                    .where(
                        Message.media_type == media_type,
                        Message.status == MessageStatus.COMPLETED
                    )
                    .group_by(Tag.id)
                    .having(func.count(Message.id) >= min_count)
                    .order_by(func.count(Message.id).desc())
                    .limit(limit)
                )
                
                tags_with_count = []
                for tag, count in result:
                    tags_with_count.append({
                        "tag_id": tag.id,
                        "tag_name": tag.name,
                        "tag_description": tag.description,
                        "tag_color": tag.color,
                        "media_count": count,
                        "media_type": media_type.value
                    })
                
                return tags_with_count
                
        except Exception as e:
            self.logger.error(f"按媒体数量搜索标签失败: {e}")
            return []
    
    async def get_top_tags_by_media_type(self, limit: int = 10) -> Dict[str, Any]:
        """
        获取各媒体类型的热门标签
        
        Args:
            limit: 每种类型的限制数量
        
        Returns:
            Dict: 各媒体类型的热门标签
        """
        try:
            result = {}
            
            for media_type in MediaType:
                top_tags = await self.search_tags_by_media_count(
                    media_type, 
                    min_count=1, 
                    limit=limit
                )
                result[media_type.value] = top_tags
            
            return {
                "top_tags_by_type": result,
                "generated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"获取热门标签失败: {e}")
            return {"error": str(e)}
    
    async def get_comprehensive_tag_report(self, tag_name: str) -> Dict[str, Any]:
        """
        获取标签的综合报告
        
        Args:
            tag_name: 标签名称
        
        Returns:
            Dict: 综合报告
        """
        try:
            # 获取基础媒体统计
            media_stats = await self.get_tag_media_stats(tag_name=tag_name)
            if "error" in media_stats:
                return media_stats
            
            # 获取时间线统计
            timeline_stats = await self.get_tag_timeline_stats(tag_name, days=30)
            
            # 获取频道分布
            channel_distribution = await self._get_tag_channel_distribution(tag_name)
            
            return {
                "tag_name": tag_name,
                "media_statistics": media_stats,
                "timeline_statistics": timeline_stats,
                "channel_distribution": channel_distribution,
                "generated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"获取标签综合报告失败: {e}")
            return {"error": str(e)}
    
    async def _get_tag_channel_distribution(self, tag_name: str) -> Dict[str, Any]:
        """
        获取标签在各频道的分布
        
        Args:
            tag_name: 标签名称
        
        Returns:
            Dict: 频道分布信息
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 查找标签
                tag_result = await session.execute(
                    select(Tag).where(Tag.name == tag_name)
                )
                tag = tag_result.scalar_one_or_none()
                
                if not tag:
                    return {"error": f"未找到标签: {tag_name}"}
                
                # 获取各频道的消息数量
                result = await session.execute(
                    select(Channel, func.count(Message.id).label('message_count'))
                    .join(Message, Channel.id == Message.channel_id)
                    .join(MessageTag, Message.id == MessageTag.message_id)
                    .where(
                        MessageTag.tag_id == tag.id,
                        Message.status == MessageStatus.COMPLETED
                    )
                    .group_by(Channel.id)
                    .order_by(func.count(Message.id).desc())
                )
                
                channel_distribution = []
                total_messages = 0
                
                for channel, count in result:
                    channel_distribution.append({
                        "channel_id": channel.id,
                        "channel_title": channel.channel_title,
                        "channel_username": channel.channel_username,
                        "message_count": count,
                        "percentage": 0  # 稍后计算
                    })
                    total_messages += count
                
                # 计算百分比
                for item in channel_distribution:
                    if total_messages > 0:
                        item["percentage"] = (item["message_count"] / total_messages) * 100
                
                return {
                    "total_messages": total_messages,
                    "channel_count": len(channel_distribution),
                    "distribution": channel_distribution
                }
                
        except Exception as e:
            self.logger.error(f"获取标签频道分布失败: {e}")
            return {"error": str(e)}
    
    async def compare_tags_media_stats(self, tag_names: List[str]) -> Dict[str, Any]:
        """
        比较多个标签的媒体统计
        
        Args:
            tag_names: 标签名称列表
        
        Returns:
            Dict: 比较结果
        """
        try:
            comparison_data = {}
            
            for tag_name in tag_names:
                stats = await self.get_tag_media_stats(tag_name=tag_name)
                if "error" not in stats:
                    comparison_data[tag_name] = {
                        "videos": stats["media_stats"]["video"]["count"],
                        "images": stats["media_stats"]["image"]["count"],
                        "audio": stats["media_stats"]["audio"]["count"],
                        "documents": stats["media_stats"]["document"]["count"],
                        "total_files": stats["total_files"],
                        "total_size_mb": stats["total_size_mb"]
                    }
            
            return {
                "compared_tags": list(tag_names),
                "comparison_data": comparison_data,
                "generated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"比较标签媒体统计失败: {e}")
            return {"error": str(e)}
