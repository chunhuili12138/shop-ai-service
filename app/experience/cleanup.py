"""
经验池定期清理任务
集成到 APScheduler 定时任务中
"""

from app.experience.pool import get_experience_pool


async def cleanup_experience_pool():
    """
    清理经验池
    - 清理低质量案例
    - 淘汰长时间未使用的案例
    """
    try:
        pool = get_experience_pool()
        
        # 清理低质量案例（质量 < 50 且使用次数 < 2）
        await pool.cleanup_low_quality(min_quality=50, min_usage=2)
        
        # 淘汰过期案例（超过 30 天且使用次数 < 1）
        await pool.cleanup_by_frequency(max_age_days=30, min_usage=1)
        
        print("[ExperiencePool] 定期清理完成")
    except Exception as e:
        print(f"[ExperiencePool] 定期清理失败: {str(e)}")
