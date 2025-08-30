# -*- coding: utf-8 -*-
"""
下载模式管理器
管理不同的下载模式和策略
"""

from enum import Enum
from typing import Dict, Any, List
from datetime import datetime

from ..database.database_manager import DatabaseManager
from ..database.models import Message, MediaType
from ..config.settings import Settings
from ..utils.logger import LoggerMixin


class DownloadMode(str, Enum):
    """下载模式枚举"""
    AUTO = "auto"           # 自动下载所有文件
    MANUAL = "manual"       # 手动下载
    SELECTIVE = "selective" # 选择性自动下载


class DownloadModeManager(LoggerMixin):
    """下载模式管理器"""
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        初始化下载模式管理器
        
        Args:
            db_manager: 数据库管理器
            settings: 配置对象
        """
        self.db_manager = db_manager
        self.settings = settings
        
        # 当前下载模式
        self.current_mode = DownloadMode(settings.auto_download_mode)
        
        # 选择性下载规则
        self.selective_rules = {
            MediaType.IMAGE: {
                "auto_download": True,
                "max_size_mb": 10,
                "priority": 1
            },
            MediaType.VIDEO: {
                "auto_download": True,
                "max_size_mb": 50,
                "priority": 2
            },
            MediaType.AUDIO: {
                "auto_download": True,
                "max_size_mb": 20,
                "priority": 1
            },
            MediaType.DOCUMENT: {
                "auto_download": False,  # 文档默认不自动下载
                "max_size_mb": 10,
                "priority": 0
            }
        }
        
        self.logger.info(f"下载模式管理器初始化完成，当前模式: {self.current_mode}")
    
    def get_current_mode(self) -> DownloadMode:
        """获取当前下载模式"""
        return self.current_mode
    
    def set_download_mode(self, mode: DownloadMode) -> bool:
        """
        设置下载模式
        
        Args:
            mode: 下载模式
        
        Returns:
            bool: 是否设置成功
        """
        try:
            self.current_mode = mode
            self.settings.auto_download_mode = mode.value
            
            self.logger.info(f"下载模式已更改为: {mode.value}")
            return True
            
        except Exception as e:
            self.logger.error(f"设置下载模式失败: {e}")
            return False
    
    def should_auto_download(self, message: Message) -> Dict[str, Any]:
        """
        判断是否应该自动下载文件
        
        Args:
            message: 消息对象
        
        Returns:
            Dict: 下载决策信息
        """
        try:
            if self.current_mode == DownloadMode.MANUAL:
                return {
                    "should_download": False,
                    "reason": "手动下载模式",
                    "priority": 0
                }
            
            elif self.current_mode == DownloadMode.AUTO:
                # 检查基本限制
                if message.file_size and message.file_size > self.settings.max_file_size_bytes:
                    return {
                        "should_download": False,
                        "reason": "文件超过最大大小限制",
                        "priority": 0
                    }
                
                return {
                    "should_download": True,
                    "reason": "自动下载模式",
                    "priority": 1
                }
            
            elif self.current_mode == DownloadMode.SELECTIVE:
                return self._evaluate_selective_download(message)
            
            return {
                "should_download": False,
                "reason": "未知下载模式",
                "priority": 0
            }
            
        except Exception as e:
            self.logger.error(f"判断自动下载失败: {e}")
            return {
                "should_download": False,
                "reason": f"判断出错: {e}",
                "priority": 0
            }
    
    def _evaluate_selective_download(self, message: Message) -> Dict[str, Any]:
        """
        评估选择性下载
        
        Args:
            message: 消息对象
        
        Returns:
            Dict: 下载决策信息
        """
        try:
            media_type = message.media_type
            rules = self.selective_rules.get(media_type)
            
            if not rules:
                return {
                    "should_download": False,
                    "reason": f"媒体类型 {media_type} 没有选择性下载规则",
                    "priority": 0
                }
            
            # 检查是否启用自动下载
            if not rules["auto_download"]:
                return {
                    "should_download": False,
                    "reason": f"{media_type} 类型未启用自动下载",
                    "priority": 0
                }
            
            # 检查文件大小限制
            max_size_bytes = rules["max_size_mb"] * 1024 * 1024
            if message.file_size and message.file_size > max_size_bytes:
                return {
                    "should_download": False,
                    "reason": f"文件大小 ({message.file_size / (1024*1024):.1f} MB) 超过 {media_type} 类型限制 ({rules['max_size_mb']} MB)",
                    "priority": 0
                }
            
            # 通过所有检查，可以自动下载
            return {
                "should_download": True,
                "reason": f"{media_type} 类型选择性自动下载",
                "priority": rules["priority"]
            }
            
        except Exception as e:
            self.logger.error(f"评估选择性下载失败: {e}")
            return {
                "should_download": False,
                "reason": f"评估出错: {e}",
                "priority": 0
            }
    
    def update_selective_rules(self, media_type: MediaType, rules: Dict[str, Any]) -> bool:
        """
        更新选择性下载规则
        
        Args:
            media_type: 媒体类型
            rules: 新规则
        
        Returns:
            bool: 是否更新成功
        """
        try:
            if media_type in self.selective_rules:
                self.selective_rules[media_type].update(rules)
                self.logger.info(f"更新 {media_type} 的选择性下载规则")
                return True
            else:
                self.logger.error(f"不支持的媒体类型: {media_type}")
                return False
                
        except Exception as e:
            self.logger.error(f"更新选择性下载规则失败: {e}")
            return False
    
    def get_selective_rules(self) -> Dict[MediaType, Dict[str, Any]]:
        """获取选择性下载规则"""
        return self.selective_rules.copy()
    
    def get_mode_description(self) -> str:
        """
        获取当前模式的描述
        
        Returns:
            str: 模式描述
        """
        descriptions = {
            DownloadMode.AUTO: "🔄 自动下载所有文件（在大小限制内）",
            DownloadMode.MANUAL: "👤 手动下载，需要用户主动触发",
            DownloadMode.SELECTIVE: "🎯 选择性自动下载，根据文件类型和大小智能决策"
        }
        
        return descriptions.get(self.current_mode, "❓ 未知模式")
    
    def get_download_stats_by_mode(self) -> Dict[str, Any]:
        """
        获取按模式分类的下载统计
        
        Returns:
            Dict: 统计信息
        """
        try:
            # 这里可以添加更详细的统计逻辑
            return {
                "current_mode": self.current_mode.value,
                "mode_description": self.get_mode_description(),
                "selective_rules": {
                    media_type.value: rules 
                    for media_type, rules in self.selective_rules.items()
                },
                "auto_download_delay": self.settings.auto_download_delay_seconds
            }
            
        except Exception as e:
            self.logger.error(f"获取下载模式统计失败: {e}")
            return {"error": str(e)}
