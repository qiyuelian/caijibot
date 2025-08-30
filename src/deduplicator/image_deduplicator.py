# -*- coding: utf-8 -*-
"""
图片去重器
基于感知哈希算法进行图片去重检测
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import numpy as np

try:
    from PIL import Image
    import imagehash
    import cv2
    IMAGING_AVAILABLE = True
except ImportError:
    IMAGING_AVAILABLE = False

from ..database.database_manager import DatabaseManager
from ..database.models import Message, DuplicateRecord, MessageStatus, MediaType
from ..utils.logger import LoggerMixin
from sqlalchemy import select, update


class ImageDeduplicator(LoggerMixin):
    """图片去重器"""
    
    def __init__(self, db_manager: DatabaseManager, similarity_threshold: float = 0.9):
        """
        初始化图片去重器
        
        Args:
            db_manager: 数据库管理器
            similarity_threshold: 相似度阈值
        """
        self.db_manager = db_manager
        self.similarity_threshold = similarity_threshold
        
        if not IMAGING_AVAILABLE:
            self.logger.warning("图像处理库未安装，图片去重功能将受限")
        
        self.logger.info(f"图片去重器初始化完成，相似度阈值: {similarity_threshold}")
    
    def _check_imaging_available(self) -> bool:
        """检查图像处理库是否可用"""
        if not IMAGING_AVAILABLE:
            self.logger.error("图像处理库未安装，请安装 Pillow, imagehash, opencv-python")
            return False
        return True
    
    async def calculate_perceptual_hash(self, image_path: Path, hash_type: str = "phash") -> Optional[str]:
        """
        计算图片的感知哈希值
        
        Args:
            image_path: 图片路径
            hash_type: 哈希类型 (phash, ahash, dhash, whash)
        
        Returns:
            Optional[str]: 感知哈希值
        """
        if not self._check_imaging_available():
            return None
        
        if not image_path.exists():
            self.logger.warning(f"图片文件不存在: {image_path}")
            return None
        
        try:
            # 打开图片
            with Image.open(image_path) as img:
                # 转换为RGB模式
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 计算感知哈希
                if hash_type == "phash":
                    hash_value = imagehash.phash(img)
                elif hash_type == "ahash":
                    hash_value = imagehash.average_hash(img)
                elif hash_type == "dhash":
                    hash_value = imagehash.dhash(img)
                elif hash_type == "whash":
                    hash_value = imagehash.whash(img)
                else:
                    hash_value = imagehash.phash(img)  # 默认使用phash
                
                hash_str = str(hash_value)
                self.logger.debug(f"计算图片感知哈希: {image_path.name} -> {hash_str}")
                return hash_str
                
        except Exception as e:
            self.logger.error(f"计算图片感知哈希失败: {e}")
            return None
    
    def calculate_hash_similarity(self, hash1: str, hash2: str) -> float:
        """
        计算两个哈希值的相似度
        
        Args:
            hash1: 第一个哈希值
            hash2: 第二个哈希值
        
        Returns:
            float: 相似度 (0-1)
        """
        if not hash1 or not hash2:
            return 0.0
        
        try:
            # 将哈希字符串转换为imagehash对象
            h1 = imagehash.hex_to_hash(hash1)
            h2 = imagehash.hex_to_hash(hash2)
            
            # 计算汉明距离
            hamming_distance = h1 - h2
            
            # 转换为相似度 (0-1)
            # 假设哈希长度为64位，最大汉明距离为64
            max_distance = len(hash1) * 4  # 每个十六进制字符代表4位
            similarity = 1.0 - (hamming_distance / max_distance)
            
            return max(0.0, min(1.0, similarity))
            
        except Exception as e:
            self.logger.error(f"计算哈希相似度失败: {e}")
            return 0.0
    
    async def extract_image_features(self, image_path: Path) -> Optional[Dict[str, Any]]:
        """
        提取图片特征
        
        Args:
            image_path: 图片路径
        
        Returns:
            Optional[Dict]: 图片特征
        """
        if not self._check_imaging_available():
            return None
        
        try:
            with Image.open(image_path) as img:
                # 基本信息
                features = {
                    "width": img.width,
                    "height": img.height,
                    "mode": img.mode,
                    "format": img.format,
                    "size_ratio": img.width / img.height if img.height > 0 else 0
                }
                
                # 计算多种感知哈希
                features["phash"] = str(imagehash.phash(img))
                features["ahash"] = str(imagehash.average_hash(img))
                features["dhash"] = str(imagehash.dhash(img))
                
                # 颜色直方图特征
                if img.mode == 'RGB':
                    hist_r = img.histogram()[0:256]
                    hist_g = img.histogram()[256:512]
                    hist_b = img.histogram()[512:768]
                    
                    # 计算主要颜色分布
                    total_pixels = img.width * img.height
                    features["red_ratio"] = sum(hist_r) / total_pixels
                    features["green_ratio"] = sum(hist_g) / total_pixels
                    features["blue_ratio"] = sum(hist_b) / total_pixels
                
                return features
                
        except Exception as e:
            self.logger.error(f"提取图片特征失败: {e}")
            return None
    
    async def update_message_content_hash(self, message_id: int, image_path: Path) -> bool:
        """
        更新消息的内容哈希值
        
        Args:
            message_id: 消息ID
            image_path: 图片路径
        
        Returns:
            bool: 是否更新成功
        """
        try:
            # 计算感知哈希
            content_hash = await self.calculate_perceptual_hash(image_path)
            if not content_hash:
                return False
            
            # 更新数据库
            async with self.db_manager.get_async_session() as session:
                await session.execute(
                    update(Message)
                    .where(Message.id == message_id)
                    .values(content_hash=content_hash)
                )
                await session.commit()
                
                self.logger.debug(f"更新消息 {message_id} 的内容哈希: {content_hash}")
                return True
                
        except Exception as e:
            self.logger.error(f"更新消息内容哈希失败: {e}")
            return False
    
    async def find_similar_images(self, content_hash: str, threshold: float = None) -> List[Message]:
        """
        查找相似的图片
        
        Args:
            content_hash: 内容哈希值
            threshold: 相似度阈值
        
        Returns:
            List[Message]: 相似的消息列表
        """
        if threshold is None:
            threshold = self.similarity_threshold
        
        try:
            async with self.db_manager.get_async_session() as session:
                # 获取所有图片消息的内容哈希
                result = await session.execute(
                    select(Message)
                    .where(
                        Message.media_type == MediaType.IMAGE,
                        Message.content_hash.isnot(None),
                        Message.status != MessageStatus.DUPLICATE
                    )
                )
                
                all_images = result.scalars().all()
                
                # 计算相似度并筛选
                similar_images = []
                for img_msg in all_images:
                    if img_msg.content_hash == content_hash:
                        continue  # 跳过相同的哈希
                    
                    similarity = self.calculate_hash_similarity(content_hash, img_msg.content_hash)
                    if similarity >= threshold:
                        similar_images.append(img_msg)
                
                return similar_images
                
        except Exception as e:
            self.logger.error(f"查找相似图片失败: {e}")
            return []
    
    async def detect_image_duplicates(self, message: Message) -> List[Tuple[Message, float]]:
        """
        检测图片的重复和相似文件
        
        Args:
            message: 要检测的消息
        
        Returns:
            List[Tuple[Message, float]]: 重复/相似消息和相似度列表
        """
        if message.media_type != MediaType.IMAGE:
            return []
        
        if not message.content_hash:
            self.logger.debug(f"消息 {message.id} 没有内容哈希值")
            return []
        
        try:
            # 查找相似图片
            similar_images = await self.find_similar_images(message.content_hash)
            
            # 计算相似度
            duplicate_pairs = []
            for similar_msg in similar_images:
                similarity = self.calculate_hash_similarity(
                    message.content_hash, 
                    similar_msg.content_hash
                )
                duplicate_pairs.append((similar_msg, similarity))
            
            # 按相似度排序
            duplicate_pairs.sort(key=lambda x: x[1], reverse=True)
            
            if duplicate_pairs:
                self.logger.info(f"图片消息 {message.id} 发现 {len(duplicate_pairs)} 个相似文件")
            
            return duplicate_pairs
            
        except Exception as e:
            self.logger.error(f"检测图片重复失败: {e}")
            return []
    
    async def mark_image_as_duplicate(
        self, 
        original_message: Message, 
        duplicate_message: Message,
        similarity_score: float,
        action: str = "keep_original"
    ) -> bool:
        """
        标记图片消息为重复
        
        Args:
            original_message: 原始消息
            duplicate_message: 重复消息
            similarity_score: 相似度分数
            action: 处理动作
        
        Returns:
            bool: 是否标记成功
        """
        try:
            async with self.db_manager.get_async_session() as session:
                # 标记重复消息状态
                await session.execute(
                    update(Message)
                    .where(Message.id == duplicate_message.id)
                    .values(
                        status=MessageStatus.DUPLICATE,
                        is_duplicate=True,
                        original_message_id=original_message.id
                    )
                )
                
                # 创建去重记录
                duplicate_record = DuplicateRecord(
                    original_message_id=original_message.id,
                    duplicate_message_id=duplicate_message.id,
                    similarity_score=similarity_score,
                    similarity_type="image_hash",
                    action_taken=action,
                    reason=f"图片感知哈希相似度: {similarity_score:.3f}"
                )
                
                session.add(duplicate_record)
                await session.commit()
                
                self.logger.info(
                    f"标记重复图片: 原始={original_message.id}, 重复={duplicate_message.id}, "
                    f"相似度={similarity_score:.3f}"
                )
                
                return True
                
        except Exception as e:
            self.logger.error(f"标记重复图片失败: {e}")
            return False
    
    async def process_image_deduplication(self, message: Message) -> Dict[str, Any]:
        """
        处理单个图片消息的去重检测
        
        Args:
            message: 要处理的消息
        
        Returns:
            Dict: 处理结果
        """
        if message.media_type != MediaType.IMAGE:
            return {
                "success": False,
                "reason": "不是图片消息",
                "duplicates_found": 0
            }
        
        try:
            # 如果消息没有文件路径，跳过
            if not message.file_path:
                return {
                    "success": False,
                    "reason": "消息没有文件路径",
                    "duplicates_found": 0
                }
            
            image_path = Path(message.file_path)
            
            # 如果没有内容哈希值，先计算
            if not message.content_hash:
                success = await self.update_message_content_hash(message.id, image_path)
                if not success:
                    return {
                        "success": False,
                        "reason": "无法计算图片内容哈希值",
                        "duplicates_found": 0
                    }
                
                # 重新获取消息以获得更新的哈希值
                async with self.db_manager.get_async_session() as session:
                    result = await session.execute(
                        select(Message).where(Message.id == message.id)
                    )
                    message = result.scalar_one()
            
            # 检测重复图片
            duplicates = await self.detect_image_duplicates(message)
            
            if not duplicates:
                return {
                    "success": True,
                    "reason": "未发现相似图片",
                    "duplicates_found": 0
                }
            
            # 处理重复图片
            processed_count = 0
            for duplicate_msg, similarity in duplicates:
                # 选择保留策略：保留最早的文件
                if message.created_at < duplicate_msg.created_at:
                    # 当前消息更早，标记duplicate_msg为重复
                    success = await self.mark_image_as_duplicate(
                        message, duplicate_msg, similarity, "keep_original"
                    )
                else:
                    # duplicate_msg更早，标记当前消息为重复
                    success = await self.mark_image_as_duplicate(
                        duplicate_msg, message, similarity, "keep_original"
                    )
                
                if success:
                    processed_count += 1
            
            return {
                "success": True,
                "reason": f"处理了 {processed_count} 个相似图片",
                "duplicates_found": len(duplicates),
                "duplicates_processed": processed_count
            }
            
        except Exception as e:
            self.logger.error(f"处理图片去重失败: {e}")
            return {
                "success": False,
                "reason": f"处理出错: {str(e)}",
                "duplicates_found": 0
            }
    
    async def batch_process_image_deduplication(self, limit: int = 50) -> Dict[str, Any]:
        """
        批量处理图片去重检测
        
        Args:
            limit: 处理数量限制
        
        Returns:
            Dict: 批量处理结果
        """
        try:
            # 获取需要去重检测的图片消息
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(
                    select(Message)
                    .where(
                        Message.media_type == MediaType.IMAGE,
                        Message.status == MessageStatus.COMPLETED,
                        Message.file_path.isnot(None),
                        Message.is_duplicate == False
                    )
                    .limit(limit)
                    .order_by(Message.created_at.asc())
                )
                
                messages = result.scalars().all()
            
            if not messages:
                return {
                    "success": True,
                    "processed": 0,
                    "duplicates_found": 0,
                    "message": "没有需要处理的图片消息"
                }
            
            # 批量处理
            total_processed = 0
            total_duplicates = 0
            errors = []
            
            for message in messages:
                try:
                    result = await self.process_image_deduplication(message)
                    total_processed += 1
                    
                    if result["success"]:
                        total_duplicates += result["duplicates_found"]
                    else:
                        errors.append(f"消息 {message.id}: {result['reason']}")
                    
                    # 避免过度占用资源
                    await asyncio.sleep(0.2)
                    
                except Exception as e:
                    errors.append(f"消息 {message.id}: {str(e)}")
            
            self.logger.info(
                f"批量图片去重完成: 处理 {total_processed} 条消息, "
                f"发现 {total_duplicates} 个相似图片, "
                f"错误 {len(errors)} 个"
            )
            
            return {
                "success": True,
                "processed": total_processed,
                "duplicates_found": total_duplicates,
                "errors": errors[:10]  # 只返回前10个错误
            }
            
        except Exception as e:
            self.logger.error(f"批量图片去重处理失败: {e}")
            return {
                "success": False,
                "processed": 0,
                "duplicates_found": 0,
                "error": str(e)
            }
