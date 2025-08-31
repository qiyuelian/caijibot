# -*- coding: utf-8 -*-
"""
数据库模型定义
定义所有数据库表的结构和关系
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, 
    String, Text, UniqueConstraint, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Session
from sqlalchemy.sql import func

Base = declarative_base()


class MediaType(str, Enum):
    """媒体类型枚举"""
    VIDEO = "video"
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"


class ChannelStatus(str, Enum):
    """频道状态枚举"""
    ACTIVE = "active"      # 活跃监控
    PAUSED = "paused"      # 暂停监控
    ERROR = "error"        # 错误状态
    DELETED = "deleted"    # 已删除


class MessageStatus(str, Enum):
    """消息处理状态枚举"""
    PENDING = "pending"        # 待处理
    DOWNLOADING = "downloading" # 下载中
    PROCESSING = "processing"   # 处理中
    COMPLETED = "completed"     # 已完成
    FAILED = "failed"          # 处理失败
    DUPLICATE = "duplicate"     # 重复内容
    SKIPPED = "skipped"        # 已跳过


class Channel(Base):
    """频道表"""
    __tablename__ = "channels"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(50), unique=True, nullable=False, comment="Telegram频道ID")
    channel_username = Column(String(100), nullable=True, comment="频道用户名")
    channel_title = Column(String(200), nullable=False, comment="频道标题")
    channel_description = Column(Text, nullable=True, comment="频道描述")
    
    status = Column(String(20), default=ChannelStatus.ACTIVE, comment="频道状态")
    added_by_user_id = Column(String(50), nullable=False, comment="添加者用户ID")
    
    # 统计信息
    total_messages = Column(Integer, default=0, comment="总消息数")
    processed_messages = Column(Integer, default=0, comment="已处理消息数")
    last_message_id = Column(Integer, nullable=True, comment="最后处理的消息ID")
    last_check_time = Column(DateTime, nullable=True, comment="最后检查时间")
    
    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 关系
    messages = relationship("Message", back_populates="channel", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Channel(id={self.id}, title='{self.channel_title}', status='{self.status}')>"


class Message(Base):
    """消息表"""
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, nullable=False, comment="Telegram消息ID")
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, comment="所属频道ID")
    
    # 消息内容
    message_text = Column(Text, nullable=True, comment="消息文本")
    media_type = Column(String(20), nullable=True, comment="媒体类型")
    file_name = Column(String(500), nullable=True, comment="文件名")
    file_size = Column(Integer, nullable=True, comment="文件大小(字节)")
    file_path = Column(String(1000), nullable=True, comment="本地文件路径")
    
    # 处理状态
    status = Column(String(20), default=MessageStatus.PENDING, comment="处理状态")
    download_progress = Column(Float, default=0.0, comment="下载进度(0-1)")
    error_message = Column(Text, nullable=True, comment="错误信息")
    
    # 去重信息
    file_hash = Column(String(64), nullable=True, comment="文件哈希值")
    content_hash = Column(String(64), nullable=True, comment="内容哈希值")
    is_duplicate = Column(Boolean, default=False, comment="是否为重复内容")
    original_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True, comment="原始消息ID")
    
    # 时间戳
    message_date = Column(DateTime, nullable=False, comment="消息发送时间")
    created_at = Column(DateTime, default=func.now(), comment="记录创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="记录更新时间")
    processed_at = Column(DateTime, nullable=True, comment="处理完成时间")
    
    # 关系
    channel = relationship("Channel", back_populates="messages")
    tags = relationship("MessageTag", back_populates="message", cascade="all, delete-orphan")
    duplicates = relationship("Message", remote_side=[id])
    
    # 索引
    __table_args__ = (
        UniqueConstraint('message_id', 'channel_id', name='uq_message_channel'),
        Index('idx_message_status', 'status'),
        Index('idx_message_hash', 'file_hash'),
        Index('idx_message_date', 'message_date'),
    )
    
    def __repr__(self):
        return f"<Message(id={self.id}, message_id={self.message_id}, status='{self.status}')>"


class Tag(Base):
    """标签表"""
    __tablename__ = "tags"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, comment="标签名称")
    description = Column(Text, nullable=True, comment="标签描述")
    color = Column(String(7), nullable=True, comment="标签颜色(HEX)")
    
    # 统计信息
    usage_count = Column(Integer, default=0, comment="使用次数")
    
    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 关系
    message_tags = relationship("MessageTag", back_populates="tag", cascade="all, delete-orphan")
    classification_rules = relationship("ClassificationRule", back_populates="tag", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Tag(id={self.id}, name='{self.name}')>"


class MessageTag(Base):
    """消息标签关联表"""
    __tablename__ = "message_tags"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, comment="消息ID")
    tag_id = Column(Integer, ForeignKey("tags.id"), nullable=False, comment="标签ID")
    
    # 分类信息
    confidence = Column(Float, default=1.0, comment="分类置信度(0-1)")
    is_auto_classified = Column(Boolean, default=False, comment="是否自动分类")
    classified_by = Column(String(50), nullable=True, comment="分类者")
    
    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    
    # 关系
    message = relationship("Message", back_populates="tags")
    tag = relationship("Tag", back_populates="message_tags")
    
    # 索引
    __table_args__ = (
        UniqueConstraint('message_id', 'tag_id', name='uq_message_tag'),
        Index('idx_message_tag_confidence', 'confidence'),
    )
    
    def __repr__(self):
        return f"<MessageTag(message_id={self.message_id}, tag_id={self.tag_id})>"


class ClassificationRule(Base):
    """分类规则表"""
    __tablename__ = "classification_rules"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, comment="规则名称")
    description = Column(Text, nullable=True, comment="规则描述")
    
    # 规则配置
    rule_type = Column(String(50), nullable=False, comment="规则类型(keyword/regex/file_ext)")
    rule_pattern = Column(Text, nullable=False, comment="规则模式")
    target_field = Column(String(50), nullable=False, comment="目标字段(filename/text/both)")
    
    # 标签关联
    tag_id = Column(Integer, ForeignKey("tags.id"), nullable=False, comment="目标标签ID")
    
    # 规则状态
    is_active = Column(Boolean, default=True, comment="是否启用")
    priority = Column(Integer, default=0, comment="优先级(数字越大优先级越高)")
    
    # 统计信息
    match_count = Column(Integer, default=0, comment="匹配次数")
    
    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 关系
    tag = relationship("Tag", back_populates="classification_rules")
    
    # 索引
    __table_args__ = (
        Index('idx_rule_active_priority', 'is_active', 'priority'),
        Index('idx_rule_type', 'rule_type'),
    )
    
    def __repr__(self):
        return f"<ClassificationRule(id={self.id}, name='{self.name}', type='{self.rule_type}')>"


class DuplicateRecord(Base):
    """去重记录表"""
    __tablename__ = "duplicate_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, comment="原始消息ID")
    duplicate_message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, comment="重复消息ID")

    # 相似度信息
    similarity_score = Column(Float, nullable=False, comment="相似度分数(0-1)")
    similarity_type = Column(String(50), nullable=False, comment="相似度类型(hash/feature/content)")

    # 处理决策
    action_taken = Column(String(50), nullable=False, comment="采取的行动(keep_original/keep_duplicate/keep_both)")
    reason = Column(Text, nullable=True, comment="决策原因")

    # 时间戳
    detected_at = Column(DateTime, default=func.now(), comment="检测时间")
    processed_at = Column(DateTime, nullable=True, comment="处理时间")

    # 关系
    original_message = relationship("Message", foreign_keys=[original_message_id])
    duplicate_message = relationship("Message", foreign_keys=[duplicate_message_id])

    # 索引
    __table_args__ = (
        UniqueConstraint('original_message_id', 'duplicate_message_id', name='uq_duplicate_pair'),
        Index('idx_duplicate_similarity', 'similarity_score'),
        Index('idx_duplicate_type', 'similarity_type'),
    )

    def __repr__(self):
        return f"<DuplicateRecord(original={self.original_message_id}, duplicate={self.duplicate_message_id}, score={self.similarity_score})>"


class UserSettings(Base):
    """用户设置表"""
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), unique=True, nullable=False, comment="Telegram用户ID")
    username = Column(String(100), nullable=True, comment="用户名")

    # 采集设置
    enable_video_collection = Column(Boolean, default=True, comment="启用视频采集")
    enable_image_collection = Column(Boolean, default=True, comment="启用图片采集")
    max_file_size_mb = Column(Float, default=100.0, comment="最大文件大小(MB)")

    # 分类设置
    auto_classification = Column(Boolean, default=True, comment="启用自动分类")
    default_tag_id = Column(Integer, ForeignKey("tags.id"), nullable=True, comment="默认标签ID")

    # 去重设置
    duplicate_threshold = Column(Float, default=0.95, comment="去重阈值")
    enable_hash_dedup = Column(Boolean, default=True, comment="启用哈希去重")
    enable_feature_dedup = Column(Boolean, default=True, comment="启用特征去重")

    # 通知设置
    enable_notifications = Column(Boolean, default=True, comment="启用通知")
    notify_on_completion = Column(Boolean, default=True, comment="完成时通知")
    notify_on_error = Column(Boolean, default=True, comment="错误时通知")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关系
    default_tag = relationship("Tag", foreign_keys=[default_tag_id])

    def __repr__(self):
        return f"<UserSettings(user_id='{self.user_id}', username='{self.username}')>"


class SystemStats(Base):
    """系统统计表"""
    __tablename__ = "system_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(DateTime, nullable=False, comment="统计日期")

    # 采集统计
    total_channels = Column(Integer, default=0, comment="总频道数")
    active_channels = Column(Integer, default=0, comment="活跃频道数")
    total_messages = Column(Integer, default=0, comment="总消息数")
    processed_messages = Column(Integer, default=0, comment="已处理消息数")

    # 文件统计
    total_files = Column(Integer, default=0, comment="总文件数")
    total_videos = Column(Integer, default=0, comment="视频文件数")
    total_images = Column(Integer, default=0, comment="图片文件数")
    total_size_bytes = Column(Integer, default=0, comment="总文件大小(字节)")

    # 去重统计
    duplicate_files = Column(Integer, default=0, comment="重复文件数")
    space_saved_bytes = Column(Integer, default=0, comment="节省空间(字节)")

    # 分类统计
    classified_messages = Column(Integer, default=0, comment="已分类消息数")
    auto_classified = Column(Integer, default=0, comment="自动分类数")
    manual_classified = Column(Integer, default=0, comment="手动分类数")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    # 索引
    __table_args__ = (
        Index('idx_stats_date', 'stat_date'),
    )

    def __repr__(self):
        return f"<SystemStats(date={self.stat_date}, channels={self.total_channels}, messages={self.total_messages})>"
