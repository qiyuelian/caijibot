# -*- coding: utf-8 -*-
"""
Telegram机器人主类
负责处理用户交互和机器人命令
"""

import asyncio
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from ..config.settings import Settings
from ..database.database_manager import DatabaseManager
from ..classifier.auto_classifier import AutoClassifier
from ..classifier.tag_manager import TagManager
from ..deduplicator.dedup_manager import DeduplicationManager
from ..storage.file_manager import FileManager
from ..storage.download_manager import DownloadManager
from ..storage.storage_monitor import StorageMonitor
from ..statistics.tag_statistics import TagStatistics
from ..utils.logger import LoggerMixin
from .command_helper import CommandHelper


class TelegramBot(LoggerMixin):
    """Telegram机器人主类"""
    
    def __init__(self, settings: Settings, db_manager: DatabaseManager):
        """
        初始化Telegram机器人
        
        Args:
            settings: 配置对象
            db_manager: 数据库管理器
        """
        self.settings = settings
        self.db_manager = db_manager
        
        # Bot应用程序
        self.application = None
        
        # Telegram客户端（用于频道消息采集）
        self.client = None

        # 分类器和标签管理器
        self.auto_classifier = AutoClassifier(db_manager, settings)
        self.tag_manager = TagManager(db_manager)

        # 去重管理器
        self.dedup_manager = DeduplicationManager(db_manager, settings)

        # 存储管理器
        self.file_manager = FileManager(db_manager, settings)
        self.download_manager = DownloadManager(
            db_manager,
            None,  # Telegram客户端稍后设置
            self.file_manager,
            settings
        )
        self.storage_monitor = StorageMonitor(db_manager, settings)

        # 命令帮助管理器
        self.command_helper = CommandHelper()

        # 标签统计管理器
        self.tag_statistics = TagStatistics(db_manager)

        # 运行状态
        self.is_running = False
        
        self.logger.info("Telegram机器人初始化完成")
    
    async def initialize(self):
        """初始化机器人和客户端"""
        try:
            # 初始化Bot应用程序
            self.application = Application.builder().token(self.settings.bot_token).build()
            
            # 注册命令处理器
            self._register_handlers()
            
            # 初始化Telegram客户端
            self.client = TelegramClient(
                self.settings.session_name,
                self.settings.api_id,
                self.settings.api_hash
            )
            
            # 启动客户端
            await self.client.start()
            
            # 检查是否需要登录
            if not await self.client.is_user_authorized():
                self.logger.warning("Telegram客户端未授权，需要手动登录")
            
            self.logger.info("Telegram机器人和客户端初始化完成")
            
        except Exception as e:
            self.logger.error(f"初始化Telegram机器人失败: {e}")
            raise
    
    def _register_handlers(self):
        """注册命令处理器"""
        # 基本命令
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        
        # 频道管理命令
        self.application.add_handler(CommandHandler("add_channel", self.add_channel_command))
        self.application.add_handler(CommandHandler("remove_channel", self.remove_channel_command))
        self.application.add_handler(CommandHandler("list_channels", self.list_channels_command))
        
        # 统计和搜索命令
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("search", self.search_command))
        
        # 设置命令
        self.application.add_handler(CommandHandler("settings", self.settings_command))

        # 标签和分类命令
        self.application.add_handler(CommandHandler("tags", self.tags_command))
        self.application.add_handler(CommandHandler("classify", self.classify_command))

        # 去重命令
        self.application.add_handler(CommandHandler("dedup", self.dedup_command))

        # 存储管理命令
        self.application.add_handler(CommandHandler("storage", self.storage_command))
        self.application.add_handler(CommandHandler("downloads", self.downloads_command))
        self.application.add_handler(CommandHandler("download_mode", self.download_mode_command))

        # 管理命令
        self.application.add_handler(CommandHandler("queue_downloads", self.queue_downloads_command))
        self.application.add_handler(CommandHandler("cleanup_temp", self.cleanup_temp_command))
        self.application.add_handler(CommandHandler("system_info", self.system_info_command))

        # 标签统计命令
        self.application.add_handler(CommandHandler("tag_stats", self.tag_stats_command))
        self.application.add_handler(CommandHandler("media_by_tag", self.media_by_tag_command))

        # 回调查询处理器
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # 消息处理器
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        self.logger.info("命令处理器注册完成")
    
    async def start(self):
        """启动机器人"""
        try:
            # 初始化
            await self.initialize()
            
            # 启动Bot应用程序
            await self.application.initialize()
            await self.application.start()
            
            self.is_running = True
            self.logger.info("Telegram机器人启动成功")
            
            # 启动自动分类器
            if self.settings.auto_classification:
                asyncio.create_task(self.auto_classifier.start_auto_classification())

            # 启动去重管理器
            if self.settings.enable_hash_dedup or self.settings.enable_feature_dedup:
                asyncio.create_task(self.dedup_manager.start_auto_deduplication())

            # 初始化存储系统
            await self.file_manager.initialize_storage()

            # 启动下载管理器
            asyncio.create_task(self.download_manager.start_download_worker())

            # 启动存储监控器
            asyncio.create_task(self.storage_monitor.start_monitoring())

            # 开始轮询
            await self.application.updater.start_polling()

            # 保持运行
            while self.is_running:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            self.logger.info("收到停止信号")
        except Exception as e:
            self.logger.error(f"机器人运行出错: {e}")
            raise
        finally:
            await self.stop()
    
    async def stop(self):
        """停止机器人"""
        try:
            self.is_running = False

            # 停止所有后台服务
            await self.auto_classifier.stop_auto_classification()
            await self.dedup_manager.stop_auto_deduplication()
            await self.download_manager.stop_download_worker()
            await self.storage_monitor.stop_monitoring()

            if self.application:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()

            if self.client:
                await self.client.disconnect()

            self.logger.info("Telegram机器人已停止")
            
        except Exception as e:
            self.logger.error(f"停止机器人时出错: {e}")
    
    # 命令处理方法
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/start命令"""
        user = update.effective_user
        welcome_text = f"""
🤖 欢迎使用Telegram频道内容采集机器人！

👋 你好 {user.first_name}！

这个机器人可以帮助你：
📺 采集频道中的视频和图片
🏷️ 自动分类和标记内容
🔍 检测和去除重复文件
📊 提供详细的统计信息

使用 /help 查看所有可用命令。
        """
        
        # 创建快捷操作按钮
        keyboard = [
            [InlineKeyboardButton("📋 查看频道列表", callback_data="list_channels")],
            [InlineKeyboardButton("➕ 添加频道", callback_data="add_channel")],
            [InlineKeyboardButton("📊 查看统计", callback_data="stats")],
            [InlineKeyboardButton("⚙️ 设置", callback_data="settings")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
        self.logger.info(f"用户 {user.id} 启动了机器人")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/help命令"""
        try:
            # 如果指定了特定命令，显示详细帮助
            if context.args:
                command_name = context.args[0].lstrip('/')
                help_text = self.command_helper.get_command_help(command_name)
                await update.message.reply_text(help_text, parse_mode='Markdown')
                return

            # 显示快速帮助
            help_text = self.command_helper.get_quick_help()

            # 创建分类按钮
            categories = self.command_helper.get_all_categories()
            keyboard = []

            # 每行两个按钮
            for i in range(0, len(categories), 2):
                row = []
                for j in range(2):
                    if i + j < len(categories):
                        category = categories[i + j]
                        row.append(InlineKeyboardButton(
                            category,
                            callback_data=f"help_category_{category}"
                        ))
                keyboard.append(row)

            # 添加搜索按钮
            keyboard.append([InlineKeyboardButton("🔍 搜索命令", callback_data="help_search")])

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取帮助信息失败: {e}")
            self.logger.error(f"处理help命令失败: {e}")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/status命令"""
        try:
            # 获取数据库状态
            db_healthy = await self.db_manager.health_check()
            
            # 获取客户端状态
            client_connected = self.client and self.client.is_connected()
            
            status_text = f"""
🔍 **机器人状态**

🤖 机器人: {'✅ 运行中' if self.is_running else '❌ 已停止'}
🗄️ 数据库: {'✅ 正常' if db_healthy else '❌ 异常'}
📡 客户端: {'✅ 已连接' if client_connected else '❌ 未连接'}

⏰ 运行时间: {self._get_uptime()}
💾 内存使用: {self._get_memory_usage()}
            """
            
            await update.message.reply_text(status_text, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"获取状态信息失败: {e}")
            self.logger.error(f"获取状态失败: {e}")
    
    async def add_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/add_channel命令"""
        if not context.args:
            await update.message.reply_text(
                "请提供频道链接或用户名\n"
                "例如: /add_channel https://t.me/example_channel\n"
                "或: /add_channel @example_channel"
            )
            return
        
        channel_input = context.args[0]
        user_id = str(update.effective_user.id)
        
        try:
            # 这里会调用频道管理器来添加频道
            # 暂时返回成功消息
            await update.message.reply_text(
                f"✅ 正在添加频道: {channel_input}\n"
                "请稍等，正在验证频道信息..."
            )
            
            self.logger.info(f"用户 {user_id} 请求添加频道: {channel_input}")
            
        except Exception as e:
            await update.message.reply_text(f"添加频道失败: {e}")
            self.logger.error(f"添加频道失败: {e}")
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理按钮回调"""
        query = update.callback_query
        await query.answer()

        data = query.data

        if data == "list_channels":
            await self.list_channels_command(update, context)
        elif data == "add_channel":
            await query.edit_message_text("请使用命令: /add_channel <频道链接>")
        elif data == "stats":
            await self.stats_command(update, context)
        elif data == "settings":
            await self.settings_command(update, context)
        elif data == "list_all_tags":
            await self._handle_list_tags_callback(query)
        elif data == "create_tag":
            await query.edit_message_text("请使用格式: /create_tag <标签名> [描述]")
        elif data == "search_tags":
            await query.edit_message_text("请使用格式: /search_tags <关键词>")
        elif data == "manual_classify":
            await self._handle_manual_classify_callback(query)
        elif data == "classification_rules":
            await self._handle_classification_rules_callback(query)
        elif data == "classification_details":
            await self._handle_classification_details_callback(query)
        elif data == "manual_dedup":
            await self._handle_manual_dedup_callback(query)
        elif data == "duplicate_report":
            await self._handle_duplicate_report_callback(query)
        elif data == "dedup_details":
            await self._handle_dedup_details_callback(query)
        elif data == "storage_report":
            await self._handle_storage_report_callback(query)
        elif data == "storage_cleanup":
            await self._handle_storage_cleanup_callback(query)
        elif data == "storage_monitor":
            await self._handle_storage_monitor_callback(query)
        elif data == "pause_downloads":
            await self._handle_pause_downloads_callback(query)
        elif data == "resume_downloads":
            await self._handle_resume_downloads_callback(query)
        elif data == "retry_downloads":
            await self._handle_retry_downloads_callback(query)
        elif data.startswith("set_download_mode_"):
            mode = data.replace("set_download_mode_", "")
            await self._handle_set_download_mode_callback(query, mode)
        elif data.startswith("confirm_remove_channel_"):
            channel_id = int(data.replace("confirm_remove_channel_", ""))
            await self._handle_confirm_remove_channel_callback(query, channel_id)
        elif data == "cancel_operation":
            await query.edit_message_text("❌ 操作已取消")
        elif data == "add_channel_prompt":
            await self._handle_add_channel_prompt_callback(query)
        elif data == "remove_channel_prompt":
            await self._handle_remove_channel_prompt_callback(query)
        elif data == "refresh_channels":
            await self._handle_refresh_channels_callback(query)
        elif data.startswith("help_category_"):
            category = data.replace("help_category_", "")
            await self._handle_help_category_callback(query, category)
        elif data == "help_search":
            await self._handle_help_search_callback(query)
        elif data == "back_to_help":
            await self._handle_back_to_help_callback(query)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理普通消息"""
        # 这里可以处理用户发送的普通消息
        pass
    
    def _get_uptime(self) -> str:
        """获取运行时间"""
        # 简单实现，实际应该记录启动时间
        return "未知"
    
    def _get_memory_usage(self) -> str:
        """获取内存使用情况"""
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            return f"{memory_mb:.1f} MB"
        except ImportError:
            return "未知"
    
    # 其他命令处理方法将在后续实现
    async def list_channels_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/list_channels命令"""
        try:
            async with self.db_manager.get_async_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Channel).order_by(Channel.created_at.desc())
                )
                channels = result.scalars().all()

            if not channels:
                await update.message.reply_text("📭 暂无已添加的频道")
                return

            text = "📋 **已添加的频道列表**\n\n"

            for i, channel in enumerate(channels, 1):
                status_emoji = {
                    ChannelStatus.ACTIVE: "🟢",
                    ChannelStatus.INACTIVE: "🟡",
                    ChannelStatus.ERROR: "🔴"
                }.get(channel.status, "⚪")

                # 获取消息统计
                async with self.db_manager.get_async_session() as session:
                    from sqlalchemy import func
                    count_result = await session.execute(
                        select(func.count(Message.id)).where(
                            Message.channel_id == channel.id
                        )
                    )
                    message_count = count_result.scalar()

                text += f"{i}. {status_emoji} **{channel.channel_title}**\n"
                text += f"   • ID: `{channel.channel_id}`\n"
                text += f"   • 消息数: {message_count}\n"
                text += f"   • 状态: {channel.status.value}\n"
                if channel.last_check_time:
                    text += f"   • 最后检查: {channel.last_check_time.strftime('%Y-%m-%d %H:%M')}\n"
                text += "\n"

            # 创建管理按钮
            keyboard = [
                [InlineKeyboardButton("➕ 添加频道", callback_data="add_channel_prompt")],
                [InlineKeyboardButton("🗑️ 移除频道", callback_data="remove_channel_prompt")],
                [InlineKeyboardButton("🔄 刷新状态", callback_data="refresh_channels")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取频道列表失败: {e}")
            self.logger.error(f"处理list_channels命令失败: {e}")
    
    async def remove_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/remove_channel命令"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "请提供要移除的频道ID或链接\n"
                    "例如: /remove_channel @example_channel\n"
                    "或: /remove_channel -1001234567890"
                )
                return

            channel_identifier = context.args[0]

            # 查找频道
            async with self.db_manager.get_async_session() as session:
                from sqlalchemy import select, delete

                # 尝试按不同方式查找频道
                if channel_identifier.startswith('@'):
                    # 按用户名查找
                    result = await session.execute(
                        select(Channel).where(Channel.channel_username == channel_identifier[1:])
                    )
                elif channel_identifier.startswith('-'):
                    # 按ID查找
                    result = await session.execute(
                        select(Channel).where(Channel.channel_id == channel_identifier)
                    )
                else:
                    # 按标题模糊查找
                    result = await session.execute(
                        select(Channel).where(Channel.channel_title.like(f"%{channel_identifier}%"))
                    )

                channel = result.scalar_one_or_none()

                if not channel:
                    await update.message.reply_text(f"❌ 未找到频道: {channel_identifier}")
                    return

                # 询问确认
                text = f"""
⚠️ **确认移除频道**

📺 **频道**: {channel.channel_title}
🆔 **ID**: `{channel.channel_id}`
📊 **状态**: {channel.status.value}

❗ **注意**: 移除频道将删除所有相关的消息记录和文件！

确定要移除这个频道吗？
                """

                keyboard = [
                    [InlineKeyboardButton("✅ 确认移除", callback_data=f"confirm_remove_channel_{channel.id}")],
                    [InlineKeyboardButton("❌ 取消", callback_data="cancel_operation")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"处理移除频道命令失败: {e}")
            self.logger.error(f"处理remove_channel命令失败: {e}")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/stats命令"""
        try:
            # 获取各种统计信息
            async with self.db_manager.get_async_session() as session:
                from sqlalchemy import func

                # 频道统计
                channel_count = await session.execute(select(func.count(Channel.id)))
                channel_count = channel_count.scalar()

                # 消息统计
                total_messages = await session.execute(select(func.count(Message.id)))
                total_messages = total_messages.scalar()

                # 按状态统计消息
                status_stats = {}
                for status in MessageStatus:
                    count = await session.execute(
                        select(func.count(Message.id)).where(Message.status == status)
                    )
                    status_stats[status.value] = count.scalar()

                # 按媒体类型统计
                type_stats = {}
                for media_type in MediaType:
                    count = await session.execute(
                        select(func.count(Message.id)).where(Message.media_type == media_type)
                    )
                    type_stats[media_type.value] = count.scalar()

                # 文件大小统计
                total_size = await session.execute(
                    select(func.sum(Message.file_size)).where(Message.file_size.isnot(None))
                )
                total_size = total_size.scalar() or 0

            # 格式化统计信息
            text = f"""
📊 **系统统计信息**

📺 **频道统计**:
• 总频道数: {channel_count}

📄 **消息统计**:
• 总消息数: {total_messages}
• 待处理: {status_stats.get('pending', 0)}
• 已完成: {status_stats.get('completed', 0)}
• 重复文件: {status_stats.get('duplicate', 0)}
• 失败: {status_stats.get('failed', 0)}

🎬 **媒体类型统计**:
• 视频: {type_stats.get('video', 0)}
• 图片: {type_stats.get('image', 0)}
• 音频: {type_stats.get('audio', 0)}
• 文档: {type_stats.get('document', 0)}

💾 **存储统计**:
• 总文件大小: {total_size / (1024*1024*1024):.2f} GB
• 平均文件大小: {(total_size / total_messages / (1024*1024)) if total_messages > 0 else 0:.1f} MB
            """

            # 创建详细统计按钮
            keyboard = [
                [InlineKeyboardButton("📊 详细统计", callback_data="detailed_stats")],
                [InlineKeyboardButton("📈 性能指标", callback_data="performance_stats")],
                [InlineKeyboardButton("🔄 刷新数据", callback_data="refresh_stats")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取统计信息失败: {e}")
            self.logger.error(f"处理stats命令失败: {e}")
    
    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/search命令"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "🔍 **搜索帮助**\n\n"
                    "请提供搜索关键词:\n"
                    "`/search 关键词`\n\n"
                    "**搜索范围**:\n"
                    "• 文件名\n"
                    "• 消息文本\n"
                    "• 标签\n\n"
                    "**示例**:\n"
                    "`/search 猫咪视频`\n"
                    "`/search .mp4`\n"
                    "`/search #搞笑`",
                    parse_mode='Markdown'
                )
                return

            search_term = " ".join(context.args)

            # 搜索消息
            async with self.db_manager.get_async_session() as session:
                from sqlalchemy import or_

                result = await session.execute(
                    select(Message).where(
                        or_(
                            Message.file_name.like(f"%{search_term}%"),
                            Message.message_text.like(f"%{search_term}%")
                        )
                    ).limit(20).order_by(Message.created_at.desc())
                )

                messages = result.scalars().all()

            if not messages:
                await update.message.reply_text(f"🔍 未找到包含 '{search_term}' 的内容")
                return

            text = f"🔍 **搜索结果** (关键词: {search_term})\n\n"

            for i, msg in enumerate(messages[:10], 1):  # 只显示前10个结果
                # 获取频道信息
                async with self.db_manager.get_async_session() as session:
                    channel_result = await session.execute(
                        select(Channel).where(Channel.id == msg.channel_id)
                    )
                    channel = channel_result.scalar_one_or_none()

                channel_name = channel.channel_title if channel else "未知频道"

                status_emoji = {
                    MessageStatus.PENDING: "⏳",
                    MessageStatus.COMPLETED: "✅",
                    MessageStatus.DUPLICATE: "🔄",
                    MessageStatus.FAILED: "❌"
                }.get(msg.status, "❓")

                text += f"{i}. {status_emoji} **{msg.file_name}**\n"
                text += f"   📺 {channel_name}\n"
                text += f"   📅 {msg.message_date.strftime('%Y-%m-%d %H:%M')}\n"
                text += f"   📊 {msg.media_type.value} • {(msg.file_size or 0) / (1024*1024):.1f} MB\n"
                if msg.message_text and len(msg.message_text) > 0:
                    preview = msg.message_text[:50] + "..." if len(msg.message_text) > 50 else msg.message_text
                    text += f"   💬 {preview}\n"
                text += "\n"

            if len(messages) > 10:
                text += f"... 还有 {len(messages) - 10} 个结果未显示"

            await update.message.reply_text(text, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"搜索失败: {e}")
            self.logger.error(f"处理search命令失败: {e}")
    
    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/settings命令"""
        try:
            # 显示当前设置
            text = f"""
⚙️ **系统设置**

📁 **存储设置**:
• 存储路径: `{self.settings.storage_path}`
• 最大文件大小: {self.settings.max_file_size_mb} MB
• 最大存储空间: {self.settings.max_storage_size_gb} GB

⬇️ **下载设置**:
• 下载模式: {self.settings.auto_download_mode}
• 最大并发下载: {self.settings.max_concurrent_downloads}
• 下载延迟: {self.settings.auto_download_delay_seconds} 秒

🎯 **采集设置**:
• 视频采集: {'✅ 启用' if self.settings.enable_video_collection else '❌ 禁用'}
• 图片采集: {'✅ 启用' if self.settings.enable_image_collection else '❌ 禁用'}
• 采集间隔: {self.settings.collection_interval_seconds} 秒

🔄 **去重设置**:
• 哈希去重: {'✅ 启用' if self.settings.enable_hash_dedup else '❌ 禁用'}
• 特征去重: {'✅ 启用' if self.settings.enable_feature_dedup else '❌ 禁用'}
• 相似度阈值: {self.settings.duplicate_threshold:.0%}

🤖 **分类设置**:
• 自动分类: {'✅ 启用' if self.settings.auto_classification else '❌ 禁用'}
• 默认标签: {', '.join(self.settings.default_tags)}
            """

            # 创建设置管理按钮
            keyboard = [
                [InlineKeyboardButton("📁 存储设置", callback_data="settings_storage")],
                [InlineKeyboardButton("⬇️ 下载设置", callback_data="settings_download")],
                [InlineKeyboardButton("🎯 采集设置", callback_data="settings_collection")],
                [InlineKeyboardButton("🔄 去重设置", callback_data="settings_dedup")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取设置信息失败: {e}")
            self.logger.error(f"处理settings命令失败: {e}")

    async def tags_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/tags命令"""
        try:
            # 获取标签统计
            stats = await self.tag_manager.get_tag_stats()

            if "error" in stats:
                await update.message.reply_text(f"获取标签信息失败: {stats['error']}")
                return

            # 格式化标签信息
            text = f"""
🏷️ **标签统计信息**

📊 **总体统计**:
• 总标签数: {stats['total_tags']}
• 使用中标签: {stats['used_tags']}
• 未使用标签: {stats['unused_tags']}

🔥 **热门标签**:
"""

            for tag in stats['popular_tags'][:5]:
                text += f"• {tag['name']} ({tag['usage_count']} 次使用)\n"

            if stats['recent_tags']:
                text += "\n🆕 **最近创建**:\n"
                for tag in stats['recent_tags'][:3]:
                    text += f"• {tag['name']}\n"

            # 创建操作按钮
            keyboard = [
                [InlineKeyboardButton("📋 查看所有标签", callback_data="list_all_tags")],
                [InlineKeyboardButton("➕ 创建标签", callback_data="create_tag")],
                [InlineKeyboardButton("🔍 搜索标签", callback_data="search_tags")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取标签信息失败: {e}")
            self.logger.error(f"处理tags命令失败: {e}")

    async def classify_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/classify命令"""
        try:
            # 获取分类统计
            stats = await self.auto_classifier.get_classification_stats()

            if "error" in stats:
                await update.message.reply_text(f"获取分类信息失败: {stats['error']}")
                return

            # 格式化分类信息
            text = f"""
🤖 **自动分类统计**

📊 **分类概况**:
• 总消息数: {stats['total_messages']}
• 已分类消息: {stats['classified_messages']}
• 自动分类: {stats['auto_classified']}
• 手动分类: {stats['manual_classified']}
• 分类率: {stats['classification_rate']:.1%}

🔄 **运行状态**:
• 分类器状态: {'🟢 运行中' if stats['is_running'] else '🔴 已停止'}
• 已处理: {stats['runtime_stats']['processed']}
• 已分类: {stats['runtime_stats']['classified']}
• 错误数: {stats['runtime_stats']['errors']}
            """

            # 创建操作按钮
            keyboard = [
                [InlineKeyboardButton("🔄 手动分类", callback_data="manual_classify")],
                [InlineKeyboardButton("⚙️ 分类规则", callback_data="classification_rules")],
                [InlineKeyboardButton("📈 详细统计", callback_data="classification_details")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取分类信息失败: {e}")
            self.logger.error(f"处理classify命令失败: {e}")

    async def dedup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/dedup命令"""
        try:
            # 获取去重统计
            stats = await self.dedup_manager.get_deduplication_stats()

            if "error" in stats:
                await update.message.reply_text(f"获取去重信息失败: {stats['error']}")
                return

            # 格式化去重信息
            text = f"""
🔍 **去重检测统计**

📊 **总体统计**:
• 总消息数: {stats['total_messages']}
• 重复消息: {stats['duplicate_messages']}
• 唯一消息: {stats['unique_messages']}
• 去重记录: {stats['duplicate_records']}
• 去重率: {stats['deduplication_rate']:.1%}

🔧 **功能状态**:
• 哈希去重: {'✅ 启用' if stats['settings']['hash_dedup_enabled'] else '❌ 禁用'}
• 特征去重: {'✅ 启用' if stats['settings']['feature_dedup_enabled'] else '❌ 禁用'}
• 相似度阈值: {stats['settings']['duplicate_threshold']:.2f}

🔄 **运行状态**:
• 去重器状态: {'🟢 运行中' if stats['is_running'] else '🔴 已停止'}
• 已处理: {stats['runtime_stats']['processed']}
• 发现重复: {stats['runtime_stats']['duplicates_found']}
• 错误数: {stats['runtime_stats']['errors']}
            """

            # 创建操作按钮
            keyboard = [
                [InlineKeyboardButton("🔄 手动去重", callback_data="manual_dedup")],
                [InlineKeyboardButton("📋 重复文件报告", callback_data="duplicate_report")],
                [InlineKeyboardButton("📈 详细统计", callback_data="dedup_details")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取去重信息失败: {e}")
            self.logger.error(f"处理dedup命令失败: {e}")

    async def storage_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/storage命令"""
        try:
            # 获取存储统计
            report = await self.storage_monitor.get_comprehensive_report()

            if "error" in report:
                await update.message.reply_text(f"获取存储信息失败: {report['error']}")
                return

            disk_usage = report["disk_usage"]
            storage_usage = report["storage_usage"]
            db_stats = report["database_stats"]

            # 格式化存储信息
            text = f"""
💾 **存储使用情况**

🖥️ **磁盘空间**:
• 总容量: {disk_usage['total'] / (1024**3):.1f} GB
• 已使用: {disk_usage['used'] / (1024**3):.1f} GB ({disk_usage['usage_ratio']:.1%})
• 剩余空间: {disk_usage['free'] / (1024**3):.1f} GB

📁 **项目存储**:
• 文件总数: {storage_usage['total_files']}
• 占用空间: {storage_usage['total_size_gb']:.2f} GB
• 存储路径: `{storage_usage['storage_path']}`

📊 **按类型统计**:
"""

            for media_type, stats in db_stats["by_media_type"].items():
                if stats["file_count"] > 0:
                    text += f"• {media_type}: {stats['file_count']} 个文件 ({stats['total_size_mb']:.1f} MB)\n"

            # 一致性检查
            consistency = report["consistency_check"]
            if not consistency["is_consistent"]:
                text += f"\n⚠️ **数据一致性警告**: 数据库与实际文件大小差异 {consistency['size_difference_mb']:.1f} MB"

            # 创建操作按钮
            keyboard = [
                [InlineKeyboardButton("📊 详细报告", callback_data="storage_report")],
                [InlineKeyboardButton("🧹 清理文件", callback_data="storage_cleanup")],
                [InlineKeyboardButton("📈 监控状态", callback_data="storage_monitor")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取存储信息失败: {e}")
            self.logger.error(f"处理storage命令失败: {e}")

    async def downloads_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/downloads命令"""
        try:
            # 获取下载统计
            stats = await self.download_manager.get_download_stats()

            if "error" in stats:
                await update.message.reply_text(f"获取下载信息失败: {stats['error']}")
                return

            # 获取活跃下载信息
            active_downloads = await self.download_manager.get_active_downloads_info()

            # 格式化下载信息
            text = f"""
⬇️ **下载管理状态**

📊 **下载统计**:
• 队列中: {stats['queue_size']} 个任务
• 正在下载: {stats['active_downloads']} / {stats['max_concurrent']}
• 已完成: {stats['total_completed']}
• 失败: {stats['total_failed']}
• 总下载量: {stats['total_mb_downloaded']:.1f} MB

⚡ **性能指标**:
"""

            if stats.get("download_rate_mbps"):
                text += f"• 下载速度: {stats['download_rate_mbps']:.2f} MB/s\n"
            if stats.get("files_per_minute"):
                text += f"• 处理速度: {stats['files_per_minute']:.1f} 文件/分钟\n"

            text += f"\n🔄 **下载器状态**: {'🟢 运行中' if stats['is_downloading'] else '🔴 已停止'}"

            # 显示活跃下载
            if active_downloads:
                text += f"\n\n📥 **当前下载** (前5个):\n"
                for download in active_downloads[:5]:
                    progress_bar = "█" * int(download["progress"] * 10) + "░" * (10 - int(download["progress"] * 10))
                    text += f"• {download['file_name'][:30]}...\n"
                    text += f"  [{progress_bar}] {download['progress']:.1%}\n"

            # 创建操作按钮
            keyboard = [
                [InlineKeyboardButton("⏸️ 暂停下载", callback_data="pause_downloads")],
                [InlineKeyboardButton("▶️ 恢复下载", callback_data="resume_downloads")],
                [InlineKeyboardButton("🔄 重试失败", callback_data="retry_downloads")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取下载信息失败: {e}")
            self.logger.error(f"处理downloads命令失败: {e}")

    async def download_mode_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/download_mode命令"""
        try:
            current_mode = self.settings.auto_download_mode

            text = f"""
⚙️ **下载模式设置**

🔄 **当前模式**: {current_mode}

📋 **可用模式**:
• **auto** - 自动下载所有文件（在大小限制内）
• **manual** - 手动下载，需要用户主动触发
• **selective** - 选择性自动下载，根据文件类型智能决策

🎯 **选择性下载规则**:
• 图片: 自动下载 ≤ 10MB
• 视频: 自动下载 ≤ 50MB
• 音频: 自动下载 ≤ 20MB
• 文档: 手动下载

💡 使用 `/download_mode <模式>` 切换模式
例如: `/download_mode auto`
            """

            # 创建模式切换按钮
            keyboard = [
                [InlineKeyboardButton("🔄 自动模式", callback_data="set_download_mode_auto")],
                [InlineKeyboardButton("👤 手动模式", callback_data="set_download_mode_manual")],
                [InlineKeyboardButton("🎯 选择性模式", callback_data="set_download_mode_selective")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取下载模式信息失败: {e}")
            self.logger.error(f"处理download_mode命令失败: {e}")

    async def _handle_list_tags_callback(self, query):
        """处理查看所有标签回调"""
        try:
            tags = await self.tag_manager.list_tags(limit=20)

            if not tags:
                await query.edit_message_text("暂无标签")
                return

            text = "🏷️ **所有标签** (前20个):\n\n"
            for tag in tags:
                text += f"• **{tag['name']}** ({tag['usage_count']} 次使用)\n"
                if tag['description']:
                    text += f"  _{tag['description']}_\n"
                text += "\n"

            await query.edit_message_text(text, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"获取标签列表失败: {e}")

    async def _handle_manual_classify_callback(self, query):
        """处理手动分类回调"""
        try:
            text = """
🤖 **手动分类功能**

可用命令:
• `/classify_message <消息ID>` - 分类单条消息
• `/classify_batch <消息ID1> <消息ID2> ...` - 批量分类
• `/reclassify_all` - 重新分类所有消息

💡 提示: 消息ID可以通过 `/search` 命令获取
            """

            await query.edit_message_text(text, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"处理手动分类失败: {e}")

    async def _handle_classification_rules_callback(self, query):
        """处理分类规则回调"""
        try:
            rules = await self.auto_classifier.rule_engine.get_rules(active_only=True)

            if not rules:
                text = "📋 **分类规则**\n\n暂无活跃的分类规则"
            else:
                text = f"📋 **分类规则** ({len(rules)} 条):\n\n"
                for rule in rules[:10]:  # 只显示前10条
                    text += f"• **{rule.name}**\n"
                    text += f"  类型: {rule.rule_type}\n"
                    text += f"  目标: {rule.target_field}\n"
                    text += f"  标签: {rule.tag.name}\n"
                    text += f"  匹配: {rule.match_count} 次\n\n"

            text += "\n💡 使用 `/add_rule` 命令添加新规则"

            await query.edit_message_text(text, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"获取分类规则失败: {e}")

    async def _handle_classification_details_callback(self, query):
        """处理分类详情回调"""
        try:
            stats = await self.auto_classifier.get_classification_stats()

            text = f"""
📈 **详细分类统计**

📊 **消息统计**:
• 总消息数: {stats['total_messages']}
• 已分类: {stats['classified_messages']}
• 未分类: {stats['total_messages'] - stats['classified_messages']}

🤖 **分类方式**:
• 自动分类: {stats['auto_classified']}
• 手动分类: {stats['manual_classified']}

⚡ **运行时统计**:
• 已处理: {stats['runtime_stats']['processed']}
• 成功分类: {stats['runtime_stats']['classified']}
• 处理错误: {stats['runtime_stats']['errors']}

🔄 **分类器状态**: {'🟢 运行中' if stats['is_running'] else '🔴 已停止'}
            """

            await query.edit_message_text(text, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"获取详细统计失败: {e}")

    async def _handle_manual_dedup_callback(self, query):
        """处理手动去重回调"""
        try:
            text = """
🔍 **手动去重功能**

可用命令:
• `/dedup_message <消息ID>` - 去重单条消息
• `/dedup_batch [类型] [数量]` - 批量去重
  - 类型: image, video 或留空表示全部
  - 数量: 处理数量，默认100
• `/dedup_report` - 查看重复文件报告

💡 示例:
• `/dedup_batch image 50` - 去重50个图片
• `/dedup_batch video` - 去重所有视频
• `/dedup_batch 200` - 去重200个文件
            """

            await query.edit_message_text(text, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"处理手动去重失败: {e}")

    async def _handle_duplicate_report_callback(self, query):
        """处理重复文件报告回调"""
        try:
            report = await self.dedup_manager.get_duplicate_files_report(limit=50)

            if not report["success"]:
                await query.edit_message_text(f"获取报告失败: {report['error']}")
                return

            text = f"""
📋 **重复文件报告**

📊 **统计信息**:
• 重复文件数: {report['total_duplicates']}
• 重复组数: {report['duplicate_groups']}
• 节省空间: {report['space_saved_mb']:.1f} MB

🗂️ **重复组示例** (前5组):
"""

            count = 0
            for original_id, duplicates in report['duplicate_groups_detail'].items():
                if count >= 5:
                    break

                text += f"\n**组 {count + 1}** (原始消息: {original_id}):\n"
                for dup in duplicates[:3]:  # 只显示前3个重复文件
                    text += f"• {dup['file_name']} ({dup['media_type']})\n"

                if len(duplicates) > 3:
                    text += f"• ... 还有 {len(duplicates) - 3} 个重复文件\n"

                count += 1

            if report['duplicate_groups'] > 5:
                text += f"\n... 还有 {report['duplicate_groups'] - 5} 个重复组"

            await query.edit_message_text(text, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"获取重复文件报告失败: {e}")

    async def _handle_dedup_details_callback(self, query):
        """处理去重详情回调"""
        try:
            stats = await self.dedup_manager.get_deduplication_stats()

            text = f"""
📈 **详细去重统计**

📊 **消息统计**:
• 总消息数: {stats['total_messages']}
• 重复消息: {stats['duplicate_messages']}
• 唯一消息: {stats['unique_messages']}
• 已计算哈希: {stats['hashed_messages']}

🔍 **去重效果**:
• 去重率: {stats['deduplication_rate']:.1%}
• 去重记录: {stats['duplicate_records']}

⚡ **运行时统计**:
• 已处理: {stats['runtime_stats']['processed']}
• 发现重复: {stats['runtime_stats']['duplicates_found']}
• 处理错误: {stats['runtime_stats']['errors']}

🔧 **配置信息**:
• 哈希去重: {'启用' if stats['settings']['hash_dedup_enabled'] else '禁用'}
• 特征去重: {'启用' if stats['settings']['feature_dedup_enabled'] else '禁用'}
• 相似度阈值: {stats['settings']['duplicate_threshold']:.2f}

🔄 **运行状态**: {'🟢 运行中' if stats['is_running'] else '🔴 已停止'}
            """

            if 'runtime_seconds' in stats:
                hours = int(stats['runtime_seconds'] // 3600)
                minutes = int((stats['runtime_seconds'] % 3600) // 60)
                text += f"\n⏱️ **运行时间**: {hours}小时 {minutes}分钟"

            await query.edit_message_text(text, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"获取去重详情失败: {e}")

    async def _handle_storage_report_callback(self, query):
        """处理存储报告回调"""
        try:
            report = await self.storage_monitor.get_comprehensive_report()

            if "error" in report:
                await query.edit_message_text(f"获取存储报告失败: {report['error']}")
                return

            disk = report["disk_usage"]
            storage = report["storage_usage"]

            text = f"""
📊 **详细存储报告**

🖥️ **磁盘使用情况**:
• 总容量: {disk['total'] / (1024**3):.1f} GB
• 已使用: {disk['used'] / (1024**3):.1f} GB
• 剩余: {disk['free'] / (1024**3):.1f} GB
• 使用率: {disk['usage_ratio']:.1%}

📁 **项目文件统计**:
• 文件总数: {storage['total_files']}
• 总大小: {storage['total_size_gb']:.2f} GB

📋 **按扩展名统计** (前5个):
"""

            # 按大小排序显示前5个扩展名
            extensions = sorted(
                storage.get("by_extension", {}).items(),
                key=lambda x: x[1]["size"],
                reverse=True
            )

            for ext, info in extensions[:5]:
                ext_name = ext if ext else "无扩展名"
                text += f"• {ext_name}: {info['count']} 个文件 ({info['size_mb']:.1f} MB)\n"

            # 一致性检查
            consistency = report["consistency_check"]
            text += f"\n🔍 **数据一致性**: "
            if consistency["is_consistent"]:
                text += "✅ 正常"
            else:
                text += f"⚠️ 差异 {consistency['size_difference_mb']:.1f} MB"

            await query.edit_message_text(text, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"获取存储报告失败: {e}")

    async def _handle_storage_cleanup_callback(self, query):
        """处理存储清理回调"""
        try:
            text = """
🧹 **存储清理选项**

可用清理命令:
• `/cleanup_temp` - 清理临时文件
• `/cleanup_old <天数>` - 清理指定天数前的文件
• `/cleanup_duplicates` - 清理重复文件
• `/cleanup_failed` - 清理失败的下载

⚠️ **注意**: 清理操作不可逆，请谨慎使用

💡 建议定期清理临时文件和重复文件以节省空间
            """

            await query.edit_message_text(text, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"处理存储清理失败: {e}")

    async def _handle_storage_monitor_callback(self, query):
        """处理存储监控回调"""
        try:
            text = f"""
📈 **存储监控状态**

🔄 **监控器状态**: {'🟢 运行中' if self.storage_monitor.is_monitoring else '🔴 已停止'}

⏰ **最后检查**: {self.storage_monitor.last_check_time.strftime('%Y-%m-%d %H:%M:%S') if self.storage_monitor.last_check_time else '从未检查'}

⚙️ **监控配置**:
• 空间警告阈值: {self.storage_monitor.space_warning_threshold:.0%}
• 空间严重阈值: {self.storage_monitor.space_critical_threshold:.0%}
• 检查间隔: 30 分钟

💡 监控器会自动检查磁盘空间使用情况，并在空间不足时发出警告
            """

            await query.edit_message_text(text, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"获取监控状态失败: {e}")

    async def _handle_pause_downloads_callback(self, query):
        """处理暂停下载回调"""
        try:
            await self.download_manager.pause_downloads()
            await query.edit_message_text("⏸️ 下载已暂停")

        except Exception as e:
            await query.edit_message_text(f"暂停下载失败: {e}")

    async def _handle_resume_downloads_callback(self, query):
        """处理恢复下载回调"""
        try:
            await self.download_manager.resume_downloads()
            await query.edit_message_text("▶️ 下载已恢复")

        except Exception as e:
            await query.edit_message_text(f"恢复下载失败: {e}")

    async def _handle_retry_downloads_callback(self, query):
        """处理重试下载回调"""
        try:
            retry_count = await self.download_manager.retry_failed_downloads()
            await query.edit_message_text(f"🔄 已重试 {retry_count} 个失败的下载任务")

        except Exception as e:
            await query.edit_message_text(f"重试下载失败: {e}")

    async def _handle_set_download_mode_callback(self, query, mode: str):
        """处理设置下载模式回调"""
        try:
            # 验证模式
            valid_modes = ["auto", "manual", "selective"]
            if mode not in valid_modes:
                await query.edit_message_text(f"❌ 无效的下载模式: {mode}")
                return

            # 更新配置
            old_mode = self.settings.auto_download_mode
            self.settings.auto_download_mode = mode

            # 模式描述
            mode_descriptions = {
                "auto": "🔄 自动下载所有文件",
                "manual": "👤 手动下载模式",
                "selective": "🎯 选择性自动下载"
            }

            text = f"""
✅ **下载模式已更新**

📝 **变更**: {old_mode} → {mode}
🔧 **新模式**: {mode_descriptions.get(mode, mode)}

💡 新设置将在下次采集时生效
            """

            await query.edit_message_text(text, parse_mode='Markdown')

            self.logger.info(f"下载模式已从 {old_mode} 更改为 {mode}")

        except Exception as e:
            await query.edit_message_text(f"设置下载模式失败: {e}")

    async def _handle_confirm_remove_channel_callback(self, query, channel_id: int):
        """处理确认移除频道回调"""
        try:
            async with self.db_manager.get_async_session() as session:
                from sqlalchemy import select, delete

                # 获取频道信息
                channel_result = await session.execute(
                    select(Channel).where(Channel.id == channel_id)
                )
                channel = channel_result.scalar_one_or_none()

                if not channel:
                    await query.edit_message_text("❌ 频道不存在")
                    return

                channel_title = channel.channel_title

                # 删除相关消息
                message_result = await session.execute(
                    select(func.count(Message.id)).where(Message.channel_id == channel_id)
                )
                message_count = message_result.scalar()

                await session.execute(
                    delete(Message).where(Message.channel_id == channel_id)
                )

                # 删除频道
                await session.execute(
                    delete(Channel).where(Channel.id == channel_id)
                )

                await session.commit()

                await query.edit_message_text(
                    f"✅ **频道移除成功**\n\n"
                    f"📺 频道: {channel_title}\n"
                    f"🗑️ 已删除 {message_count} 条相关消息记录"
                )

                self.logger.info(f"移除频道: {channel_title} (ID: {channel_id})")

        except Exception as e:
            await query.edit_message_text(f"移除频道失败: {e}")

    async def _handle_add_channel_prompt_callback(self, query):
        """处理添加频道提示回调"""
        text = """
➕ **添加新频道**

请使用以下命令添加频道:
`/add_channel <频道链接或用户名>`

**支持格式**:
• 完整链接: `/add_channel https://t.me/example_channel`
• 用户名: `/add_channel @example_channel`
• 频道ID: `/add_channel -1001234567890`

💡 **提示**: 确保机器人有权限访问该频道
        """

        await query.edit_message_text(text, parse_mode='Markdown')

    async def _handle_remove_channel_prompt_callback(self, query):
        """处理移除频道提示回调"""
        text = """
🗑️ **移除频道**

请使用以下命令移除频道:
`/remove_channel <频道标识>`

**支持格式**:
• 用户名: `/remove_channel @example_channel`
• 频道ID: `/remove_channel -1001234567890`
• 频道标题: `/remove_channel 示例频道`

⚠️ **警告**: 移除频道将删除所有相关数据！
        """

        await query.edit_message_text(text, parse_mode='Markdown')

    async def _handle_refresh_channels_callback(self, query):
        """处理刷新频道回调"""
        try:
            # 重新获取频道列表
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Channel).order_by(Channel.created_at.desc())
                )
                channels = result.scalars().all()

            if not channels:
                await query.edit_message_text("📭 暂无已添加的频道")
                return

            text = "📋 **已添加的频道列表** (已刷新)\n\n"

            for i, channel in enumerate(channels, 1):
                status_emoji = {
                    ChannelStatus.ACTIVE: "🟢",
                    ChannelStatus.INACTIVE: "🟡",
                    ChannelStatus.ERROR: "🔴"
                }.get(channel.status, "⚪")

                text += f"{i}. {status_emoji} **{channel.channel_title}**\n"
                text += f"   • ID: `{channel.channel_id}`\n"
                text += f"   • 状态: {channel.status.value}\n"
                if channel.last_check_time:
                    text += f"   • 最后检查: {channel.last_check_time.strftime('%Y-%m-%d %H:%M')}\n"
                text += "\n"

            await query.edit_message_text(text, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"刷新频道列表失败: {e}")

    async def _handle_help_category_callback(self, query, category: str):
        """处理帮助分类回调"""
        try:
            commands = self.command_helper.get_category_commands(category)

            if not commands:
                await query.edit_message_text(f"❌ 分类 '{category}' 下没有命令")
                return

            text = f"📖 **{category} 命令**\n\n"

            for cmd_name in commands:
                cmd_info = self.command_helper.commands[cmd_name]
                text += f"• `/{cmd_name}` - {cmd_info['description']}\n"

            text += f"\n💡 使用 `/help <命令名>` 获取详细帮助"

            # 返回按钮
            keyboard = [[InlineKeyboardButton("🔙 返回帮助", callback_data="back_to_help")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"获取分类帮助失败: {e}")

    async def _handle_help_search_callback(self, query):
        """处理帮助搜索回调"""
        text = """
🔍 **命令搜索**

使用以下方式搜索命令:
• `/help <命令名>` - 获取特定命令帮助
• 在下方按分类浏览命令

**搜索示例**:
• `/help add_channel` - 添加频道命令帮助
• `/help search` - 搜索功能帮助
• `/help storage` - 存储管理帮助

💡 **提示**: 命令名不需要包含 `/` 前缀
        """

        # 返回按钮
        keyboard = [[InlineKeyboardButton("🔙 返回帮助", callback_data="back_to_help")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    async def _handle_help_category_callback(self, query, category: str):
        """处理帮助分类回调"""
        try:
            commands = self.command_helper.get_category_commands(category)

            if not commands:
                await query.edit_message_text(f"❌ 分类 '{category}' 下没有命令")
                return

            text = f"📖 **{category} 命令**\n\n"

            for cmd_name in commands:
                cmd_info = self.command_helper.commands[cmd_name]
                text += f"• `/{cmd_name}` - {cmd_info['description']}\n"

            text += f"\n💡 使用 `/help <命令名>` 获取详细帮助"

            # 返回按钮
            keyboard = [[InlineKeyboardButton("🔙 返回帮助", callback_data="back_to_help")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"获取分类帮助失败: {e}")

    async def _handle_help_search_callback(self, query):
        """处理帮助搜索回调"""
        text = """
🔍 **命令搜索**

使用以下方式搜索命令:
• `/help <命令名>` - 获取特定命令帮助
• 在下方按分类浏览命令

**搜索示例**:
• `/help add_channel` - 添加频道命令帮助
• `/help search` - 搜索功能帮助
• `/help storage` - 存储管理帮助

💡 **提示**: 命令名不需要包含 `/` 前缀
        """

        # 返回按钮
        keyboard = [[InlineKeyboardButton("🔙 返回帮助", callback_data="back_to_help")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    async def _handle_back_to_help_callback(self, query):
        """处理返回帮助回调"""
        try:
            # 重新显示主帮助页面
            help_text = self.command_helper.get_quick_help()

            # 创建分类按钮
            categories = self.command_helper.get_all_categories()
            keyboard = []

            # 每行两个按钮
            for i in range(0, len(categories), 2):
                row = []
                for j in range(2):
                    if i + j < len(categories):
                        category = categories[i + j]
                        row.append(InlineKeyboardButton(
                            category,
                            callback_data=f"help_category_{category}"
                        ))
                keyboard.append(row)

            # 添加搜索按钮
            keyboard.append([InlineKeyboardButton("🔍 搜索命令", callback_data="help_search")])

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            await query.edit_message_text(f"返回帮助页面失败: {e}")

    async def queue_downloads_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/queue_downloads命令"""
        try:
            # 获取参数
            limit = 50  # 默认限制
            if context.args:
                try:
                    limit = int(context.args[0])
                    limit = max(1, min(limit, 200))  # 限制在1-200之间
                except ValueError:
                    await update.message.reply_text("❌ 请提供有效的数字限制")
                    return

            # 将待下载消息加入队列
            queued_count = await self.download_manager.queue_pending_downloads(limit)

            text = f"""
📥 **下载队列更新**

✅ 已将 {queued_count} 个待下载文件加入队列

🔄 **当前状态**:
• 队列大小: {self.download_manager.download_queue.qsize()}
• 活跃下载: {len(self.download_manager.active_downloads)}
• 下载器状态: {'🟢 运行中' if self.download_manager.is_downloading else '🔴 已停止'}

💡 使用 `/downloads` 查看详细下载状态
            """

            await update.message.reply_text(text, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"队列下载失败: {e}")
            self.logger.error(f"处理queue_downloads命令失败: {e}")

    async def cleanup_temp_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/cleanup_temp命令"""
        try:
            # 获取清理时间参数
            max_age_hours = 24  # 默认24小时
            if context.args:
                try:
                    max_age_hours = int(context.args[0])
                    max_age_hours = max(1, min(max_age_hours, 168))  # 限制在1-168小时(7天)
                except ValueError:
                    await update.message.reply_text("❌ 请提供有效的小时数")
                    return

            # 执行清理
            result = await self.file_manager.cleanup_temp_files(max_age_hours)

            if "error" in result:
                await update.message.reply_text(f"❌ 清理失败: {result['error']}")
                return

            text = f"""
🧹 **临时文件清理完成**

📊 **清理结果**:
• 删除文件数: {result['deleted_files']}
• 释放空间: {result['freed_space_mb']:.1f} MB
• 清理条件: 超过 {max_age_hours} 小时的文件

✅ 临时文件清理成功完成
            """

            await update.message.reply_text(text, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"清理临时文件失败: {e}")
            self.logger.error(f"处理cleanup_temp命令失败: {e}")

    async def system_info_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/system_info命令"""
        try:
            import platform
            import sys
            from datetime import datetime

            # 获取系统信息
            system_info = {
                "platform": platform.platform(),
                "python_version": sys.version.split()[0],
                "architecture": platform.architecture()[0],
                "processor": platform.processor() or "Unknown",
                "hostname": platform.node()
            }

            # 获取运行时信息
            uptime = datetime.utcnow() - (self.download_manager.download_stats.get("start_time") or datetime.utcnow())

            text = f"""
🖥️ **系统信息**

💻 **运行环境**:
• 操作系统: {system_info['platform']}
• Python版本: {system_info['python_version']}
• 架构: {system_info['architecture']}
• 主机名: {system_info['hostname']}

⏱️ **运行状态**:
• 机器人状态: {'🟢 运行中' if self.is_running else '🔴 已停止'}
• 运行时间: {str(uptime).split('.')[0]}

🔧 **服务状态**:
• 数据库: {'🟢 正常' if await self.db_manager.health_check() else '🔴 异常'}
• 下载器: {'🟢 运行中' if self.download_manager.is_downloading else '🔴 已停止'}
• 存储监控: {'🟢 运行中' if self.storage_monitor.is_monitoring else '🔴 已停止'}
• 自动分类: {'🟢 启用' if self.settings.auto_classification else '🔴 禁用'}

📊 **内存使用**: {self._get_memory_usage()}
            """

            await update.message.reply_text(text, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取系统信息失败: {e}")
            self.logger.error(f"处理system_info命令失败: {e}")

    async def tag_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/tag_stats命令"""
        try:
            if context.args:
                # 获取指定标签的详细统计
                tag_name = " ".join(context.args)
                stats = await self.tag_statistics.get_tag_media_stats(tag_name=tag_name)

                if "error" in stats:
                    await update.message.reply_text(f"❌ {stats['error']}")
                    return

                tag_info = stats["tag_info"]
                media_stats = stats["media_stats"]

                text = f"""
🏷️ **标签详细统计**: {tag_info['name']}

📝 **标签信息**:
• 描述: {tag_info['description'] or '无描述'}
• 颜色: {tag_info['color'] or '默认'}
• 总文件数: {stats['total_files']}
• 总大小: {stats['total_size_gb']:.2f} GB

📊 **媒体类型分布**:
🎬 视频: {media_stats['video']['count']} 个 ({media_stats['video']['size_mb']:.1f} MB)
📸 图片: {media_stats['image']['count']} 个 ({media_stats['image']['size_mb']:.1f} MB)
🎵 音频: {media_stats['audio']['count']} 个 ({media_stats['audio']['size_mb']:.1f} MB)
📄 文档: {media_stats['document']['count']} 个 ({media_stats['document']['size_mb']:.1f} MB)

📈 **平均文件大小**:
• 视频: {media_stats['video']['avg_size_mb']:.1f} MB
• 图片: {media_stats['image']['avg_size_mb']:.1f} MB
• 音频: {media_stats['audio']['avg_size_mb']:.1f} MB
• 文档: {media_stats['document']['avg_size_mb']:.1f} MB
                """

                # 创建操作按钮
                keyboard = [
                    [InlineKeyboardButton("📈 时间线统计", callback_data=f"tag_timeline_{tag_info['id']}")],
                    [InlineKeyboardButton("📺 频道分布", callback_data=f"tag_channels_{tag_info['id']}")],
                    [InlineKeyboardButton("🔍 查看文件", callback_data=f"tag_files_{tag_info['id']}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

            else:
                # 显示所有标签的摘要统计
                summary = await self.tag_statistics.get_all_tags_media_summary(limit=20)

                if "error" in summary:
                    await update.message.reply_text(f"❌ {summary['error']}")
                    return

                text = f"""
🏷️ **标签媒体统计摘要**

📊 **总体统计**:
• 活跃标签数: {summary['total_tags']}
• 总视频数: {summary['overall_stats']['total_videos']}
• 总图片数: {summary['overall_stats']['total_images']}
• 总音频数: {summary['overall_stats']['total_audio']}
• 总文档数: {summary['overall_stats']['total_documents']}

🔝 **热门标签** (前10个):
"""

                for i, tag_summary in enumerate(summary['tags_summary'][:10], 1):
                    text += f"{i}. **{tag_summary['tag_name']}**\n"
                    text += f"   🎬 {tag_summary['videos']} 📸 {tag_summary['images']} "
                    text += f"🎵 {tag_summary['audio']} 📄 {tag_summary['documents']}\n"
                    text += f"   💾 {tag_summary['total_size_mb']:.1f} MB\n\n"

                text += "💡 使用 `/tag_stats <标签名>` 查看详细统计"

                await update.message.reply_text(text, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取标签统计失败: {e}")
            self.logger.error(f"处理tag_stats命令失败: {e}")

    async def media_by_tag_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/media_by_tag命令"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "🎯 **按媒体类型查看标签分布**\n\n"
                    "请指定媒体类型:\n"
                    "• `/media_by_tag video` - 查看视频标签分布\n"
                    "• `/media_by_tag image` - 查看图片标签分布\n"
                    "• `/media_by_tag audio` - 查看音频标签分布\n"
                    "• `/media_by_tag document` - 查看文档标签分布",
                    parse_mode='Markdown'
                )
                return

            media_type_str = context.args[0].lower()

            # 转换媒体类型
            media_type_map = {
                "video": MediaType.VIDEO,
                "image": MediaType.IMAGE,
                "audio": MediaType.AUDIO,
                "document": MediaType.DOCUMENT
            }

            media_type = media_type_map.get(media_type_str)
            if not media_type:
                await update.message.reply_text(
                    f"❌ 不支持的媒体类型: {media_type_str}\n"
                    f"支持的类型: {', '.join(media_type_map.keys())}"
                )
                return

            # 获取媒体类型的标签分布
            distribution = await self.tag_statistics.get_media_type_by_tags(media_type, limit=15)

            if "error" in distribution:
                await update.message.reply_text(f"❌ {distribution['error']}")
                return

            media_emoji = {
                "video": "🎬",
                "image": "📸",
                "audio": "🎵",
                "document": "📄"
            }

            emoji = media_emoji.get(media_type_str, "📁")

            text = f"""
{emoji} **{media_type_str.title()} 标签分布统计**

📊 **总计**: {distribution['total_count']} 个{media_type_str}

🏷️ **标签分布** (前15个):
"""

            for i, tag_info in enumerate(distribution['tag_distribution'], 1):
                text += f"{i}. **{tag_info['tag_name']}**: {tag_info['count']} 个 ({tag_info['percentage']:.1f}%)\n"

            text += f"\n💡 使用 `/tag_stats <标签名>` 查看标签详细统计"

            await update.message.reply_text(text, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"获取媒体标签分布失败: {e}")
            self.logger.error(f"处理media_by_tag命令失败: {e}")
