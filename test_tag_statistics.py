#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
标签统计功能测试脚本
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database.database_manager import DatabaseManager
from src.statistics.tag_statistics import TagStatistics
from src.config.settings import Settings


async def test_tag_statistics():
    """测试标签统计功能"""
    try:
        # 初始化配置和数据库
        settings = Settings()
        db_manager = DatabaseManager(settings)
        
        # 初始化数据库
        await db_manager.initialize()
        
        # 创建标签统计管理器
        tag_stats = TagStatistics(db_manager)
        
        print("🧪 开始测试标签统计功能...\n")
        
        # 测试1: 获取所有标签的媒体摘要
        print("📊 测试1: 获取所有标签的媒体摘要")
        summary = await tag_stats.get_all_tags_media_summary(limit=10)
        
        if "error" in summary:
            print(f"❌ 错误: {summary['error']}")
        else:
            print(f"✅ 找到 {summary['total_tags']} 个活跃标签")
            print(f"   总视频: {summary['overall_stats']['total_videos']}")
            print(f"   总图片: {summary['overall_stats']['total_images']}")
            
            if summary['tags_summary']:
                print("   热门标签:")
                for i, tag in enumerate(summary['tags_summary'][:3], 1):
                    print(f"   {i}. {tag['tag_name']}: 🎬{tag['videos']} 📸{tag['images']}")
        
        print()
        
        # 测试2: 获取视频类型的标签分布
        print("🎬 测试2: 获取视频类型的标签分布")
        from src.database.models import MediaType
        video_distribution = await tag_stats.get_media_type_by_tags(MediaType.VIDEO, limit=5)
        
        if "error" in video_distribution:
            print(f"❌ 错误: {video_distribution['error']}")
        else:
            print(f"✅ 总视频数: {video_distribution['total_count']}")
            if video_distribution['tag_distribution']:
                print("   标签分布:")
                for tag_info in video_distribution['tag_distribution'][:3]:
                    print(f"   - {tag_info['tag_name']}: {tag_info['count']} 个 ({tag_info['percentage']:.1f}%)")
        
        print()
        
        # 测试3: 如果有标签，测试获取特定标签的详细统计
        if summary.get('tags_summary'):
            first_tag = summary['tags_summary'][0]['tag_name']
            print(f"🏷️ 测试3: 获取标签 '{first_tag}' 的详细统计")
            
            tag_detail = await tag_stats.get_tag_media_stats(tag_name=first_tag)
            
            if "error" in tag_detail:
                print(f"❌ 错误: {tag_detail['error']}")
            else:
                print(f"✅ 标签: {tag_detail['tag_info']['name']}")
                print(f"   总文件: {tag_detail['total_files']}")
                print(f"   总大小: {tag_detail['total_size_mb']:.1f} MB")
                
                media_stats = tag_detail['media_stats']
                print("   媒体分布:")
                for media_type, stats in media_stats.items():
                    if stats['count'] > 0:
                        print(f"   - {media_type}: {stats['count']} 个 ({stats['size_mb']:.1f} MB)")
        
        print()
        
        # 测试4: 获取热门标签
        print("🔥 测试4: 获取各媒体类型的热门标签")
        top_tags = await tag_stats.get_top_tags_by_media_type(limit=3)
        
        if "error" in top_tags:
            print(f"❌ 错误: {top_tags['error']}")
        else:
            print("✅ 热门标签:")
            for media_type, tags in top_tags['top_tags_by_type'].items():
                if tags:
                    print(f"   {media_type}:")
                    for tag in tags[:2]:  # 只显示前2个
                        print(f"   - {tag['tag_name']}: {tag['media_count']} 个")
        
        print("\n🎉 标签统计功能测试完成!")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 关闭数据库连接
        if 'db_manager' in locals():
            await db_manager.close()


async def main():
    """主函数"""
    print("🚀 标签统计功能测试")
    print("=" * 50)
    
    await test_tag_statistics()


if __name__ == "__main__":
    asyncio.run(main())
