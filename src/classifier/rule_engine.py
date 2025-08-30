# -*- coding: utf-8 -*-
"""
分类规则引擎
负责管理和执行分类规则
"""

import re
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from ..database.database_manager import DatabaseManager
from ..database.models import ClassificationRule, Tag, Message
from ..utils.logger import LoggerMixin


class RuleType(str, Enum):
    """规则类型枚举"""
    KEYWORD = "keyword"        # 关键词匹配
    REGEX = "regex"           # 正则表达式
    FILE_EXT = "file_ext"     # 文件扩展名
    FILE_SIZE = "file_size"   # 文件大小
    CONTENT_TYPE = "content_type"  # 内容类型


class TargetField(str, Enum):
    """目标字段枚举"""
    FILENAME = "filename"     # 文件名
    TEXT = "text"            # 消息文本
    BOTH = "both"            # 文件名和消息文本


class RuleEngine(LoggerMixin):
    """分类规则引擎"""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        初始化规则引擎
        
        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self._rules_cache = {}  # 规则缓存
        self._cache_valid = False
        
        self.logger.info("分类规则引擎初始化完成")
    
    async def load_rules(self) -> List[ClassificationRule]:
        """
        加载所有活跃的分类规则
        
        Returns:
            List[ClassificationRule]: 分类规则列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(ClassificationRule)
                    .options(selectinload(ClassificationRule.tag))
                    .where(ClassificationRule.is_active == True)
                    .order_by(ClassificationRule.priority.desc())
                )
                rules = result.scalars().all()
                
                # 更新缓存
                self._rules_cache = {rule.id: rule for rule in rules}
                self._cache_valid = True
                
                self.logger.info(f"加载了 {len(rules)} 条分类规则")
                return rules
                
        except Exception as e:
            self.logger.error(f"加载分类规则失败: {e}")
            return []
    
    async def classify_message(self, message: Message) -> List[Tuple[Tag, float]]:
        """
        对消息进行分类
        
        Args:
            message: 消息对象
        
        Returns:
            List[Tuple[Tag, float]]: 匹配的标签和置信度列表
        """
        if not self._cache_valid:
            await self.load_rules()
        
        matched_tags = []
        
        try:
            # 准备分类数据
            classification_data = {
                "filename": message.file_name or "",
                "text": message.message_text or "",
                "file_size": message.file_size or 0,
                "media_type": message.media_type or ""
            }
            
            # 遍历所有规则进行匹配
            for rule in self._rules_cache.values():
                confidence = await self._match_rule(rule, classification_data)
                if confidence > 0:
                    matched_tags.append((rule.tag, confidence))
                    
                    # 更新规则匹配统计
                    await self._update_rule_stats(rule.id)
            
            # 按置信度排序
            matched_tags.sort(key=lambda x: x[1], reverse=True)
            
            self.logger.debug(f"消息 {message.id} 匹配到 {len(matched_tags)} 个标签")
            return matched_tags
            
        except Exception as e:
            self.logger.error(f"分类消息失败: {e}")
            return []
    
    async def _match_rule(self, rule: ClassificationRule, data: Dict[str, Any]) -> float:
        """
        匹配单个规则
        
        Args:
            rule: 分类规则
            data: 分类数据
        
        Returns:
            float: 匹配置信度 (0-1)
        """
        try:
            rule_type = RuleType(rule.rule_type)
            target_field = TargetField(rule.target_field)
            pattern = rule.rule_pattern
            
            # 获取目标文本
            target_texts = []
            if target_field in [TargetField.FILENAME, TargetField.BOTH]:
                target_texts.append(data["filename"])
            if target_field in [TargetField.TEXT, TargetField.BOTH]:
                target_texts.append(data["text"])
            
            # 根据规则类型进行匹配
            if rule_type == RuleType.KEYWORD:
                return self._match_keyword(pattern, target_texts)
            
            elif rule_type == RuleType.REGEX:
                return self._match_regex(pattern, target_texts)
            
            elif rule_type == RuleType.FILE_EXT:
                return self._match_file_extension(pattern, data["filename"])
            
            elif rule_type == RuleType.FILE_SIZE:
                return self._match_file_size(pattern, data["file_size"])
            
            elif rule_type == RuleType.CONTENT_TYPE:
                return self._match_content_type(pattern, data["media_type"])
            
            return 0.0
            
        except Exception as e:
            self.logger.error(f"匹配规则失败: {e}")
            return 0.0
    
    def _match_keyword(self, pattern: str, target_texts: List[str]) -> float:
        """
        关键词匹配
        
        Args:
            pattern: 关键词模式 (支持多个关键词，用逗号分隔)
            target_texts: 目标文本列表
        
        Returns:
            float: 匹配置信度
        """
        keywords = [kw.strip().lower() for kw in pattern.split(",") if kw.strip()]
        if not keywords:
            return 0.0
        
        matched_count = 0
        total_keywords = len(keywords)
        
        for text in target_texts:
            if not text:
                continue
            
            text_lower = text.lower()
            for keyword in keywords:
                if keyword in text_lower:
                    matched_count += 1
                    break  # 每个文本最多匹配一次
        
        # 计算置信度：匹配的关键词数 / 总关键词数
        confidence = matched_count / total_keywords if total_keywords > 0 else 0.0
        return min(confidence, 1.0)
    
    def _match_regex(self, pattern: str, target_texts: List[str]) -> float:
        """
        正则表达式匹配
        
        Args:
            pattern: 正则表达式模式
            target_texts: 目标文本列表
        
        Returns:
            float: 匹配置信度
        """
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            
            for text in target_texts:
                if not text:
                    continue
                
                if regex.search(text):
                    return 1.0  # 正则匹配是二元的，匹配就是1.0
            
            return 0.0
            
        except re.error as e:
            self.logger.warning(f"无效的正则表达式: {pattern}, 错误: {e}")
            return 0.0
    
    def _match_file_extension(self, pattern: str, filename: str) -> float:
        """
        文件扩展名匹配
        
        Args:
            pattern: 扩展名模式 (支持多个扩展名，用逗号分隔)
            filename: 文件名
        
        Returns:
            float: 匹配置信度
        """
        if not filename:
            return 0.0
        
        file_ext = Path(filename).suffix.lower().lstrip('.')
        if not file_ext:
            return 0.0
        
        extensions = [ext.strip().lower().lstrip('.') for ext in pattern.split(",") if ext.strip()]
        
        return 1.0 if file_ext in extensions else 0.0
    
    def _match_file_size(self, pattern: str, file_size: int) -> float:
        """
        文件大小匹配
        
        Args:
            pattern: 大小模式 (格式: ">10MB", "<5MB", "1MB-10MB")
            file_size: 文件大小（字节）
        
        Returns:
            float: 匹配置信度
        """
        if file_size <= 0:
            return 0.0
        
        try:
            # 解析大小模式
            pattern = pattern.strip().upper()
            
            # 转换文件大小为MB
            size_mb = file_size / (1024 * 1024)
            
            if pattern.startswith('>'):
                # 大于某个大小
                threshold = self._parse_size(pattern[1:])
                return 1.0 if size_mb > threshold else 0.0
            
            elif pattern.startswith('<'):
                # 小于某个大小
                threshold = self._parse_size(pattern[1:])
                return 1.0 if size_mb < threshold else 0.0
            
            elif '-' in pattern:
                # 范围匹配
                parts = pattern.split('-')
                if len(parts) == 2:
                    min_size = self._parse_size(parts[0])
                    max_size = self._parse_size(parts[1])
                    return 1.0 if min_size <= size_mb <= max_size else 0.0
            
            return 0.0
            
        except Exception as e:
            self.logger.warning(f"无效的文件大小模式: {pattern}, 错误: {e}")
            return 0.0
    
    def _parse_size(self, size_str: str) -> float:
        """
        解析大小字符串
        
        Args:
            size_str: 大小字符串 (如 "10MB", "1.5GB")
        
        Returns:
            float: 大小（MB）
        """
        size_str = size_str.strip().upper()
        
        if size_str.endswith('KB'):
            return float(size_str[:-2]) / 1024
        elif size_str.endswith('MB'):
            return float(size_str[:-2])
        elif size_str.endswith('GB'):
            return float(size_str[:-2]) * 1024
        else:
            # 默认为MB
            return float(size_str)
    
    def _match_content_type(self, pattern: str, media_type: str) -> float:
        """
        内容类型匹配
        
        Args:
            pattern: 内容类型模式 (如 "video", "image", "document")
            media_type: 媒体类型
        
        Returns:
            float: 匹配置信度
        """
        if not media_type:
            return 0.0
        
        types = [t.strip().lower() for t in pattern.split(",") if t.strip()]
        return 1.0 if media_type.lower() in types else 0.0
    
    async def _update_rule_stats(self, rule_id: int):
        """
        更新规则匹配统计
        
        Args:
            rule_id: 规则ID
        """
        try:
            async with self.db_manager.get_async_session() as session:
                await session.execute(
                    update(ClassificationRule)
                    .where(ClassificationRule.id == rule_id)
                    .values(match_count=ClassificationRule.match_count + 1)
                )
                await session.commit()
        except Exception as e:
            self.logger.error(f"更新规则统计失败: {e}")
    
    async def add_rule(
        self, 
        name: str, 
        rule_type: RuleType, 
        rule_pattern: str, 
        target_field: TargetField, 
        tag_id: int,
        description: str = None,
        priority: int = 0
    ) -> Optional[ClassificationRule]:
        """
        添加新的分类规则
        
        Args:
            name: 规则名称
            rule_type: 规则类型
            rule_pattern: 规则模式
            target_field: 目标字段
            tag_id: 标签ID
            description: 规则描述
            priority: 优先级
        
        Returns:
            Optional[ClassificationRule]: 创建的规则对象
        """
        try:
            async with self.db_manager.get_async_session() as session:
                new_rule = ClassificationRule(
                    name=name,
                    description=description,
                    rule_type=rule_type.value,
                    rule_pattern=rule_pattern,
                    target_field=target_field.value,
                    tag_id=tag_id,
                    priority=priority,
                    is_active=True
                )
                
                session.add(new_rule)
                await session.commit()
                
                # 刷新缓存
                self._cache_valid = False
                
                self.logger.info(f"添加新分类规则: {name}")
                return new_rule
                
        except Exception as e:
            self.logger.error(f"添加分类规则失败: {e}")
            return None
    
    async def update_rule(self, rule_id: int, **kwargs) -> bool:
        """
        更新分类规则
        
        Args:
            rule_id: 规则ID
            **kwargs: 要更新的字段
        
        Returns:
            bool: 是否更新成功
        """
        try:
            async with self.db_manager.get_async_session() as session:
                await session.execute(
                    update(ClassificationRule)
                    .where(ClassificationRule.id == rule_id)
                    .values(**kwargs)
                )
                await session.commit()
                
                # 刷新缓存
                self._cache_valid = False
                
                self.logger.info(f"更新分类规则 {rule_id}")
                return True
                
        except Exception as e:
            self.logger.error(f"更新分类规则失败: {e}")
            return False
    
    async def delete_rule(self, rule_id: int) -> bool:
        """
        删除分类规则（软删除，设置为非活跃）
        
        Args:
            rule_id: 规则ID
        
        Returns:
            bool: 是否删除成功
        """
        return await self.update_rule(rule_id, is_active=False)
    
    async def get_rules(self, active_only: bool = True) -> List[ClassificationRule]:
        """
        获取分类规则列表
        
        Args:
            active_only: 是否只获取活跃规则
        
        Returns:
            List[ClassificationRule]: 规则列表
        """
        try:
            async with self.db_manager.get_async_session() as session:
                query = select(ClassificationRule).options(selectinload(ClassificationRule.tag))
                
                if active_only:
                    query = query.where(ClassificationRule.is_active == True)
                
                query = query.order_by(ClassificationRule.priority.desc())
                
                result = await session.execute(query)
                return result.scalars().all()
                
        except Exception as e:
            self.logger.error(f"获取分类规则失败: {e}")
            return []
