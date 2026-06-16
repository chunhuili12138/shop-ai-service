"""
定时任务配置
实现知识库定时同步功能
"""

import logging
import schedule
import time
import threading
from datetime import datetime

logger = logging.getLogger(__name__)


def _get_active_shop_ids() -> list[int]:
    """从数据库获取所有活跃店铺 ID"""
    try:
        from app.nl2sql.executor import execute_sql
        results = execute_sql(
            "SELECT DISTINCT id FROM shops WHERE status = 1 AND is_deleted = 0"
        )
        return [row["id"] for row in results]
    except Exception as e:
        logger.error(f"获取活跃店铺列表失败: {e}")
        return []


def sync_packages_job():
    """同步套餐信息定时任务（每小时）"""
    logger.info("执行套餐信息同步...")
    try:
        from app.knowledge.sync import knowledge_sync

        shop_ids = _get_active_shop_ids()
        if not shop_ids:
            logger.warning("无活跃店铺，跳过套餐同步")
            return

        for shop_id in shop_ids:
            try:
                knowledge_sync.sync_packages(shop_id=shop_id, use_api=True)
                logger.info(f"店铺 {shop_id} 套餐信息同步完成")
            except Exception as e:
                logger.error(f"店铺 {shop_id} 套餐同步失败: {str(e)}")

        logger.info("套餐信息同步全部完成")
    except Exception as e:
        logger.error(f"套餐信息同步失败: {str(e)}")


def sync_all_knowledge_job():
    """同步全部知识库定时任务（每天凌晨2点）"""
    logger.info("执行知识库全量同步...")
    try:
        from app.knowledge.sync import knowledge_sync

        shop_ids = _get_active_shop_ids()
        if not shop_ids:
            logger.warning("无活跃店铺，跳过知识库同步")
            return

        for shop_id in shop_ids:
            try:
                knowledge_sync.sync_all(shop_id=shop_id)
                logger.info(f"店铺 {shop_id} 知识库全量同步完成")
            except Exception as e:
                logger.error(f"店铺 {shop_id} 知识库同步失败: {str(e)}")

        logger.info("知识库全量同步全部完成")
    except Exception as e:
        logger.error(f"知识库全量同步失败: {str(e)}")


def sync_schema_job():
    """同步数据库 Schema 到 JSON 文件（每天凌晨3点）"""
    logger.info("执行 Schema 同步...")
    try:
        from scripts.sync_schema import sync_schema
        from app.nl2sql.schema import invalidate_schema_cache

        result = sync_schema()
        table_count = len(result.get("tables", {}))
        invalidate_schema_cache()
        logger.info(f"Schema 同步完成: {table_count} 张表")
    except Exception as e:
        logger.error(f"Schema 同步失败: {str(e)}")


def start_scheduler():
    """
    启动定时任务调度器

    定时任务：
    - 每小时同步套餐信息（从API获取最新数据）
    - 每天凌晨2点同步全部知识库
    """
    schedule.every(1).hours.do(sync_packages_job)
    schedule.every().day.at("02:00").do(sync_all_knowledge_job)
    schedule.every().day.at("03:00").do(sync_schema_job)

    logger.info("定时任务已启动：每小时同步套餐，每天凌晨2点同步知识库，每天凌晨3点同步Schema")

    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(60)

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    return scheduler_thread
