"""
知识库同步服务（按意图分组）
从MySQL数据库导出静态数据，按意图分组生成Markdown文档，索引到向量库
支持从API获取最新套餐数据
"""

import os
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, text
from app.config import settings
from app.knowledge.package_client import get_package_client


# 数据库连接
engine = create_engine(settings.MYSQL_URL)


class KnowledgeSync:
    """知识库同步服务（按意图分组）"""

    def __init__(self):
        # 按意图分组的目录结构
        self.base_dir = Path("data/knowledge")
        self.intent_dirs = {
            "package": self.base_dir / "package",
            "hours": self.base_dir / "hours",
            "refund": self.base_dir / "refund",
            "rules": self.base_dir / "rules",
            "general": self.base_dir / "general",
        }
        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保所有目录存在"""
        for dir_path in self.intent_dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)

    def sync_all(self, shop_id: int = 5) -> dict:
        """
        同步所有知识库数据（按意图分组）
        
        Args:
            shop_id: 店铺ID
        
        Returns:
            同步结果统计
        """
        results = {
            "package": False,
            "hours": False,
            "refund": False,
            "rules": False,
            "general": False,
            "timestamp": datetime.now().isoformat(),
        }

        try:
            # 同步套餐信息 → package目录
            results["package"] = self.sync_packages(shop_id)
            
            # 同步营业时间 → hours目录
            results["hours"] = self.sync_hours(shop_id)
            
            # 同步退款政策 → refund目录
            results["refund"] = self.sync_refund(shop_id)
            
            # 同步店铺规则 → rules目录
            results["rules"] = self.sync_rules(shop_id)
            
            # 同步通用问题 → general目录
            results["general"] = self.sync_general(shop_id)
            
            print(f"[知识库同步] 完成: {results}")
            return results
        except Exception as e:
            print(f"[知识库同步] 失败: {str(e)}")
            raise

    def sync_packages(self, shop_id: int, use_api: bool = True) -> bool:
        """
        同步套餐信息 → package目录
        
        Args:
            shop_id: 店铺ID
            use_api: 是否从API获取（True=API，False=数据库）
        """
        try:
            if use_api:
                # 从API获取最新数据
                client = get_package_client()
                packages = client.fetch_packages(shop_id)
                
                if packages:
                    md_content = client.format_packages_to_markdown(packages)
                    
                    file_path = self.intent_dirs["package"] / "packages.md"
                    file_path.write_text(md_content, encoding="utf-8")
                    
                    # 保存缓存时间戳
                    self._save_cache_timestamp(shop_id, "package")
                    
                    print(f"[知识库同步] 套餐信息已从API同步: {file_path}")
                    return True
                else:
                    print(f"[知识库同步] API未返回数据，降级到数据库查询")
                    # 降级到数据库查询
                    return self._sync_packages_from_db(shop_id)
            else:
                return self._sync_packages_from_db(shop_id)
                
        except Exception as e:
            print(f"[知识库同步] API同步失败: {str(e)}，降级到数据库查询")
            return self._sync_packages_from_db(shop_id)

    def _sync_packages_from_db(self, shop_id: int) -> bool:
        """从数据库同步套餐信息"""
        sql = text("""
            SELECT name, type, price, duration_minutes, 
                   max_people_per_session, description
            FROM packages
            WHERE shop_id = :shop_id AND is_active = 1
            ORDER BY id
        """)

        with engine.connect() as conn:
            result = conn.execute(sql, {"shop_id": shop_id})
            rows = result.fetchall()

        if not rows:
            print(f"[知识库同步] 未找到套餐数据: shop_id={shop_id}")
            return False

        # 套餐类型映射（数据库中存储的是大写字符串）
        type_names = {
            "SINGLE": "单次卡",
            "WEEKLY": "周卡",
            "MONTHLY": "月卡",
        }
        
        # 使用次数映射
        usage_count = {
            "SINGLE": "1次",
            "WEEKLY": "7次（每天1次，共7天）",
            "MONTHLY": "30次（每天1次，共30天）",
        }

        md_content = "# 套餐介绍\n\n"
        for row in rows:
            type_name = type_names.get(row.type, row.type or "未知")
            usage = usage_count.get(row.type, "请咨询店员")
            duration = row.duration_minutes or 0
            hours = duration // 60
            minutes = duration % 60
            duration_text = f"{hours}小时{minutes}分钟" if minutes else f"{hours}小时"

            md_content += f"## {row.name}\n\n"
            md_content += f"- **类型**：{type_name}\n"
            md_content += f"- **价格**：¥{row.price:.0f}\n"
            md_content += f"- **使用次数**：{usage}\n"
            md_content += f"- **单次时长**：{duration_text}\n"
            md_content += f"- **每场上限**：{row.max_people_per_session}人\n"
            if row.description:
                md_content += f"- **说明**：{row.description}\n"
            md_content += "\n"

        file_path = self.intent_dirs["package"] / "packages.md"
        file_path.write_text(md_content, encoding="utf-8")
        print(f"[知识库同步] 套餐信息已从数据库同步: {file_path}")
        return True

    def sync_hours(self, shop_id: int) -> bool:
        """同步营业时间 → hours目录"""
        sql = text("""
            SELECT name, address, contact_phone, 
                   open_time, close_time, business_days
            FROM shops
            WHERE id = :shop_id AND is_deleted = 0
        """)

        with engine.connect() as conn:
            result = conn.execute(sql, {"shop_id": shop_id})
            row = result.fetchone()

        if not row:
            print(f"[知识库同步] 未找到店铺信息: shop_id={shop_id}")
            return False

        day_names = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        business_days = row.business_days or "1,2,3,4,5,6,7"
        day_list = [day_names[int(d)] for d in business_days.split(",") if d.isdigit()]
        business_text = "、".join(day_list) if day_list else "每天"

        md_content = f"""# 营业时间

## 店铺名称
{row.name}

## 营业时间
- **营业日**：{business_text}
- **营业时段**：{row.open_time or '09:00'} - {row.close_time or '21:00'}

## 联系方式
- **地址**：{row.address or '未设置'}
- **电话**：{row.contact_phone or '未设置'}
"""

        file_path = self.intent_dirs["hours"] / "hours.md"
        file_path.write_text(md_content, encoding="utf-8")
        print(f"[知识库同步] 营业时间已同步: {file_path}")
        return True

    def sync_refund(self, shop_id: int) -> bool:
        """同步退款政策 → refund目录"""
        sql = text("""
            SELECT question, answer
            FROM shop_faqs
            WHERE shop_id = :shop_id AND category = 'refund' AND is_active = 1
            ORDER BY id
        """)

        with engine.connect() as conn:
            result = conn.execute(sql, {"shop_id": shop_id})
            rows = result.fetchall()

        # 如果没有专门的退款FAQ，使用默认政策
        if not rows:
            md_content = """# 退款政策

## 退款规则
- 购买后7天内未使用可申请全额退款
- 已使用的套餐不支持退款
- 退款金额将原路返回到支付账户

## 退款流程
1. 联系店铺客服说明退款原因
2. 提供订单号和支付凭证
3. 客服审核通过后处理退款
4. 退款将在1-3个工作日内到账

## 注意事项
- 套餐有效期过后自动过期，不支持退款
- 特殊活动套餐可能有不同的退款规则
"""
        else:
            md_content = "# 退款政策\n\n"
            for row in rows:
                md_content += f"## {row.question}\n\n"
                md_content += f"{row.answer}\n\n"

        file_path = self.intent_dirs["refund"] / "refund.md"
        file_path.write_text(md_content, encoding="utf-8")
        print(f"[知识库同步] 退款政策已同步: {file_path}")
        return True

    def sync_rules(self, shop_id: int) -> bool:
        """同步店铺规则 → rules目录"""
        sql = text("""
            SELECT question, answer
            FROM shop_faqs
            WHERE shop_id = :shop_id AND category = 'rules' AND is_active = 1
            ORDER BY id
        """)

        with engine.connect() as conn:
            result = conn.execute(sql, {"shop_id": shop_id})
            rows = result.fetchall()

        # 如果没有专门的规则FAQ，使用默认规则
        if not rows:
            md_content = """# 店铺规则

## 年龄限制
- 适合3-12岁儿童
- 3岁以下儿童需家长全程陪同
- 12岁以上建议选择成人项目

## 安全须知
- 请遵守店内安全规定
- 请勿携带危险物品入场
- 请勿在店内奔跑打闹

## 入场须知
- 请在前台登记后入场
- 请保管好个人物品
- 如有身体不适请立即告知工作人员
"""
        else:
            md_content = "# 店铺规则\n\n"
            for row in rows:
                md_content += f"## {row.question}\n\n"
                md_content += f"{row.answer}\n\n"

        file_path = self.intent_dirs["rules"] / "rules.md"
        file_path.write_text(md_content, encoding="utf-8")
        print(f"[知识库同步] 店铺规则已同步: {file_path}")
        return True

    def sync_general(self, shop_id: int) -> bool:
        """同步通用问题 → general目录"""
        sql = text("""
            SELECT question, answer
            FROM shop_faqs
            WHERE shop_id = :shop_id AND category = 'general' AND is_active = 1
            ORDER BY id
        """)

        with engine.connect() as conn:
            result = conn.execute(sql, {"shop_id": shop_id})
            rows = result.fetchall()

        if not rows:
            print(f"[知识库同步] 未找到通用FAQ: shop_id={shop_id}")
            return False

        md_content = "# 常见问题\n\n"
        for row in rows:
            md_content += f"## {row.question}\n\n"
            md_content += f"{row.answer}\n\n"

        file_path = self.intent_dirs["general"] / "general.md"
        file_path.write_text(md_content, encoding="utf-8")
        print(f"[知识库同步] 通用问题已同步: {file_path}")
        return True

    def _save_cache_timestamp(self, shop_id: int, cache_type: str):
        """保存缓存时间戳"""
        cache_dir = Path("data/cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp_file = cache_dir / f"{shop_id}_{cache_type}_timestamp.txt"
        timestamp_file.write_text(datetime.now().isoformat())
        print(f"[知识库同步] 缓存时间戳已保存: {timestamp_file}")

    def get_cache_age(self, shop_id: int, cache_type: str) -> float:
        """
        获取缓存年龄（小时）
        
        Returns:
            缓存年龄（小时），如果无缓存返回 -1
        """
        cache_dir = Path("data/cache")
        timestamp_file = cache_dir / f"{shop_id}_{cache_type}_timestamp.txt"
        
        if not timestamp_file.exists():
            return -1
        
        try:
            timestamp_str = timestamp_file.read_text().strip()
            timestamp = datetime.fromisoformat(timestamp_str)
            age = (datetime.now() - timestamp).total_seconds() / 3600
            return age
        except Exception:
            return -1


# 全局实例
knowledge_sync = KnowledgeSync()
