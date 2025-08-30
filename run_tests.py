#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试运行脚本
运行所有测试用例并生成报告
"""

import asyncio
import sys
import os
import subprocess
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils.performance_monitor import run_performance_benchmark


def run_pytest_tests():
    """运行pytest测试"""
    print("🧪 运行pytest测试套件")
    print("=" * 50)
    
    try:
        # 运行pytest命令
        result = subprocess.run([
            sys.executable, "-m", "pytest", 
            "tests/", 
            "-v",                    # 详细输出
            "--tb=short",           # 简短的错误回溯
            "--durations=10",       # 显示最慢的10个测试
            "--cov=src",            # 代码覆盖率
            "--cov-report=term-missing",  # 显示未覆盖的行
            "--cov-report=html:htmlcov"   # 生成HTML覆盖率报告
        ], capture_output=True, text=True, timeout=300)
        
        print("📊 测试结果:")
        print(result.stdout)
        
        if result.stderr:
            print("⚠️ 警告和错误:")
            print(result.stderr)
        
        if result.returncode == 0:
            print("✅ 所有测试通过!")
        else:
            print(f"❌ 测试失败，退出码: {result.returncode}")
        
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print("❌ 测试超时（5分钟）")
        return False
    except Exception as e:
        print(f"❌ 运行测试时出错: {e}")
        return False


def check_test_dependencies():
    """检查测试依赖"""
    print("🔍 检查测试依赖")
    print("=" * 30)
    
    required_packages = [
        "pytest",
        "pytest-asyncio", 
        "pytest-cov",
        "psutil"
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} - 未安装")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n📦 请安装缺失的包:")
        print(f"pip install {' '.join(missing_packages)}")
        return False
    
    print("✅ 所有测试依赖已满足")
    return True


async def run_integration_tests():
    """运行集成测试"""
    print("\n🔗 运行集成测试")
    print("=" * 30)
    
    try:
        # 测试数据库连接
        print("📊 测试数据库连接...")
        from src.config.settings import Settings
        from src.database.database_manager import DatabaseManager
        
        # 使用临时数据库
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                database_url=f"sqlite:///{temp_dir}/test_integration.db",
                storage_path=f"{temp_dir}/storage",
                bot_token="test_token",
                api_id=12345,
                api_hash="test_hash"
            )
            
            db_manager = DatabaseManager(settings)
            await db_manager.initialize()
            
            # 测试健康检查
            health = await db_manager.health_check()
            if health:
                print("✅ 数据库连接正常")
            else:
                print("❌ 数据库连接失败")
                return False
            
            await db_manager.close()
        
        # 测试性能基准
        print("⚡ 运行性能基准测试...")
        await run_performance_benchmark()
        
        print("✅ 集成测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_test_report():
    """生成测试报告"""
    print("\n📋 生成测试报告")
    print("=" * 30)
    
    try:
        # 检查覆盖率报告
        htmlcov_path = Path("htmlcov/index.html")
        if htmlcov_path.exists():
            print(f"✅ HTML覆盖率报告: {htmlcov_path.absolute()}")
        
        # 生成简单的测试摘要
        report_content = f"""
# 测试报告

生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}

## 测试环境
- Python版本: {sys.version}
- 操作系统: {os.name}
- 工作目录: {os.getcwd()}

## 测试文件
- 数据库测试: tests/test_database.py
- 去重功能测试: tests/test_deduplication.py  
- 存储功能测试: tests/test_storage.py
- 标签统计测试: tests/test_tag_statistics.py
- 机器人命令测试: tests/test_bot_commands.py

## 覆盖率报告
详细覆盖率报告请查看: htmlcov/index.html

## 性能基准
性能基准测试结果已在控制台输出
        """
        
        # 保存报告
        with open("test_report.md", "w", encoding="utf-8") as f:
            f.write(report_content)
        
        print("✅ 测试报告已生成: test_report.md")
        return True
        
    except Exception as e:
        print(f"❌ 生成测试报告失败: {e}")
        return False


async def main():
    """主函数"""
    print("🚀 Telegram Bot 采集系统 - 测试套件")
    print("=" * 60)
    
    start_time = time.time()
    
    # 1. 检查依赖
    if not check_test_dependencies():
        print("❌ 测试依赖检查失败，请安装缺失的包")
        return 1
    
    # 2. 运行集成测试
    integration_success = await run_integration_tests()
    if not integration_success:
        print("❌ 集成测试失败")
        return 1
    
    # 3. 运行pytest测试
    pytest_success = run_pytest_tests()
    
    # 4. 生成测试报告
    generate_test_report()
    
    # 5. 总结
    end_time = time.time()
    total_time = end_time - start_time
    
    print("\n" + "=" * 60)
    print("📊 测试总结")
    print("=" * 60)
    print(f"总耗时: {total_time:.2f} 秒")
    
    if integration_success and pytest_success:
        print("🎉 所有测试通过!")
        print("✅ 系统功能正常")
        print("📋 详细报告: test_report.md")
        print("📊 覆盖率报告: htmlcov/index.html")
        return 0
    else:
        print("❌ 部分测试失败")
        if not integration_success:
            print("  - 集成测试失败")
        if not pytest_success:
            print("  - 单元测试失败")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⚠️ 测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试运行出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
