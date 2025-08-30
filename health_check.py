#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统健康检查工具
检查系统各组件的健康状态
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config.settings import Settings
from src.database.database_manager import DatabaseManager
from src.utils.performance_monitor import PerformanceMonitor


class HealthChecker:
    """系统健康检查器"""
    
    def __init__(self):
        """初始化健康检查器"""
        self.checks = []
        self.results = {}
    
    async def run_all_checks(self) -> Dict[str, Any]:
        """运行所有健康检查"""
        print("🏥 开始系统健康检查")
        print("=" * 50)
        
        self.results = {
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": "unknown",
            "checks": {}
        }
        
        # 1. 配置检查
        config_result = await self._check_configuration()
        self.results["checks"]["configuration"] = config_result
        
        # 2. 数据库检查
        database_result = await self._check_database()
        self.results["checks"]["database"] = database_result
        
        # 3. 存储检查
        storage_result = await self._check_storage()
        self.results["checks"]["storage"] = storage_result
        
        # 4. 依赖检查
        dependencies_result = await self._check_dependencies()
        self.results["checks"]["dependencies"] = dependencies_result
        
        # 5. 性能检查
        performance_result = await self._check_performance()
        self.results["checks"]["performance"] = performance_result
        
        # 6. 网络检查
        network_result = await self._check_network()
        self.results["checks"]["network"] = network_result
        
        # 计算总体状态
        self._calculate_overall_status()
        
        return self.results
    
    async def _check_configuration(self) -> Dict[str, Any]:
        """检查配置"""
        print("⚙️ 检查配置...")
        
        try:
            settings = Settings()
            
            checks = {
                "config_file_exists": Path(".env").exists(),
                "required_fields": {
                    "bot_token": bool(getattr(settings, 'bot_token', None)),
                    "api_id": bool(getattr(settings, 'api_id', None)),
                    "api_hash": bool(getattr(settings, 'api_hash', None)),
                    "database_url": bool(getattr(settings, 'database_url', None))
                },
                "storage_path": Path(settings.storage_path).exists() or True,  # 可以创建
                "settings_valid": True
            }
            
            all_required = all(checks["required_fields"].values())
            
            result = {
                "status": "healthy" if all_required else "warning",
                "details": checks,
                "message": "配置正常" if all_required else "部分必需配置缺失"
            }
            
            print(f"   {'✅' if all_required else '⚠️'} {result['message']}")
            return result
            
        except Exception as e:
            result = {
                "status": "error",
                "details": {"error": str(e)},
                "message": f"配置检查失败: {e}"
            }
            print(f"   ❌ {result['message']}")
            return result
    
    async def _check_database(self) -> Dict[str, Any]:
        """检查数据库"""
        print("🗄️ 检查数据库...")
        
        try:
            settings = Settings()
            db_manager = DatabaseManager(settings)
            
            # 测试数据库连接
            await db_manager.initialize()
            health = await db_manager.health_check()
            
            # 检查表结构
            async with db_manager.get_async_session() as session:
                from sqlalchemy import text
                
                # 检查主要表是否存在
                tables_to_check = ["channels", "messages", "tags", "message_tags"]
                existing_tables = []
                
                for table in tables_to_check:
                    try:
                        result = await session.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
                        existing_tables.append(table)
                    except:
                        pass
            
            await db_manager.close()
            
            result = {
                "status": "healthy" if health and len(existing_tables) == len(tables_to_check) else "warning",
                "details": {
                    "connection": health,
                    "tables_exist": existing_tables,
                    "expected_tables": tables_to_check
                },
                "message": "数据库正常" if health else "数据库连接失败"
            }
            
            print(f"   {'✅' if health else '❌'} {result['message']}")
            return result
            
        except Exception as e:
            result = {
                "status": "error",
                "details": {"error": str(e)},
                "message": f"数据库检查失败: {e}"
            }
            print(f"   ❌ {result['message']}")
            return result
    
    async def _check_storage(self) -> Dict[str, Any]:
        """检查存储"""
        print("💾 检查存储...")
        
        try:
            settings = Settings()
            storage_path = Path(settings.storage_path)
            
            # 检查存储路径
            can_create = True
            can_write = True
            
            try:
                storage_path.mkdir(parents=True, exist_ok=True)
                
                # 测试写入权限
                test_file = storage_path / "health_check_test.txt"
                test_file.write_text("health check")
                test_file.unlink()
                
            except Exception as e:
                can_create = False
                can_write = False
            
            # 检查磁盘空间
            import shutil
            disk_usage = shutil.disk_usage(storage_path.parent)
            free_gb = disk_usage.free / (1024**3)
            
            result = {
                "status": "healthy" if can_create and can_write and free_gb > 1 else "warning",
                "details": {
                    "storage_path": str(storage_path),
                    "path_exists": storage_path.exists(),
                    "can_create": can_create,
                    "can_write": can_write,
                    "free_space_gb": free_gb
                },
                "message": "存储正常" if can_write else "存储访问异常"
            }
            
            print(f"   {'✅' if can_write else '❌'} {result['message']}")
            return result
            
        except Exception as e:
            result = {
                "status": "error",
                "details": {"error": str(e)},
                "message": f"存储检查失败: {e}"
            }
            print(f"   ❌ {result['message']}")
            return result
    
    async def _check_dependencies(self) -> Dict[str, Any]:
        """检查依赖"""
        print("📦 检查依赖...")
        
        required_packages = [
            "telethon", "python-telegram-bot", "sqlalchemy", 
            "aiofiles", "pillow", "opencv-python", "numpy"
        ]
        
        installed_packages = []
        missing_packages = []
        
        for package in required_packages:
            try:
                __import__(package.replace("-", "_"))
                installed_packages.append(package)
            except ImportError:
                missing_packages.append(package)
        
        result = {
            "status": "healthy" if not missing_packages else "error",
            "details": {
                "installed": installed_packages,
                "missing": missing_packages,
                "total_required": len(required_packages)
            },
            "message": "所有依赖已安装" if not missing_packages else f"缺失 {len(missing_packages)} 个依赖"
        }
        
        print(f"   {'✅' if not missing_packages else '❌'} {result['message']}")
        return result
    
    async def _check_performance(self) -> Dict[str, Any]:
        """检查性能"""
        print("⚡ 检查性能...")
        
        try:
            monitor = PerformanceMonitor()
            metrics = await monitor.collect_metrics()
            
            # 评估性能状态
            cpu_ok = metrics["cpu"]["percent"] < 80
            memory_ok = metrics["memory"]["percent"] < 80
            disk_ok = metrics["disk"]["percent"] < 85
            
            performance_ok = cpu_ok and memory_ok and disk_ok
            
            result = {
                "status": "healthy" if performance_ok else "warning",
                "details": {
                    "cpu_percent": metrics["cpu"]["percent"],
                    "memory_percent": metrics["memory"]["percent"],
                    "disk_percent": metrics["disk"]["percent"],
                    "process_memory_mb": metrics["process"]["memory_rss"] / (1024*1024)
                },
                "message": "性能正常" if performance_ok else "性能指标异常"
            }
            
            print(f"   {'✅' if performance_ok else '⚠️'} {result['message']}")
            return result
            
        except Exception as e:
            result = {
                "status": "error",
                "details": {"error": str(e)},
                "message": f"性能检查失败: {e}"
            }
            print(f"   ❌ {result['message']}")
            return result
    
    async def _check_network(self) -> Dict[str, Any]:
        """检查网络"""
        print("🌐 检查网络...")
        
        try:
            import aiohttp
            
            # 测试网络连接
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    async with session.get("https://api.telegram.org") as response:
                        telegram_accessible = response.status == 200
                except:
                    telegram_accessible = False
            
            result = {
                "status": "healthy" if telegram_accessible else "warning",
                "details": {
                    "telegram_api_accessible": telegram_accessible
                },
                "message": "网络连接正常" if telegram_accessible else "Telegram API不可访问"
            }
            
            print(f"   {'✅' if telegram_accessible else '⚠️'} {result['message']}")
            return result
            
        except Exception as e:
            result = {
                "status": "error", 
                "details": {"error": str(e)},
                "message": f"网络检查失败: {e}"
            }
            print(f"   ❌ {result['message']}")
            return result
    
    def _calculate_overall_status(self):
        """计算总体状态"""
        statuses = [check["status"] for check in self.results["checks"].values()]
        
        if "error" in statuses:
            self.results["overall_status"] = "error"
        elif "warning" in statuses:
            self.results["overall_status"] = "warning"
        else:
            self.results["overall_status"] = "healthy"
    
    def print_summary(self):
        """打印检查摘要"""
        print("\n" + "=" * 50)
        print("📋 健康检查摘要")
        print("=" * 50)
        
        status_emoji = {
            "healthy": "✅",
            "warning": "⚠️", 
            "error": "❌",
            "unknown": "❓"
        }
        
        overall_emoji = status_emoji.get(self.results["overall_status"], "❓")
        print(f"🏥 总体状态: {overall_emoji} {self.results['overall_status'].upper()}")
        
        print("\n📊 详细结果:")
        for check_name, check_result in self.results["checks"].items():
            emoji = status_emoji.get(check_result["status"], "❓")
            print(f"   {emoji} {check_name}: {check_result['message']}")
        
        # 给出建议
        if self.results["overall_status"] == "error":
            print("\n🚨 发现严重问题，请检查错误信息并修复")
        elif self.results["overall_status"] == "warning":
            print("\n⚠️ 发现警告，建议检查相关配置")
        else:
            print("\n🎉 系统健康状态良好!")


async def main():
    """主函数"""
    print("🏥 Telegram Bot 采集系统 - 健康检查")
    print("=" * 60)
    
    checker = HealthChecker()
    
    try:
        # 运行健康检查
        results = await checker.run_all_checks()
        
        # 打印摘要
        checker.print_summary()
        
        # 保存结果
        import json
        with open("health_check_report.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n📄 详细报告已保存: health_check_report.json")
        
        # 返回退出码
        if results["overall_status"] == "healthy":
            return 0
        elif results["overall_status"] == "warning":
            return 1
        else:
            return 2
            
    except Exception as e:
        print(f"\n❌ 健康检查失败: {e}")
        import traceback
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⚠️ 健康检查被用户中断")
        sys.exit(1)
