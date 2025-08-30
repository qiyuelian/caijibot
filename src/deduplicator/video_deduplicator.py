# -*- coding: utf-8 -*-
"""
视频去重器
基于视频特征进行去重检测
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import json

try:
    import cv2
    import numpy as np
    from moviepy.editor import VideoFileClip
    VIDEO_PROCESSING_AVAILABLE = True
except ImportError:
    VIDEO_PROCESSING_AVAILABLE = False

from ..database.database_manager import DatabaseManager
from ..database.models import Message, DuplicateRecord, MessageStatus, MediaType
from ..utils.logger import LoggerMixin
from sqlalchemy import select, update


class VideoDeduplicator(LoggerMixin):
    """视频去重器"""
    
    def __init__(self, db_manager: DatabaseManager, similarity_threshold: float = 0.85):
        """
        初始化视频去重器
        
        Args:
            db_manager: 数据库管理器
            similarity_threshold: 相似度阈值
        """
        self.db_manager = db_manager
        self.similarity_threshold = similarity_threshold
        
        if not VIDEO_PROCESSING_AVAILABLE:
            self.logger.warning("视频处理库未安装，视频去重功能将受限")
        
        self.logger.info(f"视频去重器初始化完成，相似度阈值: {similarity_threshold}")
    
    def _check_video_processing_available(self) -> bool:
        """检查视频处理库是否可用"""
        if not VIDEO_PROCESSING_AVAILABLE:
            self.logger.error("视频处理库未安装，请安装 opencv-python, moviepy")
            return False
        return True
    
    async def extract_video_features(self, video_path: Path) -> Optional[Dict[str, Any]]:
        """
        提取视频特征
        
        Args:
            video_path: 视频路径
        
        Returns:
            Optional[Dict]: 视频特征
        """
        if not self._check_video_processing_available():
            return None
        
        if not video_path.exists():
            self.logger.warning(f"视频文件不存在: {video_path}")
            return None
        
        try:
            features = {}
            
            # 使用OpenCV获取基本信息
            cap = cv2.VideoCapture(str(video_path))
            
            if not cap.isOpened():
                self.logger.error(f"无法打开视频文件: {video_path}")
                return None
            
            # 基本属性
            features["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            features["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            features["fps"] = cap.get(cv2.CAP_PROP_FPS)
            features["frame_count"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # 计算时长
            if features["fps"] > 0:
                features["duration"] = features["frame_count"] / features["fps"]
            else:
                features["duration"] = 0
            
            # 提取关键帧特征
            frame_features = await self._extract_frame_features(cap)
            features.update(frame_features)
            
            cap.release()
            
            # 使用MoviePy获取额外信息
            try:
                with VideoFileClip(str(video_path)) as clip:
                    features["audio_duration"] = clip.duration
                    features["has_audio"] = clip.audio is not None
                    if clip.audio:
                        features["audio_fps"] = clip.audio.fps
            except Exception as e:
                self.logger.debug(f"MoviePy处理失败: {e}")
                features["has_audio"] = False
            
            self.logger.debug(f"提取视频特征: {video_path.name} -> {len(features)} 个特征")
            return features
            
        except Exception as e:
            self.logger.error(f"提取视频特征失败: {e}")
            return None
    
    async def _extract_frame_features(self, cap) -> Dict[str, Any]:
        """
        提取关键帧特征
        
        Args:
            cap: OpenCV VideoCapture对象
        
        Returns:
            Dict: 帧特征
        """
        try:
            frame_features = {
                "frame_hashes": [],
                "avg_brightness": 0,
                "avg_contrast": 0,
                "color_histogram": []
            }
            
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames == 0:
                return frame_features
            
            # 选择关键帧（开始、中间、结束各几帧）
            key_frame_positions = [
                0,  # 第一帧
                total_frames // 4,  # 1/4处
                total_frames // 2,  # 中间
                total_frames * 3 // 4,  # 3/4处
                total_frames - 1  # 最后一帧
            ]
            
            brightness_values = []
            contrast_values = []
            
            for pos in key_frame_positions:
                cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                ret, frame = cap.read()
                
                if not ret:
                    continue
                
                # 计算帧哈希（简单的平均哈希）
                frame_hash = self._calculate_frame_hash(frame)
                if frame_hash:
                    frame_features["frame_hashes"].append(frame_hash)
                
                # 计算亮度和对比度
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                brightness = np.mean(gray)
                contrast = np.std(gray)
                
                brightness_values.append(brightness)
                contrast_values.append(contrast)
                
                # 计算颜色直方图（只对中间帧）
                if pos == total_frames // 2:
                    hist_b = cv2.calcHist([frame], [0], None, [256], [0, 256])
                    hist_g = cv2.calcHist([frame], [1], None, [256], [0, 256])
                    hist_r = cv2.calcHist([frame], [2], None, [256], [0, 256])
                    
                    # 归一化直方图
                    hist_b = hist_b.flatten() / np.sum(hist_b)
                    hist_g = hist_g.flatten() / np.sum(hist_g)
                    hist_r = hist_r.flatten() / np.sum(hist_r)
                    
                    frame_features["color_histogram"] = {
                        "blue": hist_b.tolist()[:32],  # 只保存前32个bin
                        "green": hist_g.tolist()[:32],
                        "red": hist_r.tolist()[:32]
                    }
            
            # 计算平均值
            if brightness_values:
                frame_features["avg_brightness"] = np.mean(brightness_values)
                frame_features["avg_contrast"] = np.mean(contrast_values)
            
            return frame_features
            
        except Exception as e:
            self.logger.error(f"提取帧特征失败: {e}")
            return {}
    
    def _calculate_frame_hash(self, frame) -> Optional[str]:
        """
        计算帧的简单哈希值
        
        Args:
            frame: 视频帧
        
        Returns:
            Optional[str]: 帧哈希值
        """
        try:
            # 转换为灰度图
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # 缩放到8x8
            resized = cv2.resize(gray, (8, 8))
            
            # 计算平均值
            avg = np.mean(resized)
            
            # 生成哈希
            hash_bits = []
            for i in range(8):
                for j in range(8):
                    hash_bits.append('1' if resized[i, j] > avg else '0')
            
            # 转换为十六进制
            hash_str = hex(int(''.join(hash_bits), 2))[2:].zfill(16)
            return hash_str
            
        except Exception as e:
            self.logger.error(f"计算帧哈希失败: {e}")
            return None
    
    def calculate_video_similarity(self, features1: Dict[str, Any], features2: Dict[str, Any]) -> float:
        """
        计算两个视频的相似度
        
        Args:
            features1: 第一个视频的特征
            features2: 第二个视频的特征
        
        Returns:
            float: 相似度 (0-1)
        """
        try:
            similarity_scores = []
            
            # 1. 基本属性相似度
            if features1.get("width") and features2.get("width"):
                width_sim = 1.0 - abs(features1["width"] - features2["width"]) / max(features1["width"], features2["width"])
                similarity_scores.append(width_sim * 0.1)
            
            if features1.get("height") and features2.get("height"):
                height_sim = 1.0 - abs(features1["height"] - features2["height"]) / max(features1["height"], features2["height"])
                similarity_scores.append(height_sim * 0.1)
            
            # 2. 时长相似度
            if features1.get("duration") and features2.get("duration"):
                duration_diff = abs(features1["duration"] - features2["duration"])
                max_duration = max(features1["duration"], features2["duration"])
                if max_duration > 0:
                    duration_sim = 1.0 - min(duration_diff / max_duration, 1.0)
                    similarity_scores.append(duration_sim * 0.2)
            
            # 3. 帧哈希相似度
            hashes1 = features1.get("frame_hashes", [])
            hashes2 = features2.get("frame_hashes", [])
            
            if hashes1 and hashes2:
                hash_similarities = []
                for h1 in hashes1:
                    for h2 in hashes2:
                        hash_sim = self._calculate_hash_similarity(h1, h2)
                        hash_similarities.append(hash_sim)
                
                if hash_similarities:
                    avg_hash_sim = np.mean(hash_similarities)
                    similarity_scores.append(avg_hash_sim * 0.4)
            
            # 4. 亮度和对比度相似度
            if features1.get("avg_brightness") is not None and features2.get("avg_brightness") is not None:
                brightness_sim = 1.0 - abs(features1["avg_brightness"] - features2["avg_brightness"]) / 255.0
                similarity_scores.append(brightness_sim * 0.1)
            
            if features1.get("avg_contrast") is not None and features2.get("avg_contrast") is not None:
                contrast_sim = 1.0 - abs(features1["avg_contrast"] - features2["avg_contrast"]) / 255.0
                similarity_scores.append(contrast_sim * 0.1)
            
            # 5. 颜色直方图相似度
            hist1 = features1.get("color_histogram")
            hist2 = features2.get("color_histogram")
            
            if hist1 and hist2:
                hist_sim = self._calculate_histogram_similarity(hist1, hist2)
                similarity_scores.append(hist_sim * 0.1)
            
            # 计算加权平均相似度
            if similarity_scores:
                total_similarity = sum(similarity_scores)
                return min(1.0, max(0.0, total_similarity))
            else:
                return 0.0
                
        except Exception as e:
            self.logger.error(f"计算视频相似度失败: {e}")
            return 0.0
    
    def _calculate_hash_similarity(self, hash1: str, hash2: str) -> float:
        """计算两个哈希值的相似度"""
        if not hash1 or not hash2 or len(hash1) != len(hash2):
            return 0.0
        
        try:
            # 计算汉明距离
            hamming_distance = sum(c1 != c2 for c1, c2 in zip(hash1, hash2))
            similarity = 1.0 - (hamming_distance / len(hash1))
            return similarity
        except:
            return 0.0
    
    def _calculate_histogram_similarity(self, hist1: Dict, hist2: Dict) -> float:
        """计算颜色直方图相似度"""
        try:
            similarities = []
            
            for color in ["red", "green", "blue"]:
                if color in hist1 and color in hist2:
                    h1 = np.array(hist1[color])
                    h2 = np.array(hist2[color])
                    
                    # 使用相关系数计算相似度
                    correlation = np.corrcoef(h1, h2)[0, 1]
                    if not np.isnan(correlation):
                        similarities.append(correlation)
            
            return np.mean(similarities) if similarities else 0.0
            
        except Exception as e:
            self.logger.error(f"计算直方图相似度失败: {e}")
            return 0.0
    
    async def update_message_content_hash(self, message_id: int, video_path: Path) -> bool:
        """
        更新消息的内容哈希值（存储视频特征）
        
        Args:
            message_id: 消息ID
            video_path: 视频路径
        
        Returns:
            bool: 是否更新成功
        """
        try:
            # 提取视频特征
            features = await self.extract_video_features(video_path)
            if not features:
                return False
            
            # 将特征序列化为JSON字符串作为内容哈希
            content_hash = json.dumps(features, sort_keys=True)
            
            # 更新数据库
            async with self.db_manager.get_async_session() as session:
                await session.execute(
                    update(Message)
                    .where(Message.id == message_id)
                    .values(content_hash=content_hash)
                )
                await session.commit()
                
                self.logger.debug(f"更新消息 {message_id} 的视频特征")
                return True
                
        except Exception as e:
            self.logger.error(f"更新消息视频特征失败: {e}")
            return False
    
    async def find_similar_videos(self, features: Dict[str, Any], threshold: float = None) -> List[Tuple[Message, float]]:
        """
        查找相似的视频
        
        Args:
            features: 视频特征
            threshold: 相似度阈值
        
        Returns:
            List[Tuple[Message, float]]: 相似的消息和相似度列表
        """
        if threshold is None:
            threshold = self.similarity_threshold
        
        try:
            async with self.db_manager.get_async_session() as session:
                # 获取所有视频消息的内容哈希
                result = await session.execute(
                    select(Message)
                    .where(
                        Message.media_type == MediaType.VIDEO,
                        Message.content_hash.isnot(None),
                        Message.status != MessageStatus.DUPLICATE
                    )
                )
                
                all_videos = result.scalars().all()
                
                # 计算相似度并筛选
                similar_videos = []
                for video_msg in all_videos:
                    try:
                        other_features = json.loads(video_msg.content_hash)
                        similarity = self.calculate_video_similarity(features, other_features)
                        
                        if similarity >= threshold:
                            similar_videos.append((video_msg, similarity))
                    except json.JSONDecodeError:
                        continue
                
                # 按相似度排序
                similar_videos.sort(key=lambda x: x[1], reverse=True)
                return similar_videos
                
        except Exception as e:
            self.logger.error(f"查找相似视频失败: {e}")
            return []
    
    async def detect_video_duplicates(self, message: Message) -> List[Tuple[Message, float]]:
        """
        检测视频的重复和相似文件
        
        Args:
            message: 要检测的消息
        
        Returns:
            List[Tuple[Message, float]]: 重复/相似消息和相似度列表
        """
        if message.media_type != MediaType.VIDEO:
            return []
        
        if not message.content_hash:
            self.logger.debug(f"消息 {message.id} 没有视频特征")
            return []
        
        try:
            # 解析视频特征
            features = json.loads(message.content_hash)
            
            # 查找相似视频
            similar_videos = await self.find_similar_videos(features)
            
            # 排除自己
            duplicate_pairs = [(msg, sim) for msg, sim in similar_videos if msg.id != message.id]
            
            if duplicate_pairs:
                self.logger.info(f"视频消息 {message.id} 发现 {len(duplicate_pairs)} 个相似文件")
            
            return duplicate_pairs
            
        except json.JSONDecodeError:
            self.logger.error(f"消息 {message.id} 的视频特征格式错误")
            return []
        except Exception as e:
            self.logger.error(f"检测视频重复失败: {e}")
            return []
    
    async def process_video_deduplication(self, message: Message) -> Dict[str, Any]:
        """
        处理单个视频消息的去重检测
        
        Args:
            message: 要处理的消息
        
        Returns:
            Dict: 处理结果
        """
        if message.media_type != MediaType.VIDEO:
            return {
                "success": False,
                "reason": "不是视频消息",
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
            
            video_path = Path(message.file_path)
            
            # 如果没有内容哈希值，先计算
            if not message.content_hash:
                success = await self.update_message_content_hash(message.id, video_path)
                if not success:
                    return {
                        "success": False,
                        "reason": "无法提取视频特征",
                        "duplicates_found": 0
                    }
                
                # 重新获取消息以获得更新的特征
                async with self.db_manager.get_async_session() as session:
                    result = await session.execute(
                        select(Message).where(Message.id == message.id)
                    )
                    message = result.scalar_one()
            
            # 检测重复视频
            duplicates = await self.detect_video_duplicates(message)
            
            if not duplicates:
                return {
                    "success": True,
                    "reason": "未发现相似视频",
                    "duplicates_found": 0
                }
            
            return {
                "success": True,
                "reason": f"发现 {len(duplicates)} 个相似视频",
                "duplicates_found": len(duplicates),
                "duplicates_processed": 0  # 暂不自动标记，需要人工确认
            }
            
        except Exception as e:
            self.logger.error(f"处理视频去重失败: {e}")
            return {
                "success": False,
                "reason": f"处理出错: {str(e)}",
                "duplicates_found": 0
            }
