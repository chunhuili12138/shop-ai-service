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
            "about": self.base_dir / "about",
            "general": self.base_dir / "general",
        }
        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保所有目录存在"""
        for dir_path in self.intent_dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)

    def sync_all(self, shop_id: int) -> dict:
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
            "about": False,
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
            
            # 同步助手身份 → about目录
            results["about"] = self.sync_about(shop_id)

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

    def sync_about(self, shop_id: int) -> bool:
        """
        同步助手身份信息 → about目录
        内容直接内嵌，不依赖外部文件
        """
        try:
            md_content = """# 店铺智能助手介绍

## 我是谁
我是店铺智能助手，一款专为 DIY 手工店、亲子游乐等体验式门店打造的 AI 运营助手。我帮助店长和员工高效管理店铺日常运营，支持数据查询、操作执行、知识问答和经营分析。

## 支持的查询功能

### 经营数据查询
- 营业额：今日/本月/上月营业额、订单数
- 营收趋势：按日/周/月的营收变化趋势
- 热销套餐：各套餐销量排行、销售额对比

### 顾客管理查询
- 顾客信息：按姓名/手机号搜索顾客
- 消费记录：顾客的购买历史、核销记录
- 钱包余额：顾客储值卡余额、积分

### 套餐管理查询
- 套餐列表：所有在售套餐（单次/周卡/月卡）
- 套餐详情：价格、时长、包含项目

### 库存管理查询
- 库存查询：各物料当前库存数量
- 库存预警：低于安全库存的物料清单

### 退款管理查询
- 退款记录：所有退款申请（待处理/已完成/已拒绝）
- 待审核退款：需要店长处理的退款申请

### 员工管理查询
- 员工列表：在职员工信息
- 绩效统计：员工核销数量、业绩排名
- 排班查询：员工排班表
- 考勤记录：员工打卡记录

### 营销管理查询
- 优惠券：优惠券列表、库存
- 优惠券使用：领取和使用记录
- 评价反馈：顾客评价列表

### 通知管理查询
- 通知消息：已发送的通知列表

## 支持的操作功能

### 退款审批（支持单条和批量）
- 批准退款：确认后批准退款申请
- 拒绝退款：填写理由后拒绝退款申请

### 核销管理（支持单条和批量）
- 核销入座：为顾客核销套餐，开始游玩
- 结束游玩：结束顾客的游玩场次

### 库存管理
- 物料入库：物料到货后入库登记
- 物料出库：领用物料出库登记

### 营销管理
- 发放优惠券：向指定顾客发放优惠券

### 客户服务
- 回复评价：回复顾客的评价反馈

### 通知管理
- 发送通知：向员工或顾客发送通知消息

## 支持的分析功能
- 经营分析：本月经营情况综合分析、多维度数据对比
- 知识问答：店铺规则、营业时间、退款政策等问题解答
- 数据查询：用自然语言查询店铺数据（如"本月卖了多少钱"）

## 使用方式
- 直接用自然语言提问，如"今天营业额多少？"
- 支持多轮对话，可以追问"那昨天呢？"
- 支持省略句，我会结合上下文理解
- 操作类指令如"拒绝刘强东的退款"会弹出确认框

## 我的服务范围
- 仅限当前店铺的数据和信息
- 不涉及其他店铺或外部系统
- 不提供医疗、法律、金融等专业建议
- 不支持删除数据、修改价格、发送短信等操作

## 我的局限
- 我基于店铺数据库回答，实时数据可能有几分钟延迟
- 复杂分析可能需要多步查询，请耐心等待
- 如果我不确定，会如实告知而不是猜测
- 高风险操作（如退款审批）需要人工确认后才能执行
"""
            target_dir = self.intent_dirs["about"]
            target_dir.mkdir(parents=True, exist_ok=True)
            file_path = target_dir / "assistant_identity.md"
            file_path.write_text(md_content, encoding="utf-8")
            print(f"[知识库同步] 助手身份已同步: {file_path}")
            return True
        except Exception as e:
            print(f"[知识库同步] 助手身份同步失败: {str(e)}")
            return False

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
