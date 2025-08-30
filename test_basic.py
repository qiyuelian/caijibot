#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基础功能测试脚本
用于测试项目的基本功能是否正常工作
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).parent))

from src.config.settings import Settings
from src.database.database_manager import DatabaseManager
from src.utils.logger import setup_logger


async def test_configuration():
    """测试配置加载"""
    print("🔧 测试配置加载...")
    try:
        # 注意：这里会因为缺少必需的环境变量而失败，这是正常的
        settings = Settings()
        print("✅ 配置加载成功")
        return True
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        print("💡 提示: 请先创建 .env 文件并填入必要的配置")
        return False


async def test_logger():
    """测试日志系统"""
    print("\n📝 测试日志系统...")
    try:
        logger = setup_logger(
            log_level="INFO",
            log_file=Path("./logs/test.log"),
            enable_console=True,
            enable_rich=True
        )
        
        logger.info("这是一条测试日志消息")
        logger.warning("这是一条警告消息")
        logger.error("这是一条错误消息")
        
        print("✅ 日志系统工作正常")
        return True
    except Exception as e:
        print(f"❌ 日志系统测试失败: {e}")
        return False


async def test_database():
    """测试数据库连接"""
    print("\n🗄️ 测试数据库...")
    try:
        # 使用测试数据库
        db_manager = DatabaseManager("sqlite:///./data/test.db")
        await db_manager.initialize()
        
        # 健康检查
        is_healthy = await db_manager.health_check()
        if is_healthy:
            print("✅ 数据库连接正常")
            
            # 获取数据库信息
            db_info = await db_manager.get_database_info()
            print(f"📊 数据库信息: {db_info}")
            
            await db_manager.close()
            return True
        else:
            print("❌ 数据库健康检查失败")
            return False
            
    except Exception as e:
        print(f"❌ 数据库测试失败: {e}")
        return False


async def test_project_structure():
    """测试项目结构"""
    print("\n📁 检查项目结构...")
    
    required_dirs = [
        "src",
        "src/bot",
        "src/collector", 
        "src/classifier",
        "src/deduplicator",
        "src/storage",
        "src/database",
        "src/config",
        "src/utils"
    ]
    
    required_files = [
        "main.py",
        "requirements.txt",
        ".env.example",
        "src/__init__.py",
        "src/bot/telegram_bot.py",
        "src/bot/channel_manager.py",
        "src/collector/message_collector.py",
        "src/database/models.py",
        "src/database/database_manager.py",
        "src/config/settings.py",
        "src/utils/logger.py"
    ]
    
    missing_items = []
    
    # 检查目录
    for dir_path in required_dirs:
        if not Path(dir_path).exists():
            missing_items.append(f"目录: {dir_path}")
    
    # 检查文件
    for file_path in required_files:
        if not Path(file_path).exists():
            missing_items.append(f"文件: {file_path}")
    
    if missing_items:
        print("❌ 项目结构不完整，缺少以下项目:")
        for item in missing_items:
            print(f"   - {item}")
        return False
    else:
        print("✅ 项目结构完整")
        return True


async def test_imports():
    """测试模块导入"""
    print("\n📦 测试模块导入...")
    
    modules_to_test = [
        ("src.config.settings", "Settings"),
        ("src.database.database_manager", "DatabaseManager"),
        ("src.database.models", "Channel"),
        ("src.bot.telegram_bot", "TelegramBot"),
        ("src.bot.channel_manager", "ChannelManager"),
        ("src.collector.message_collector", "MessageCollector"),
        ("src.utils.logger", "setup_logger")
    ]
    
    failed_imports = []
    
    for module_name, class_name in modules_to_test:
        try:
            module = __import__(module_name, fromlist=[class_name])
            getattr(module, class_name)
            print(f"✅ {module_name}.{class_name}")
        except Exception as e:
            print(f"❌ {module_name}.{class_name}: {e}")
            failed_imports.append((module_name, class_name, str(e)))
    
    if failed_imports:
        print(f"\n❌ {len(failed_imports)} 个模块导入失败")
        return False
    else:
        print(f"\n✅ 所有 {len(modules_to_test)} 个模块导入成功")
        return True


async def main():
    """主测试函数"""
    print("🚀 开始基础功能测试...\n")
    
    tests = [
        ("项目结构", test_project_structure),
        ("模块导入", test_imports),
        ("日志系统", test_logger),
        ("数据库", test_database),
        ("配置加载", test_configuration)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} 测试出现异常: {e}")
            results.append((test_name, False))
    
    # 汇总结果
    print("\n" + "="*50)
    print("📋 测试结果汇总:")
    print("="*50)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name:12} : {status}")
        if result:
            passed += 1
    
    print("="*50)
    print(f"总计: {passed}/{total} 项测试通过")
    
    if passed == total:
        print("🎉 所有基础功能测试通过！")
        return 0
    else:
        print("⚠️  部分测试失败，请检查相关配置和依赖")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
