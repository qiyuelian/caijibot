# -*- coding: utf-8 -*-
"""
默认分类规则
提供一些常用的分类规则模板
"""

from typing import List, Dict, Any
from .rule_engine import RuleType, TargetField


class DefaultRules:
    """默认分类规则集合"""
    
    @staticmethod
    def get_default_rules() -> List[Dict[str, Any]]:
        """
        获取默认分类规则列表
        
        Returns:
            List[Dict]: 默认规则配置列表
        """
        return [
            # 视频分类规则
            {
                "name": "视频文件扩展名",
                "description": "根据视频文件扩展名进行分类",
                "rule_type": RuleType.FILE_EXT,
                "rule_pattern": "mp4,avi,mkv,mov,wmv,flv,webm,m4v",
                "target_field": TargetField.FILENAME,
                "tag_name": "视频",
                "tag_description": "视频文件",
                "tag_color": "#FF6B6B",
                "priority": 10
            },
            
            # 图片分类规则
            {
                "name": "图片文件扩展名",
                "description": "根据图片文件扩展名进行分类",
                "rule_type": RuleType.FILE_EXT,
                "rule_pattern": "jpg,jpeg,png,gif,bmp,webp,svg,tiff",
                "target_field": TargetField.FILENAME,
                "tag_name": "图片",
                "tag_description": "图片文件",
                "tag_color": "#4ECDC4",
                "priority": 10
            },
            
            # 音频分类规则
            {
                "name": "音频文件扩展名",
                "description": "根据音频文件扩展名进行分类",
                "rule_type": RuleType.FILE_EXT,
                "rule_pattern": "mp3,wav,flac,aac,ogg,wma,m4a",
                "target_field": TargetField.FILENAME,
                "tag_name": "音频",
                "tag_description": "音频文件",
                "tag_color": "#45B7D1",
                "priority": 10
            },
            
            # 文档分类规则
            {
                "name": "文档文件扩展名",
                "description": "根据文档文件扩展名进行分类",
                "rule_type": RuleType.FILE_EXT,
                "rule_pattern": "pdf,doc,docx,txt,rtf,xls,xlsx,ppt,pptx",
                "target_field": TargetField.FILENAME,
                "tag_name": "文档",
                "tag_description": "文档文件",
                "tag_color": "#96CEB4",
                "priority": 10
            },
            
            # 压缩包分类规则
            {
                "name": "压缩包文件扩展名",
                "description": "根据压缩包文件扩展名进行分类",
                "rule_type": RuleType.FILE_EXT,
                "rule_pattern": "zip,rar,7z,tar,gz,bz2,xz",
                "target_field": TargetField.FILENAME,
                "tag_name": "压缩包",
                "tag_description": "压缩包文件",
                "tag_color": "#FFEAA7",
                "priority": 10
            },
            
            # 大文件分类规则
            {
                "name": "大文件",
                "description": "大于100MB的文件",
                "rule_type": RuleType.FILE_SIZE,
                "rule_pattern": ">100MB",
                "target_field": TargetField.FILENAME,
                "tag_name": "大文件",
                "tag_description": "大于100MB的文件",
                "tag_color": "#DDA0DD",
                "priority": 5
            },
            
            # 小文件分类规则
            {
                "name": "小文件",
                "description": "小于1MB的文件",
                "rule_type": RuleType.FILE_SIZE,
                "rule_pattern": "<1MB",
                "target_field": TargetField.FILENAME,
                "tag_name": "小文件",
                "tag_description": "小于1MB的文件",
                "tag_color": "#98D8C8",
                "priority": 5
            },
            
            # 内容类型分类规则
            {
                "name": "视频内容类型",
                "description": "根据媒体类型识别视频",
                "rule_type": RuleType.CONTENT_TYPE,
                "rule_pattern": "video",
                "target_field": TargetField.FILENAME,
                "tag_name": "视频内容",
                "tag_description": "视频媒体内容",
                "tag_color": "#F7DC6F",
                "priority": 8
            },
            
            {
                "name": "图片内容类型",
                "description": "根据媒体类型识别图片",
                "rule_type": RuleType.CONTENT_TYPE,
                "rule_pattern": "image",
                "target_field": TargetField.FILENAME,
                "tag_name": "图片内容",
                "tag_description": "图片媒体内容",
                "tag_color": "#BB8FCE",
                "priority": 8
            },
            
            # 关键词分类规则示例
            {
                "name": "娱乐内容",
                "description": "包含娱乐相关关键词的内容",
                "rule_type": RuleType.KEYWORD,
                "rule_pattern": "电影,电视剧,综艺,娱乐,明星,演员,导演",
                "target_field": TargetField.BOTH,
                "tag_name": "娱乐",
                "tag_description": "娱乐相关内容",
                "tag_color": "#85C1E9",
                "priority": 7
            },
            
            {
                "name": "教育内容",
                "description": "包含教育相关关键词的内容",
                "rule_type": RuleType.KEYWORD,
                "rule_pattern": "教程,学习,教育,课程,培训,知识,技能",
                "target_field": TargetField.BOTH,
                "tag_name": "教育",
                "tag_description": "教育学习内容",
                "tag_color": "#F8C471",
                "priority": 7
            },
            
            {
                "name": "科技内容",
                "description": "包含科技相关关键词的内容",
                "rule_type": RuleType.KEYWORD,
                "rule_pattern": "科技,技术,编程,软件,硬件,AI,人工智能,机器学习",
                "target_field": TargetField.BOTH,
                "tag_name": "科技",
                "tag_description": "科技技术内容",
                "tag_color": "#82E0AA",
                "priority": 7
            },
            
            {
                "name": "游戏内容",
                "description": "包含游戏相关关键词的内容",
                "rule_type": RuleType.KEYWORD,
                "rule_pattern": "游戏,攻略,解说,直播,电竞,手游,网游",
                "target_field": TargetField.BOTH,
                "tag_name": "游戏",
                "tag_description": "游戏相关内容",
                "tag_color": "#F1948A",
                "priority": 7
            },
            
            {
                "name": "音乐内容",
                "description": "包含音乐相关关键词的内容",
                "rule_type": RuleType.KEYWORD,
                "rule_pattern": "音乐,歌曲,专辑,歌手,乐队,演唱会,MV",
                "target_field": TargetField.BOTH,
                "tag_name": "音乐",
                "tag_description": "音乐相关内容",
                "tag_color": "#85C1E9",
                "priority": 7
            },
            
            # 正则表达式规则示例
            {
                "name": "日期格式文件",
                "description": "文件名包含日期格式的文件",
                "rule_type": RuleType.REGEX,
                "rule_pattern": r"\d{4}[-_]\d{2}[-_]\d{2}",
                "target_field": TargetField.FILENAME,
                "tag_name": "日期文件",
                "tag_description": "文件名包含日期的文件",
                "tag_color": "#D7BDE2",
                "priority": 6
            },
            
            {
                "name": "版本号文件",
                "description": "文件名包含版本号的文件",
                "rule_type": RuleType.REGEX,
                "rule_pattern": r"v?\d+\.\d+(\.\d+)?",
                "target_field": TargetField.FILENAME,
                "tag_name": "版本文件",
                "tag_description": "包含版本号的文件",
                "tag_color": "#AED6F1",
                "priority": 6
            }
        ]
    
    @staticmethod
    def get_basic_rules() -> List[Dict[str, Any]]:
        """
        获取基础分类规则（只包含文件类型分类）
        
        Returns:
            List[Dict]: 基础规则配置列表
        """
        all_rules = DefaultRules.get_default_rules()
        # 只返回文件扩展名和内容类型的规则
        basic_rules = []
        for rule in all_rules:
            if rule["rule_type"] in [RuleType.FILE_EXT, RuleType.CONTENT_TYPE]:
                basic_rules.append(rule)
        return basic_rules
    
    @staticmethod
    def get_content_rules() -> List[Dict[str, Any]]:
        """
        获取内容分类规则（关键词和正则表达式）
        
        Returns:
            List[Dict]: 内容规则配置列表
        """
        all_rules = DefaultRules.get_default_rules()
        # 只返回关键词和正则表达式规则
        content_rules = []
        for rule in all_rules:
            if rule["rule_type"] in [RuleType.KEYWORD, RuleType.REGEX]:
                content_rules.append(rule)
        return content_rules
    
    @staticmethod
    def get_size_rules() -> List[Dict[str, Any]]:
        """
        获取文件大小分类规则
        
        Returns:
            List[Dict]: 大小规则配置列表
        """
        all_rules = DefaultRules.get_default_rules()
        # 只返回文件大小规则
        size_rules = []
        for rule in all_rules:
            if rule["rule_type"] == RuleType.FILE_SIZE:
                size_rules.append(rule)
        return size_rules
