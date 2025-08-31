# -*- coding: utf-8 -*-
"""
配置管理模块
负责加载和管理应用程序的所有配置项
"""

import os
from pathlib import Path
from typing import List, Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用程序配置类"""
    
    # Telegram Bot 配置
    bot_token: str = Field(..., env="BOT_TOKEN", description="Telegram Bot Token")
    api_id: int = Field(..., env="API_ID", description="Telegram API ID")
    api_hash: str = Field(..., env="API_HASH", description="Telegram API Hash")
    session_name: str = Field("bot_session", env="SESSION_NAME", description="会话名称")

    # 用户权限配置
    admin_user_ids: List[int] = Field(default=[], env="ADMIN_USER_IDS", description="管理员用户ID列表")
    
    # 数据库配置
    database_url: str = Field("sqlite:///./data/bot.db", env="DATABASE_URL", description="数据库连接URL")
    
    # 存储配置
    storage_path: Path = Field(Path("./downloads"), env="STORAGE_PATH", description="文件存储路径")
    max_storage_size_gb: float = Field(10.0, env="MAX_STORAGE_SIZE_GB", description="最大存储空间(GB)")
    max_file_size_mb: float = Field(100.0, env="MAX_FILE_SIZE_MB", description="单个文件最大大小(MB)")
    
    # 采集配置
    enable_video_collection: bool = Field(True, env="ENABLE_VIDEO_COLLECTION", description="启用视频采集")
    enable_image_collection: bool = Field(True, env="ENABLE_IMAGE_COLLECTION", description="启用图片采集")
    collection_interval_seconds: int = Field(30, env="COLLECTION_INTERVAL_SECONDS", description="采集间隔(秒)")
    max_history_days: int = Field(30, env="MAX_HISTORY_DAYS", description="最大历史消息天数")
    
    # 去重配置
    duplicate_threshold: float = Field(0.95, env="DUPLICATE_THRESHOLD", description="去重相似度阈值")
    enable_hash_dedup: bool = Field(True, env="ENABLE_HASH_DEDUP", description="启用哈希去重")
    enable_feature_dedup: bool = Field(True, env="ENABLE_FEATURE_DEDUP", description="启用特征去重")
    
    # 分类配置
    auto_classification: bool = Field(True, env="AUTO_CLASSIFICATION", description="启用自动分类")
    default_tags: List[str] = Field(["未分类"], env="DEFAULT_TAGS", description="默认标签")
    
    # 日志配置
    log_level: str = Field("INFO", env="LOG_LEVEL", description="日志级别")
    log_file: Path = Field(Path("./logs/bot.log"), env="LOG_FILE", description="日志文件路径")
    max_log_size_mb: float = Field(50.0, env="MAX_LOG_SIZE_MB", description="最大日志文件大小(MB)")
    
    # 性能配置
    max_concurrent_downloads: int = Field(3, env="MAX_CONCURRENT_DOWNLOADS", description="最大并发下载数")
    download_timeout_seconds: int = Field(300, env="DOWNLOAD_TIMEOUT_SECONDS", description="下载超时时间(秒)")
    retry_attempts: int = Field(3, env="RETRY_ATTEMPTS", description="重试次数")

    # 存储监控配置
    enable_storage_monitoring: bool = Field(True, env="ENABLE_STORAGE_MONITORING", description="启用存储监控")
    storage_warning_threshold: float = Field(0.8, env="STORAGE_WARNING_THRESHOLD", description="存储空间警告阈值")
    storage_critical_threshold: float = Field(0.9, env="STORAGE_CRITICAL_THRESHOLD", description="存储空间严重警告阈值")
    temp_file_cleanup_hours: int = Field(24, env="TEMP_FILE_CLEANUP_HOURS", description="临时文件清理时间（小时）")
    auto_organize_files: bool = Field(True, env="AUTO_ORGANIZE_FILES", description="自动组织文件")

    # 下载模式配置
    auto_download_mode: str = Field("manual", env="AUTO_DOWNLOAD_MODE", description="下载模式: auto(自动), manual(手动), selective(选择性)")
    auto_download_delay_seconds: int = Field(60, env="AUTO_DOWNLOAD_DELAY_SECONDS", description="自动下载延迟时间（秒）")
    
    class Config:
        """Pydantic配置"""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    @validator("storage_path", "log_file", pre=True)
    def convert_to_path(cls, v):
        """将字符串转换为Path对象"""
        if isinstance(v, str):
            return Path(v)
        return v
    
    @validator("default_tags", pre=True)
    def parse_tags(cls, v):
        """解析标签列表"""
        if isinstance(v, str):
            return [tag.strip() for tag in v.split(",") if tag.strip()]
        return v

    @validator("admin_user_ids", pre=True)
    def parse_admin_user_ids(cls, v):
        """解析管理员用户ID列表"""
        if isinstance(v, str):
            return [int(id.strip()) for id in v.split(",") if id.strip().isdigit()]
        return v
    
    def __init__(self, **kwargs):
        """初始化配置"""
        super().__init__(**kwargs)
        self._ensure_directories()
    
    def _ensure_directories(self):
        """确保必要的目录存在"""
        # 创建存储目录
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # 创建日志目录
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 创建数据目录（如果使用SQLite）
        if self.database_url.startswith("sqlite"):
            db_path = self.database_url.replace("sqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    @property
    def max_file_size_bytes(self) -> int:
        """获取最大文件大小（字节）"""
        return int(self.max_file_size_mb * 1024 * 1024)
    
    @property
    def max_storage_size_bytes(self) -> int:
        """获取最大存储空间（字节）"""
        return int(self.max_storage_size_gb * 1024 * 1024 * 1024)
    
    @property
    def max_log_size_bytes(self) -> int:
        """获取最大日志文件大小（字节）"""
        return int(self.max_log_size_mb * 1024 * 1024)
