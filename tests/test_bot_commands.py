# -*- coding: utf-8 -*-
"""
机器人命令测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.bot.telegram_bot import TelegramBot
from src.bot.command_helper import CommandHelper
from src.bot.user_manager import UserManager, UserRole


class TestCommandHelper:
    """命令帮助管理器测试"""
    
    def test_command_helper_initialization(self):
        """测试命令帮助管理器初始化"""
        helper = CommandHelper()
        
        assert helper is not None
        assert len(helper.commands) > 0
        assert "start" in helper.commands
        assert "help" in helper.commands
    
    def test_get_command_help(self):
        """测试获取命令帮助"""
        helper = CommandHelper()
        
        # 测试存在的命令
        help_text = helper.get_command_help("start")
        assert "start" in help_text
        assert "描述" in help_text
        assert "用法" in help_text
        
        # 测试不存在的命令
        help_text = helper.get_command_help("nonexistent")
        assert "未找到命令" in help_text
    
    def test_get_category_commands(self):
        """测试获取分类命令"""
        helper = CommandHelper()
        
        basic_commands = helper.get_category_commands("基本命令")
        assert isinstance(basic_commands, list)
        assert "start" in basic_commands
        assert "help" in basic_commands
    
    def test_search_commands(self):
        """测试搜索命令"""
        helper = CommandHelper()
        
        # 搜索频道相关命令
        channel_commands = helper.search_commands("频道")
        assert isinstance(channel_commands, list)
        assert any("channel" in cmd for cmd in channel_commands)
        
        # 搜索存储相关命令
        storage_commands = helper.search_commands("存储")
        assert isinstance(storage_commands, list)


class TestUserManager:
    """用户管理器测试"""
    
    @pytest.mark.asyncio
    async def test_user_manager_initialization(self, test_db_manager, test_settings):
        """测试用户管理器初始化"""
        user_manager = UserManager(test_db_manager, test_settings)
        
        assert user_manager is not None
        assert user_manager.role_permissions is not None
        assert UserRole.ADMIN in user_manager.role_permissions
    
    @pytest.mark.asyncio
    async def test_user_role_assignment(self, test_db_manager, test_settings):
        """测试用户角色分配"""
        user_manager = UserManager(test_db_manager, test_settings)
        
        # 测试默认角色
        role = await user_manager.get_user_role(123456789)
        assert role in [UserRole.ADMIN, UserRole.OPERATOR, UserRole.VIEWER]
        
        # 测试添加管理员
        success = await user_manager.add_admin_user(999999999)
        assert success is True
        
        admin_role = await user_manager.get_user_role(999999999)
        assert admin_role == UserRole.ADMIN
    
    @pytest.mark.asyncio
    async def test_permission_checking(self, test_db_manager, test_settings):
        """测试权限检查"""
        user_manager = UserManager(test_db_manager, test_settings)
        
        # 添加测试管理员
        await user_manager.add_admin_user(111111111)
        
        # 测试管理员权限
        can_manage = await user_manager.check_user_permission(111111111, "can_manage_settings")
        assert can_manage is True
        
        # 测试普通用户权限
        can_view = await user_manager.check_user_permission(222222222, "can_view_stats")
        # 根据默认角色，可能为True或False
        assert isinstance(can_view, bool)
    
    @pytest.mark.asyncio
    async def test_user_authorization(self, test_db_manager, test_settings):
        """测试用户授权"""
        user_manager = UserManager(test_db_manager, test_settings)
        
        # 测试正常用户授权
        is_authorized = await user_manager.is_user_authorized(123456789)
        assert is_authorized is True
        
        # 测试禁用用户
        await user_manager.ban_user(333333333)
        is_banned_authorized = await user_manager.is_user_authorized(333333333)
        assert is_banned_authorized is False


class TestTelegramBotCommands:
    """Telegram机器人命令测试"""
    
    @pytest.mark.asyncio
    async def test_bot_initialization(self, test_db_manager, test_settings):
        """测试机器人初始化"""
        bot = TelegramBot(test_db_manager, test_settings)
        
        assert bot is not None
        assert bot.db_manager == test_db_manager
        assert bot.settings == test_settings
        assert bot.command_helper is not None
    
    @pytest.mark.asyncio
    async def test_start_command(self, test_db_manager, test_settings):
        """测试start命令"""
        bot = TelegramBot(test_db_manager, test_settings)
        
        # 模拟更新和上下文
        update = MagicMock()
        context = MagicMock()
        update.message.reply_text = AsyncMock()
        
        # 执行start命令
        await bot.start_command(update, context)
        
        # 验证回复被调用
        update.message.reply_text.assert_called_once()
        
        # 检查回复内容
        call_args = update.message.reply_text.call_args
        reply_text = call_args[0][0]
        assert "欢迎" in reply_text or "Welcome" in reply_text
    
    @pytest.mark.asyncio
    async def test_help_command(self, test_db_manager, test_settings):
        """测试help命令"""
        bot = TelegramBot(test_db_manager, test_settings)
        
        # 模拟更新和上下文
        update = MagicMock()
        context = MagicMock()
        update.message.reply_text = AsyncMock()
        context.args = []
        
        # 执行help命令
        await bot.help_command(update, context)
        
        # 验证回复被调用
        update.message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_status_command(self, test_db_manager, test_settings):
        """测试status命令"""
        bot = TelegramBot(test_db_manager, test_settings)
        
        # 模拟更新和上下文
        update = MagicMock()
        context = MagicMock()
        update.message.reply_text = AsyncMock()
        
        # 执行status命令
        await bot.status_command(update, context)
        
        # 验证回复被调用
        update.message.reply_text.assert_called_once()
        
        # 检查回复内容
        call_args = update.message.reply_text.call_args
        reply_text = call_args[0][0]
        assert "状态" in reply_text or "Status" in reply_text
    
    @pytest.mark.asyncio
    async def test_stats_command(self, test_db_manager, test_settings, sample_messages):
        """测试stats命令"""
        bot = TelegramBot(test_db_manager, test_settings)
        
        # 模拟更新和上下文
        update = MagicMock()
        context = MagicMock()
        update.message.reply_text = AsyncMock()
        
        # 执行stats命令
        await bot.stats_command(update, context)
        
        # 验证回复被调用
        update.message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_tag_stats_command(self, test_db_manager, test_settings, sample_tags):
        """测试tag_stats命令"""
        bot = TelegramBot(test_db_manager, test_settings)
        
        # 模拟更新和上下文
        update = MagicMock()
        context = MagicMock()
        update.message.reply_text = AsyncMock()
        
        # 测试无参数的tag_stats命令
        context.args = []
        await bot.tag_stats_command(update, context)
        update.message.reply_text.assert_called()
        
        # 测试带参数的tag_stats命令
        context.args = [sample_tags[0].name]
        await bot.tag_stats_command(update, context)
        update.message.reply_text.assert_called()


class TestBotErrorHandling:
    """机器人错误处理测试"""
    
    @pytest.mark.asyncio
    async def test_command_error_handling(self, test_db_manager, test_settings):
        """测试命令错误处理"""
        bot = TelegramBot(test_db_manager, test_settings)
        
        # 模拟会导致错误的情况
        update = MagicMock()
        context = MagicMock()
        update.message.reply_text = AsyncMock()
        
        # 模拟数据库错误
        bot.db_manager = None
        
        # 执行命令，应该优雅处理错误
        await bot.stats_command(update, context)
        
        # 验证错误被处理
        update.message.reply_text.assert_called()
        call_args = update.message.reply_text.call_args
        reply_text = call_args[0][0]
        assert "失败" in reply_text or "错误" in reply_text
    
    @pytest.mark.asyncio
    async def test_invalid_command_parameters(self, test_db_manager, test_settings):
        """测试无效命令参数处理"""
        bot = TelegramBot(test_db_manager, test_settings)
        
        # 模拟更新和上下文
        update = MagicMock()
        context = MagicMock()
        update.message.reply_text = AsyncMock()
        
        # 测试无效的媒体类型参数
        context.args = ["invalid_media_type"]
        await bot.media_by_tag_command(update, context)
        
        # 验证错误处理
        update.message.reply_text.assert_called()
        call_args = update.message.reply_text.call_args
        reply_text = call_args[0][0]
        assert "不支持" in reply_text or "无效" in reply_text


class TestBotIntegration:
    """机器人集成测试"""
    
    @pytest.mark.asyncio
    async def test_bot_component_integration(self, test_db_manager, test_settings):
        """测试机器人组件集成"""
        bot = TelegramBot(test_db_manager, test_settings)
        
        # 验证所有组件都正确初始化
        assert bot.channel_manager is not None
        assert bot.auto_classifier is not None
        assert bot.dedup_manager is not None
        assert bot.file_manager is not None
        assert bot.download_manager is not None
        assert bot.storage_monitor is not None
        assert bot.tag_statistics is not None
        assert bot.command_helper is not None
    
    @pytest.mark.asyncio
    async def test_bot_startup_shutdown(self, test_db_manager, test_settings):
        """测试机器人启动和关闭"""
        bot = TelegramBot(test_db_manager, test_settings)
        
        # 测试启动（不实际连接Telegram）
        # 这里主要测试初始化逻辑
        assert bot.is_running is False
        
        # 测试关闭
        await bot.stop()
        assert bot.is_running is False
