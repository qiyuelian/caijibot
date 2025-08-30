#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 频道内容采集机器人 - 主程序入口
作者: AI Assistant
创建时间: 2025-08-24
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).parent))

from src.bot.telegram_bot import TelegramBot
from src.config.settings import Settings
from src.database.database_manager import DatabaseManager
from src.utils.logger import setup_logger


async def main():
    """主程序入口"""
    # 设置日志
    logger = setup_logger()
    logger.info("启动 Telegram 频道内容采集机器人...")
    
    try:
        # 加载配置
        settings = Settings()
        logger.info("配置加载完成")
        
        # 初始化数据库
        db_manager = DatabaseManager(settings.database_url)
        await db_manager.initialize()
        logger.info("数据库初始化完成")
        
        # 创建并启动机器人
        bot = TelegramBot(settings, db_manager)
        logger.info("机器人初始化完成，开始运行...")
        
        # 启动机器人
        await bot.start()
        
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭机器人...")
    except Exception as e:
        logger.error(f"程序运行出错: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("机器人已停止")


if __name__ == "__main__":
    # 运行主程序
    asyncio.run(main())
