# -*- coding: utf-8 -*-
"""
性能监控工具
监控系统性能指标和资源使用情况
"""

import asyncio
import time
import psutil
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from functools import wraps

from .logger import LoggerMixin


class PerformanceMonitor(LoggerMixin):
    """性能监控器"""
    
    def __init__(self):
        """初始化性能监控器"""
        self.metrics_history = []
        self.is_monitoring = False
        self.start_time = datetime.utcnow()
        
        # 性能阈值
        self.thresholds = {
            "cpu_warning": 80.0,      # CPU使用率警告阈值
            "memory_warning": 80.0,   # 内存使用率警告阈值
            "disk_warning": 85.0,     # 磁盘使用率警告阈值
            "response_time_warning": 2.0  # 响应时间警告阈值（秒）
        }
        
        self.logger.info("性能监控器初始化完成")
    
    async def start_monitoring(self, interval_seconds: int = 60):
        """
        开始性能监控
        
        Args:
            interval_seconds: 监控间隔（秒）
        """
        if self.is_monitoring:
            self.logger.warning("性能监控器已在运行中")
            return
        
        self.is_monitoring = True
        self.logger.info(f"开始性能监控，间隔: {interval_seconds}秒")
        
        try:
            while self.is_monitoring:
                metrics = await self.collect_metrics()
                self.metrics_history.append(metrics)
                
                # 保持历史记录在合理大小
                if len(self.metrics_history) > 1440:  # 24小时的分钟数
                    self.metrics_history = self.metrics_history[-720:]  # 保留12小时
                
                # 检查性能警告
                await self._check_performance_warnings(metrics)
                
                await asyncio.sleep(interval_seconds)
                
        except Exception as e:
            self.logger.error(f"性能监控出错: {e}")
        finally:
            self.is_monitoring = False
    
    async def stop_monitoring(self):
        """停止性能监控"""
        self.is_monitoring = False
        self.logger.info("停止性能监控")
    
    async def collect_metrics(self) -> Dict[str, Any]:
        """
        收集性能指标
        
        Returns:
            Dict: 性能指标
        """
        try:
            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # 内存使用情况
            memory = psutil.virtual_memory()
            
            # 磁盘使用情况
            disk = psutil.disk_usage('/')
            
            # 网络IO
            network = psutil.net_io_counters()
            
            # 进程信息
            process = psutil.Process()
            process_memory = process.memory_info()
            
            metrics = {
                "timestamp": datetime.utcnow().isoformat(),
                "cpu": {
                    "percent": cpu_percent,
                    "count": psutil.cpu_count()
                },
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "percent": memory.percent,
                    "used": memory.used
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": (disk.used / disk.total) * 100
                },
                "network": {
                    "bytes_sent": network.bytes_sent,
                    "bytes_recv": network.bytes_recv,
                    "packets_sent": network.packets_sent,
                    "packets_recv": network.packets_recv
                },
                "process": {
                    "memory_rss": process_memory.rss,
                    "memory_vms": process_memory.vms,
                    "memory_percent": process.memory_percent(),
                    "cpu_percent": process.cpu_percent(),
                    "num_threads": process.num_threads()
                }
            }
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"收集性能指标失败: {e}")
            return {"error": str(e), "timestamp": datetime.utcnow().isoformat()}
    
    async def _check_performance_warnings(self, metrics: Dict[str, Any]):
        """检查性能警告"""
        try:
            warnings = []
            
            # 检查CPU使用率
            if metrics["cpu"]["percent"] > self.thresholds["cpu_warning"]:
                warnings.append(f"CPU使用率过高: {metrics['cpu']['percent']:.1f}%")
            
            # 检查内存使用率
            if metrics["memory"]["percent"] > self.thresholds["memory_warning"]:
                warnings.append(f"内存使用率过高: {metrics['memory']['percent']:.1f}%")
            
            # 检查磁盘使用率
            if metrics["disk"]["percent"] > self.thresholds["disk_warning"]:
                warnings.append(f"磁盘使用率过高: {metrics['disk']['percent']:.1f}%")
            
            # 记录警告
            for warning in warnings:
                self.logger.warning(f"性能警告: {warning}")
            
        except Exception as e:
            self.logger.error(f"检查性能警告失败: {e}")
    
    async def get_performance_summary(self, hours: int = 1) -> Dict[str, Any]:
        """
        获取性能摘要
        
        Args:
            hours: 统计小时数
        
        Returns:
            Dict: 性能摘要
        """
        try:
            if not self.metrics_history:
                return {"error": "暂无性能数据"}
            
            # 过滤指定时间范围的数据
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            recent_metrics = [
                m for m in self.metrics_history
                if datetime.fromisoformat(m["timestamp"]) > cutoff_time
            ]
            
            if not recent_metrics:
                return {"error": f"过去{hours}小时内暂无性能数据"}
            
            # 计算平均值和峰值
            cpu_values = [m["cpu"]["percent"] for m in recent_metrics if "cpu" in m]
            memory_values = [m["memory"]["percent"] for m in recent_metrics if "memory" in m]
            disk_values = [m["disk"]["percent"] for m in recent_metrics if "disk" in m]
            
            summary = {
                "period_hours": hours,
                "data_points": len(recent_metrics),
                "cpu": {
                    "avg": sum(cpu_values) / len(cpu_values) if cpu_values else 0,
                    "max": max(cpu_values) if cpu_values else 0,
                    "min": min(cpu_values) if cpu_values else 0
                },
                "memory": {
                    "avg": sum(memory_values) / len(memory_values) if memory_values else 0,
                    "max": max(memory_values) if memory_values else 0,
                    "min": min(memory_values) if memory_values else 0
                },
                "disk": {
                    "avg": sum(disk_values) / len(disk_values) if disk_values else 0,
                    "max": max(disk_values) if disk_values else 0,
                    "min": min(disk_values) if disk_values else 0
                },
                "uptime_hours": (datetime.utcnow() - self.start_time).total_seconds() / 3600,
                "monitoring_status": self.is_monitoring
            }
            
            return summary
            
        except Exception as e:
            self.logger.error(f"获取性能摘要失败: {e}")
            return {"error": str(e)}
    
    async def get_current_metrics(self) -> Dict[str, Any]:
        """
        获取当前性能指标
        
        Returns:
            Dict: 当前性能指标
        """
        return await self.collect_metrics()
    
    def set_thresholds(self, thresholds: Dict[str, float]):
        """
        设置性能阈值
        
        Args:
            thresholds: 阈值配置
        """
        self.thresholds.update(thresholds)
        self.logger.info(f"更新性能阈值: {thresholds}")


def performance_timer(func):
    """
    性能计时装饰器
    
    Args:
        func: 要计时的函数
    
    Returns:
        装饰后的函数
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            end_time = time.time()
            execution_time = end_time - start_time
            
            # 记录性能日志
            func_name = func.__name__
            if execution_time > 1.0:  # 超过1秒的操作记录警告
                print(f"⚠️ 性能警告: {func_name} 执行时间 {execution_time:.2f}秒")
            else:
                print(f"✅ 性能正常: {func_name} 执行时间 {execution_time:.3f}秒")
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            end_time = time.time()
            execution_time = end_time - start_time
            
            # 记录性能日志
            func_name = func.__name__
            if execution_time > 0.5:  # 超过0.5秒的同步操作记录警告
                print(f"⚠️ 性能警告: {func_name} 执行时间 {execution_time:.2f}秒")
            else:
                print(f"✅ 性能正常: {func_name} 执行时间 {execution_time:.3f}秒")
    
    # 根据函数类型返回对应的装饰器
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


async def run_performance_benchmark():
    """运行性能基准测试"""
    print("🚀 开始性能基准测试")
    print("=" * 50)
    
    monitor = PerformanceMonitor()
    
    # 收集基准指标
    baseline_metrics = await monitor.collect_metrics()
    
    print("📊 基准性能指标:")
    print(f"CPU使用率: {baseline_metrics['cpu']['percent']:.1f}%")
    print(f"内存使用率: {baseline_metrics['memory']['percent']:.1f}%")
    print(f"磁盘使用率: {baseline_metrics['disk']['percent']:.1f}%")
    print(f"进程内存: {baseline_metrics['process']['memory_rss'] / (1024*1024):.1f} MB")
    
    return baseline_metrics
