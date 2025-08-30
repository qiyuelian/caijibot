# -*- coding: utf-8 -*-
"""
数据库管理器
负责数据库连接、初始化和基本操作
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from .models import Base
from ..utils.logger import LoggerMixin


class DatabaseManager(LoggerMixin):
    """数据库管理器"""
    
    def __init__(self, database_url: str):
        """
        初始化数据库管理器
        
        Args:
            database_url: 数据库连接URL
        """
        self.database_url = database_url
        self.engine = None
        self.async_engine = None
        self.session_factory = None
        self.async_session_factory = None
        
        self.logger.info(f"初始化数据库管理器: {database_url}")
    
    async def initialize(self):
        """初始化数据库连接和表结构"""
        try:
            # 创建同步引擎（用于初始化）
            if self.database_url.startswith("sqlite"):
                # SQLite配置
                sync_url = self.database_url
                async_url = self.database_url.replace("sqlite://", "sqlite+aiosqlite://")
                
                self.engine = create_engine(
                    sync_url,
                    poolclass=StaticPool,
                    connect_args={"check_same_thread": False},
                    echo=False
                )
                
                self.async_engine = create_async_engine(
                    async_url,
                    poolclass=StaticPool,
                    connect_args={"check_same_thread": False},
                    echo=False
                )
                
                # 启用SQLite外键约束
                @event.listens_for(self.engine, "connect")
                def set_sqlite_pragma(dbapi_connection, connection_record):
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.close()
                
            else:
                # 其他数据库配置
                self.engine = create_engine(self.database_url, echo=False)
                self.async_engine = create_async_engine(self.database_url, echo=False)
            
            # 创建会话工厂
            self.session_factory = sessionmaker(
                bind=self.engine,
                autocommit=False,
                autoflush=False
            )
            
            self.async_session_factory = async_sessionmaker(
                bind=self.async_engine,
                class_=AsyncSession,
                autocommit=False,
                autoflush=False
            )
            
            # 创建所有表
            Base.metadata.create_all(bind=self.engine)
            
            self.logger.info("数据库初始化完成")
            
        except Exception as e:
            self.logger.error(f"数据库初始化失败: {e}")
            raise
    
    @asynccontextmanager
    async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        获取异步数据库会话
        
        Yields:
            AsyncSession: 异步数据库会话
        """
        if not self.async_session_factory:
            raise RuntimeError("数据库未初始化，请先调用 initialize() 方法")
        
        async with self.async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                self.logger.error(f"数据库会话错误: {e}")
                raise
            finally:
                await session.close()
    
    def get_session(self) -> Session:
        """
        获取同步数据库会话
        
        Returns:
            Session: 同步数据库会话
        """
        if not self.session_factory:
            raise RuntimeError("数据库未初始化，请先调用 initialize() 方法")
        
        return self.session_factory()
    
    async def close(self):
        """关闭数据库连接"""
        try:
            if self.async_engine:
                await self.async_engine.dispose()
            
            if self.engine:
                self.engine.dispose()
            
            self.logger.info("数据库连接已关闭")
            
        except Exception as e:
            self.logger.error(f"关闭数据库连接时出错: {e}")
    
    async def health_check(self) -> bool:
        """
        数据库健康检查
        
        Returns:
            bool: 数据库是否正常
        """
        try:
            async with self.get_async_session() as session:
                # 执行简单查询测试连接
                result = await session.execute("SELECT 1")
                return result.scalar() == 1
        except Exception as e:
            self.logger.error(f"数据库健康检查失败: {e}")
            return False
    
    async def get_database_info(self) -> dict:
        """
        获取数据库信息
        
        Returns:
            dict: 数据库信息
        """
        try:
            info = {
                "database_url": self.database_url,
                "engine_type": str(type(self.engine).__name__) if self.engine else None,
                "is_connected": await self.health_check(),
                "tables": []
            }
            
            if self.engine:
                # 获取表信息
                inspector = self.engine.dialect.get_table_names(self.engine.connect())
                info["tables"] = inspector
            
            return info
            
        except Exception as e:
            self.logger.error(f"获取数据库信息失败: {e}")
            return {"error": str(e)}
    
    async def backup_database(self, backup_path: str) -> bool:
        """
        备份数据库（仅支持SQLite）
        
        Args:
            backup_path: 备份文件路径
        
        Returns:
            bool: 备份是否成功
        """
        if not self.database_url.startswith("sqlite"):
            self.logger.warning("数据库备份仅支持SQLite")
            return False
        
        try:
            import shutil
            from pathlib import Path
            
            # 获取数据库文件路径
            db_path = self.database_url.replace("sqlite:///", "")
            
            # 复制数据库文件
            shutil.copy2(db_path, backup_path)
            
            self.logger.info(f"数据库备份完成: {backup_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"数据库备份失败: {e}")
            return False
    
    async def restore_database(self, backup_path: str) -> bool:
        """
        恢复数据库（仅支持SQLite）
        
        Args:
            backup_path: 备份文件路径
        
        Returns:
            bool: 恢复是否成功
        """
        if not self.database_url.startswith("sqlite"):
            self.logger.warning("数据库恢复仅支持SQLite")
            return False
        
        try:
            import shutil
            from pathlib import Path
            
            # 关闭当前连接
            await self.close()
            
            # 获取数据库文件路径
            db_path = self.database_url.replace("sqlite:///", "")
            
            # 恢复数据库文件
            shutil.copy2(backup_path, db_path)
            
            # 重新初始化连接
            await self.initialize()
            
            self.logger.info(f"数据库恢复完成: {backup_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"数据库恢复失败: {e}")
            return False
