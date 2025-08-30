# -*- coding: utf-8 -*-
"""
日志工具模块
提供统一的日志配置和管理功能
"""

import sys
from pathlib import Path
from typing import Optional

from loguru import logger
from rich.console import Console
from rich.logging import RichHandler


def setup_logger(
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
    max_size: str = "50 MB",
    rotation: str = "1 day",
    retention: str = "30 days",
    enable_console: bool = True,
    enable_rich: bool = True
) -> logger:
    """
    设置日志配置
    
    Args:
        log_level: 日志级别
        log_file: 日志文件路径
        max_size: 单个日志文件最大大小
        rotation: 日志轮转周期
        retention: 日志保留时间
        enable_console: 是否启用控制台输出
        enable_rich: 是否启用Rich格式化
    
    Returns:
        配置好的logger实例
    """
    # 移除默认处理器
    logger.remove()
    
    # 日志格式
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    
    # 控制台输出
    if enable_console:
        if enable_rich:
            # 使用Rich处理器
            console = Console()
            rich_handler = RichHandler(
                console=console,
                show_time=True,
                show_path=True,
                markup=True,
                rich_tracebacks=True
            )
            logger.add(
                rich_handler,
                level=log_level,
                format="{message}",
                backtrace=True,
                diagnose=True
            )
        else:
            # 普通控制台输出
            logger.add(
                sys.stdout,
                level=log_level,
                format=log_format,
                colorize=True,
                backtrace=True,
                diagnose=True
            )
    
    # 文件输出
    if log_file:
        # 确保日志目录存在
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 添加文件处理器
        logger.add(
            log_file,
            level=log_level,
            format=log_format,
            rotation=rotation,
            retention=retention,
            compression="zip",
            backtrace=True,
            diagnose=True,
            encoding="utf-8"
        )
        
        # 添加错误日志文件
        error_log_file = log_file.parent / f"{log_file.stem}_error.log"
        logger.add(
            error_log_file,
            level="ERROR",
            format=log_format,
            rotation=rotation,
            retention=retention,
            compression="zip",
            backtrace=True,
            diagnose=True,
            encoding="utf-8"
        )
    
    return logger


def get_logger(name: str = None) -> logger:
    """
    获取logger实例
    
    Args:
        name: logger名称
    
    Returns:
        logger实例
    """
    if name:
        return logger.bind(name=name)
    return logger


class LoggerMixin:
    """日志混入类，为其他类提供日志功能"""
    
    @property
    def logger(self):
        """获取当前类的logger"""
        return get_logger(self.__class__.__name__)
