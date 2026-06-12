"""
定时任务配置
实现知识库定时同步功能
"""

import schedule
import time
import threading
from datetime import datetime


def sync_packages_job():
    """同步套餐信息定时任务（每小时）"""
    print(f"[{datetime.now().isoformat()}] 执行套餐信息同步...")
    try:
        from app.knowledge.sync import knowledge_sync
        knowledge_sync.sync_packages(shop_id=5, use_api=True)
        print(f"[{datetime.now().isoformat()}] 套餐信息同步完成")
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] 套餐信息同步失败: {str(e)}")


def sync_all_knowledge_job():
    """同步全部知识库定时任务（每天凌晨2点）"""
    print(f"[{datetime.now().isoformat()}] 执行知识库全量同步...")
    try:
        from app.knowledge.sync import knowledge_sync
        knowledge_sync.sync_all(shop_id=5)
        print(f"[{datetime.now().isoformat()}] 知识库全量同步完成")
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] 知识库全量同步失败: {str(e)}")


def start_scheduler():
    """
    启动定时任务调度器
    
    定时任务：
    - 每小时同步套餐信息（从API获取最新数据）
    - 每天凌晨2点同步全部知识库
    """
    # 设置定时任务：每小时同步套餐
    schedule.every(1).hours.do(sync_packages_job)
    
    # 设置定时任务：每天凌晨2点同步全部
    schedule.every().day.at("02:00").do(sync_all_knowledge_job)
    
    print("⏰ 定时任务已启动：")
    print("   - 每小时同步套餐信息")
    print("   - 每天凌晨2点同步全部知识库")
    
    # 在后台线程中运行调度器
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    return scheduler_thread
