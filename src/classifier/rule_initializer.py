# -*- coding: utf-8 -*-
"""
分类规则初始化器
负责初始化默认的分类规则和标签
"""

import asyncio
from typing import List, Dict, Any

from ..database.database_manager import DatabaseManager
from ..utils.logger import LoggerMixin
from .tag_manager import TagManager
from .rule_engine import RuleEngine, RuleType, TargetField
from .default_rules import DefaultRules


class RuleInitializer(LoggerMixin):
    """分类规则初始化器"""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        初始化规则初始化器
        
        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.tag_manager = TagManager(db_manager)
        self.rule_engine = RuleEngine(db_manager)
        
        self.logger.info("分类规则初始化器初始化完成")
    
    async def initialize_default_rules(self, rule_type: str = "all") -> Dict[str, Any]:
        """
        初始化默认分类规则
        
        Args:
            rule_type: 规则类型 ("all", "basic", "content", "size")
        
        Returns:
            Dict: 初始化结果
        """
        try:
            # 获取规则配置
            if rule_type == "basic":
                rules_config = DefaultRules.get_basic_rules()
            elif rule_type == "content":
                rules_config = DefaultRules.get_content_rules()
            elif rule_type == "size":
                rules_config = DefaultRules.get_size_rules()
            else:  # all
                rules_config = DefaultRules.get_default_rules()
            
            results = {
                "total_rules": len(rules_config),
                "created_tags": 0,
                "created_rules": 0,
                "skipped_rules": 0,
                "errors": []
            }
            
            self.logger.info(f"开始初始化 {len(rules_config)} 条默认规则")
            
            for rule_config in rules_config:
                try:
                    # 创建或获取标签
                    tag = await self.tag_manager.get_or_create_tag(
                        name=rule_config["tag_name"],
                        description=rule_config.get("tag_description"),
                        color=rule_config.get("tag_color")
                    )
                    
                    if not tag:
                        results["errors"].append(f"无法创建标签: {rule_config['tag_name']}")
                        continue
                    
                    # 检查是否已存在相同的规则
                    existing_rules = await self.rule_engine.get_rules(active_only=False)
                    rule_exists = any(
                        r.name == rule_config["name"] and 
                        r.rule_type == rule_config["rule_type"].value
                        for r in existing_rules
                    )
                    
                    if rule_exists:
                        results["skipped_rules"] += 1
                        self.logger.debug(f"规则已存在，跳过: {rule_config['name']}")
                        continue
                    
                    # 创建分类规则
                    new_rule = await self.rule_engine.add_rule(
                        name=rule_config["name"],
                        rule_type=RuleType(rule_config["rule_type"]),
                        rule_pattern=rule_config["rule_pattern"],
                        target_field=TargetField(rule_config["target_field"]),
                        tag_id=tag.id,
                        description=rule_config.get("description"),
                        priority=rule_config.get("priority", 0)
                    )
                    
                    if new_rule:
                        results["created_rules"] += 1
                        self.logger.debug(f"创建规则: {rule_config['name']}")
                    else:
                        results["errors"].append(f"创建规则失败: {rule_config['name']}")
                
                except Exception as e:
                    error_msg = f"处理规则 {rule_config['name']} 时出错: {e}"
                    results["errors"].append(error_msg)
                    self.logger.error(error_msg)
            
            self.logger.info(
                f"默认规则初始化完成: "
                f"创建 {results['created_rules']} 条规则, "
                f"跳过 {results['skipped_rules']} 条, "
                f"错误 {len(results['errors'])} 个"
            )
            
            return results
            
        except Exception as e:
            self.logger.error(f"初始化默认规则失败: {e}")
            return {
                "total_rules": 0,
                "created_tags": 0,
                "created_rules": 0,
                "skipped_rules": 0,
                "errors": [str(e)]
            }
    
    async def create_custom_rule(
        self,
        name: str,
        rule_type: str,
        rule_pattern: str,
        target_field: str,
        tag_name: str,
        tag_description: str = None,
        tag_color: str = None,
        description: str = None,
        priority: int = 0
    ) -> Dict[str, Any]:
        """
        创建自定义分类规则
        
        Args:
            name: 规则名称
            rule_type: 规则类型
            rule_pattern: 规则模式
            target_field: 目标字段
            tag_name: 标签名称
            tag_description: 标签描述
            tag_color: 标签颜色
            description: 规则描述
            priority: 优先级
        
        Returns:
            Dict: 创建结果
        """
        try:
            # 验证规则类型和目标字段
            try:
                rule_type_enum = RuleType(rule_type)
                target_field_enum = TargetField(target_field)
            except ValueError as e:
                return {"success": False, "error": f"无效的参数: {e}"}
            
            # 创建或获取标签
            tag = await self.tag_manager.get_or_create_tag(
                name=tag_name,
                description=tag_description,
                color=tag_color
            )
            
            if not tag:
                return {"success": False, "error": "无法创建标签"}
            
            # 创建分类规则
            new_rule = await self.rule_engine.add_rule(
                name=name,
                rule_type=rule_type_enum,
                rule_pattern=rule_pattern,
                target_field=target_field_enum,
                tag_id=tag.id,
                description=description,
                priority=priority
            )
            
            if new_rule:
                self.logger.info(f"创建自定义规则: {name}")
                return {
                    "success": True,
                    "rule_id": new_rule.id,
                    "tag_id": tag.id,
                    "message": f"成功创建规则 '{name}'"
                }
            else:
                return {"success": False, "error": "创建规则失败"}
                
        except Exception as e:
            self.logger.error(f"创建自定义规则失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def export_rules(self) -> List[Dict[str, Any]]:
        """
        导出所有分类规则
        
        Returns:
            List[Dict]: 规则配置列表
        """
        try:
            rules = await self.rule_engine.get_rules(active_only=False)
            
            exported_rules = []
            for rule in rules:
                rule_config = {
                    "name": rule.name,
                    "description": rule.description,
                    "rule_type": rule.rule_type,
                    "rule_pattern": rule.rule_pattern,
                    "target_field": rule.target_field,
                    "tag_name": rule.tag.name,
                    "tag_description": rule.tag.description,
                    "tag_color": rule.tag.color,
                    "priority": rule.priority,
                    "is_active": rule.is_active,
                    "match_count": rule.match_count,
                    "created_at": rule.created_at.isoformat()
                }
                exported_rules.append(rule_config)
            
            self.logger.info(f"导出了 {len(exported_rules)} 条规则")
            return exported_rules
            
        except Exception as e:
            self.logger.error(f"导出规则失败: {e}")
            return []
    
    async def import_rules(self, rules_config: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        导入分类规则
        
        Args:
            rules_config: 规则配置列表
        
        Returns:
            Dict: 导入结果
        """
        results = {
            "total_rules": len(rules_config),
            "imported_rules": 0,
            "skipped_rules": 0,
            "errors": []
        }
        
        try:
            for rule_config in rules_config:
                try:
                    result = await self.create_custom_rule(
                        name=rule_config["name"],
                        rule_type=rule_config["rule_type"],
                        rule_pattern=rule_config["rule_pattern"],
                        target_field=rule_config["target_field"],
                        tag_name=rule_config["tag_name"],
                        tag_description=rule_config.get("tag_description"),
                        tag_color=rule_config.get("tag_color"),
                        description=rule_config.get("description"),
                        priority=rule_config.get("priority", 0)
                    )
                    
                    if result["success"]:
                        results["imported_rules"] += 1
                    else:
                        results["skipped_rules"] += 1
                        results["errors"].append(f"{rule_config['name']}: {result['error']}")
                
                except Exception as e:
                    results["errors"].append(f"{rule_config.get('name', 'Unknown')}: {e}")
            
            self.logger.info(
                f"规则导入完成: "
                f"导入 {results['imported_rules']} 条, "
                f"跳过 {results['skipped_rules']} 条, "
                f"错误 {len(results['errors'])} 个"
            )
            
            return results
            
        except Exception as e:
            self.logger.error(f"导入规则失败: {e}")
            results["errors"].append(str(e))
            return results
    
    async def reset_rules(self) -> Dict[str, Any]:
        """
        重置所有分类规则（删除所有规则和未使用的标签）
        
        Returns:
            Dict: 重置结果
        """
        try:
            # 获取所有规则
            rules = await self.rule_engine.get_rules(active_only=False)
            
            # 删除所有规则
            deleted_rules = 0
            for rule in rules:
                if await self.rule_engine.delete_rule(rule.id):
                    deleted_rules += 1
            
            # 获取未使用的标签并删除
            tags = await self.tag_manager.list_tags()
            deleted_tags = 0
            for tag in tags:
                if tag["usage_count"] == 0:
                    result = await self.tag_manager.delete_tag(tag["id"], force=True)
                    if result["success"]:
                        deleted_tags += 1
            
            self.logger.info(f"重置完成: 删除 {deleted_rules} 条规则, {deleted_tags} 个标签")
            
            return {
                "success": True,
                "deleted_rules": deleted_rules,
                "deleted_tags": deleted_tags
            }
            
        except Exception as e:
            self.logger.error(f"重置规则失败: {e}")
            return {"success": False, "error": str(e)}
