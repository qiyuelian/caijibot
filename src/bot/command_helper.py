# -*- coding: utf-8 -*-
"""
命令帮助管理器
提供命令的详细帮助信息和使用示例
"""

from typing import Dict, List, Any
from ..utils.logger import LoggerMixin


class CommandHelper(LoggerMixin):
    """命令帮助管理器"""
    
    def __init__(self):
        """初始化命令帮助管理器"""
        self.commands = self._initialize_commands()
        self.logger.info("命令帮助管理器初始化完成")
    
    def _initialize_commands(self) -> Dict[str, Dict[str, Any]]:
        """初始化命令信息"""
        return {
            # 基本命令
            "start": {
                "description": "启动机器人并显示欢迎信息",
                "usage": "/start",
                "examples": ["/start"],
                "category": "基本命令"
            },
            "help": {
                "description": "显示帮助信息",
                "usage": "/help [命令名]",
                "examples": ["/help", "/help add_channel"],
                "category": "基本命令"
            },
            "status": {
                "description": "查看系统运行状态",
                "usage": "/status",
                "examples": ["/status"],
                "category": "基本命令"
            },
            
            # 频道管理
            "add_channel": {
                "description": "添加要监控的频道",
                "usage": "/add_channel <频道链接或用户名>",
                "examples": [
                    "/add_channel https://t.me/example_channel",
                    "/add_channel @example_channel",
                    "/add_channel -1001234567890"
                ],
                "category": "频道管理"
            },
            "remove_channel": {
                "description": "移除监控的频道",
                "usage": "/remove_channel <频道标识>",
                "examples": [
                    "/remove_channel @example_channel",
                    "/remove_channel -1001234567890"
                ],
                "category": "频道管理"
            },
            "list_channels": {
                "description": "列出所有已添加的频道",
                "usage": "/list_channels",
                "examples": ["/list_channels"],
                "category": "频道管理"
            },
            
            # 标签和分类
            "tags": {
                "description": "管理标签系统",
                "usage": "/tags [操作] [参数]",
                "examples": [
                    "/tags",
                    "/tags add 搞笑视频",
                    "/tags remove 无用标签"
                ],
                "category": "标签分类"
            },
            "classify": {
                "description": "查看和管理自动分类",
                "usage": "/classify [操作]",
                "examples": ["/classify", "/classify stats"],
                "category": "标签分类"
            },
            
            # 去重检测
            "dedup": {
                "description": "查看去重统计和手动去重",
                "usage": "/dedup [操作]",
                "examples": ["/dedup", "/dedup scan"],
                "category": "去重检测"
            },
            
            # 存储管理
            "storage": {
                "description": "查看存储使用情况和管理",
                "usage": "/storage",
                "examples": ["/storage"],
                "category": "存储管理"
            },
            "downloads": {
                "description": "查看下载队列和状态",
                "usage": "/downloads",
                "examples": ["/downloads"],
                "category": "存储管理"
            },
            "download_mode": {
                "description": "设置下载模式",
                "usage": "/download_mode [模式]",
                "examples": [
                    "/download_mode",
                    "/download_mode auto",
                    "/download_mode selective"
                ],
                "category": "存储管理"
            },
            
            # 统计和搜索
            "stats": {
                "description": "查看系统统计信息",
                "usage": "/stats",
                "examples": ["/stats"],
                "category": "统计搜索"
            },
            "search": {
                "description": "搜索文件和消息",
                "usage": "/search <关键词>",
                "examples": [
                    "/search 猫咪视频",
                    "/search .mp4",
                    "/search #搞笑"
                ],
                "category": "统计搜索"
            },
            "tag_stats": {
                "description": "查看标签的媒体统计信息",
                "usage": "/tag_stats [标签名]",
                "examples": [
                    "/tag_stats",
                    "/tag_stats 搞笑视频",
                    "/tag_stats 猫咪"
                ],
                "category": "统计搜索"
            },
            "media_by_tag": {
                "description": "查看指定媒体类型的标签分布",
                "usage": "/media_by_tag <媒体类型>",
                "examples": [
                    "/media_by_tag video",
                    "/media_by_tag image",
                    "/media_by_tag audio"
                ],
                "category": "统计搜索"
            },
            
            # 设置管理
            "settings": {
                "description": "查看和修改系统设置",
                "usage": "/settings [类别]",
                "examples": ["/settings", "/settings storage"],
                "category": "设置管理"
            }
        }
    
    def get_command_help(self, command_name: str) -> str:
        """
        获取特定命令的帮助信息
        
        Args:
            command_name: 命令名称
        
        Returns:
            str: 帮助信息
        """
        command = self.commands.get(command_name)
        if not command:
            return f"❌ 未找到命令: {command_name}"
        
        help_text = f"""
📖 **命令帮助**: /{command_name}

📝 **描述**: {command['description']}

💡 **用法**: `{command['usage']}`

📋 **示例**:
"""
        
        for example in command['examples']:
            help_text += f"• `{example}`\n"
        
        help_text += f"\n🏷️ **分类**: {command['category']}"
        
        return help_text
    
    def get_category_commands(self, category: str) -> List[str]:
        """
        获取指定分类的所有命令
        
        Args:
            category: 分类名称
        
        Returns:
            List[str]: 命令列表
        """
        return [
            cmd_name for cmd_name, cmd_info in self.commands.items()
            if cmd_info['category'] == category
        ]
    
    def get_all_categories(self) -> List[str]:
        """获取所有命令分类"""
        categories = set()
        for cmd_info in self.commands.values():
            categories.add(cmd_info['category'])
        return sorted(list(categories))
    
    def get_commands_by_category(self) -> Dict[str, List[str]]:
        """按分类获取所有命令"""
        result = {}
        for category in self.get_all_categories():
            result[category] = self.get_category_commands(category)
        return result
    
    def search_commands(self, keyword: str) -> List[str]:
        """
        搜索命令
        
        Args:
            keyword: 搜索关键词
        
        Returns:
            List[str]: 匹配的命令列表
        """
        keyword = keyword.lower()
        matching_commands = []
        
        for cmd_name, cmd_info in self.commands.items():
            # 搜索命令名、描述和分类
            if (keyword in cmd_name.lower() or 
                keyword in cmd_info['description'].lower() or
                keyword in cmd_info['category'].lower()):
                matching_commands.append(cmd_name)
        
        return matching_commands
    
    def get_quick_help(self) -> str:
        """获取快速帮助信息"""
        categories = self.get_commands_by_category()
        
        help_text = "📖 **快速命令参考**\n\n"
        
        category_emojis = {
            "基本命令": "🤖",
            "频道管理": "📺", 
            "标签分类": "🏷️",
            "去重检测": "🔄",
            "存储管理": "💾",
            "统计搜索": "📊",
            "设置管理": "⚙️"
        }
        
        for category, commands in categories.items():
            emoji = category_emojis.get(category, "📋")
            help_text += f"{emoji} **{category}**:\n"
            
            for cmd in commands:
                cmd_info = self.commands[cmd]
                help_text += f"• `/{cmd}` - {cmd_info['description']}\n"
            
            help_text += "\n"
        
        help_text += "💡 使用 `/help <命令名>` 获取详细帮助"
        
        return help_text
    
    def validate_command_args(self, command_name: str, args: List[str]) -> Dict[str, Any]:
        """
        验证命令参数
        
        Args:
            command_name: 命令名称
            args: 参数列表
        
        Returns:
            Dict: 验证结果
        """
        command = self.commands.get(command_name)
        if not command:
            return {"valid": False, "error": f"未知命令: {command_name}"}
        
        # 这里可以添加更复杂的参数验证逻辑
        # 目前只做基本检查
        
        required_args = {
            "add_channel": 1,
            "remove_channel": 1,
            "search": 1
        }
        
        min_args = required_args.get(command_name, 0)
        
        if len(args) < min_args:
            return {
                "valid": False,
                "error": f"命令 /{command_name} 需要至少 {min_args} 个参数",
                "usage": command['usage']
            }
        
        return {"valid": True}
    
    def get_command_suggestions(self, partial_command: str) -> List[str]:
        """
        获取命令建议（用于自动补全）
        
        Args:
            partial_command: 部分命令名
        
        Returns:
            List[str]: 建议的命令列表
        """
        partial = partial_command.lower()
        suggestions = []
        
        for cmd_name in self.commands.keys():
            if cmd_name.startswith(partial):
                suggestions.append(cmd_name)
        
        return sorted(suggestions)
