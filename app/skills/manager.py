"""
Skills 管理器
管理预设 Skills，匹配用户查询并返回执行步骤
"""

import re
from typing import List, Dict, Optional, Tuple
from app.skills.models import Skill, SkillStep


class SkillManager:
    """
    Skills 管理器
    
    功能：
    1. 管理预设 Skills
    2. 匹配用户查询
    3. 返回最佳匹配的 Skill
    """
    
    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._load_default_skills()
    
    def _load_default_skills(self):
        """加载默认 Skills"""
        
        # ========== 经营分析类 ==========
        
        # Skill 1: 本月经营情况分析
        self.register(Skill(
            id="monthly_business_analysis",
            name="本月经营情况分析",
            description="分析本月的整体经营情况，包括营收、顾客、支出等",
            keywords=["本月", "经营", "情况", "分析", "月度", "这个月"],
            patterns=[
                r"(本月|这个月|月度).*?(经营|情况|分析|报告)",
                r"(经营|情况).*?(分析|报告|总结)",
                r"月.*?(报|经营|分析)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询本月营收数据",
                    description="查询本月营业额、订单数、热销套餐",
                    query="SELECT COALESCE(SUM(paid_amount), 0) as total_revenue, COUNT(*) as order_count FROM purchases WHERE shop_id = :shop_id AND MONTH(created_at) = MONTH(CURDATE()) AND YEAR(created_at) = YEAR(CURDATE()) AND status = 1",
                    is_critical=True,
                ),
                SkillStep(
                    step=2,
                    agent="nl2sql",
                    task="查询本月顾客数据",
                    description="查询本月新顾客数和活跃顾客数",
                    query="SELECT COUNT(DISTINCT CASE WHEN MONTH(c.created_at) = MONTH(CURDATE()) AND c.is_deleted = 0 THEN c.id END) as new_customers, COUNT(DISTINCT p.customer_id) as active_customers FROM customers c LEFT JOIN purchases p ON c.id = p.customer_id AND p.shop_id = :shop_id AND MONTH(p.created_at) = MONTH(CURDATE()) AND YEAR(p.created_at) = YEAR(CURDATE()) AND p.is_deleted = 0 WHERE c.shop_id = :shop_id AND c.is_deleted = 0",
                    is_critical=True,
                ),
                SkillStep(
                    step=3,
                    agent="nl2sql",
                    task="查询本月支出数据",
                    description="查询本月各类支出汇总",
                    query="SELECT COALESCE(SUM(amount), 0) as total_expense FROM expenses WHERE shop_id = :shop_id AND MONTH(expense_date) = MONTH(CURDATE()) AND YEAR(expense_date) = YEAR(CURDATE())",
                    is_critical=True,
                ),
                SkillStep(
                    step=4,
                    agent="llm",
                    task="汇总分析并给出建议",
                    description="基于以上数据进行分析并给出经营建议",
                    depends_on=[1, 2, 3],
                    is_critical=True,
                ),
            ],
            priority=10,
        ))
        
        # Skill 2: 今日经营概况
        self.register(Skill(
            id="daily_business_summary",
            name="今日经营概况",
            description="查看今天的经营数据概况",
            keywords=["今天", "今日", "日报", "当天"],
            patterns=[
                r"(今天|今日|当天).*?(经营|情况|数据|概况|营业额)",
                r"今.*?(报|经营|数据)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询今日销售数据",
                    description="查询今日营业额、订单数",
                    query="SELECT COALESCE(SUM(paid_amount), 0) as today_revenue, COUNT(*) as today_orders FROM purchases WHERE shop_id = :shop_id AND DATE(created_at) = CURDATE() AND status = 1",
                    is_critical=True,
                ),
                SkillStep(
                    step=2,
                    agent="nl2sql",
                    task="查询今日核销数据",
                    description="查询今日核销次数",
                    query="SELECT COUNT(*) as today_checkins FROM game_sessions WHERE shop_id = :shop_id AND DATE(start_time) = CURDATE() AND status = 2",
                    is_critical=True,
                ),
                SkillStep(
                    step=3,
                    agent="llm",
                    task="汇总今日概况",
                    description="汇总今日经营数据",
                    depends_on=[1, 2],
                    is_critical=True,
                ),
            ],
            priority=9,
        ))
        
        # Skill 3: 顾客消费分析
        self.register(Skill(
            id="customer_consumption_analysis",
            name="顾客消费分析",
            description="分析顾客的消费情况",
            keywords=["顾客", "消费", "会员", "客户"],
            patterns=[
                r"(顾客|客户|会员).*?(消费|购买|充值|活跃)",
                r"(消费|购买).*?(顾客|客户|会员)",
                r"顾客.*?(分析|统计|查询)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询顾客消费统计",
                    description="查询顾客消费金额、次数统计",
                    query="SELECT c.nickname, COALESCE(SUM(p.paid_amount), 0) as total_spent, COUNT(p.id) as purchase_count FROM customers c LEFT JOIN purchases p ON c.id = p.customer_id AND p.shop_id = :shop_id AND p.status = 1 WHERE c.shop_id = :shop_id GROUP BY c.id, c.nickname ORDER BY total_spent DESC LIMIT 20",
                    is_critical=True,
                ),
                SkillStep(
                    step=2,
                    agent="llm",
                    task="分析顾客消费情况",
                    description="分析顾客消费数据，给出运营建议",
                    depends_on=[1],
                    is_critical=True,
                ),
            ],
            priority=8,
        ))
        
        # Skill 4: 库存查询
        self.register(Skill(
            id="inventory_query",
            name="库存查询",
            description="查询当前库存状态",
            keywords=["库存", "物料", "货物", "存货", "缺货"],
            patterns=[
                r"(库存|物料|货物).*?(查询|查看|状态|预警|不足|缺)",
                r"(查询|查看).*?(库存|物料)",
                r"缺.*?(货|库存|物料)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询库存状态",
                    description="查询当前库存和预警",
                    query="SELECT m.name, m.unit, COALESCE(i.quantity, 0) as current_stock, m.min_stock FROM materials m LEFT JOIN inventory i ON m.id = i.material_id WHERE m.shop_id = :shop_id ORDER BY current_stock ASC",
                    is_critical=True,
                ),
                SkillStep(
                    step=2,
                    agent="llm",
                    task="分析库存情况",
                    description="分析库存状态，给出补货建议",
                    depends_on=[1],
                    is_critical=False,
                ),
            ],
            priority=7,
        ))
        
        # Skill 5: 套餐查询
        self.register(Skill(
            id="package_query",
            name="套餐查询",
            description="查询店铺套餐信息",
            keywords=["套餐", "服务", "项目", "价格", "收费"],
            patterns=[
                r"(套餐|服务|项目).*?(查询|查看|有哪些|价格|收费)",
                r"(查询|查看).*?(套餐|服务|项目)",
                r"(价格|收费|多少钱).*?(套餐|服务|项目)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询套餐列表",
                    description="查询所有套餐信息",
                    query="SELECT name, type, duration_minutes, price, original_price, is_active FROM packages WHERE shop_id = :shop_id ORDER BY price ASC",
                    is_critical=True,
                ),
            ],
            priority=6,
        ))
        
        # Skill 6: 员工查询
        self.register(Skill(
            id="staff_query",
            name="员工查询",
            description="查询员工信息",
            keywords=["员工", "服务员", "导玩", "工作人员", "店员"],
            patterns=[
                r"(员工|服务员|导玩|工作人员|店员).*?(查询|查看|有哪些|名单)",
                r"(查询|查看).*?(员工|服务员|导玩)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询员工列表",
                    description="查询所有员工信息",
                    query="SELECT s.name, s.phone, s.employment_type, s.status FROM staff s JOIN staff_shops ss ON s.id = ss.staff_id WHERE ss.shop_id = :shop_id AND s.status = 1",
                    is_critical=True,
                ),
            ],
            priority=5,
        ))
        
        # Skill 7: 收支查询
        self.register(Skill(
            id="revenue_expense_query",
            name="收支查询",
            description="查询收入和支出情况",
            keywords=["收入", "支出", "收支", "利润", "盈亏", "赚", "花"],
            patterns=[
                r"(收入|支出|收支|利润|盈亏).*?(查询|查看|多少|统计)",
                r"(查询|查看).*?(收入|支出|收支|利润)",
                r"(赚|花|利润).*?(多少|查询)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询收入数据",
                    description="查询本月收入",
                    query="SELECT COALESCE(SUM(amount), 0) as total_revenue FROM revenue_records WHERE shop_id = :shop_id AND MONTH(created_at) = MONTH(CURDATE())",
                    is_critical=True,
                ),
                SkillStep(
                    step=2,
                    agent="nl2sql",
                    task="查询支出数据",
                    description="查询本月支出",
                    query="SELECT COALESCE(SUM(amount), 0) as total_expense FROM expenses WHERE shop_id = :shop_id AND MONTH(expense_date) = MONTH(CURDATE())",
                    is_critical=True,
                ),
                SkillStep(
                    step=3,
                    agent="llm",
                    task="计算利润并分析",
                    description="计算净利润并给出分析",
                    depends_on=[1, 2],
                    is_critical=True,
                ),
            ],
            priority=7,
        ))
        
        # Skill 8: 排班查询
        self.register(Skill(
            id="schedule_query",
            name="排班查询",
            description="查询员工排班信息",
            keywords=["排班", "班次", "值班", "上班"],
            patterns=[
                r"(排班|班次|值班|上班).*?(查询|查看|今天|明天|本周)",
                r"(查询|查看).*?(排班|班次|值班)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询排班信息",
                    description="查询员工排班",
                    query="SELECT s.name, ss.schedule_date, ss.start_time, ss.end_time FROM staff_schedules ss JOIN staff s ON ss.staff_id = s.id WHERE ss.shop_id = :shop_id AND ss.schedule_date >= CURDATE() ORDER BY ss.schedule_date, ss.start_time",
                    is_critical=True,
                ),
            ],
            priority=5,
        ))
        
        # Skill 9: 优惠券查询
        self.register(Skill(
            id="coupon_query",
            name="优惠券查询",
            description="查询优惠券信息",
            keywords=["优惠券", "券", "优惠", "折扣"],
            patterns=[
                r"(优惠券|券|优惠|折扣).*?(查询|查看|有哪些|发放|使用)",
                r"(查询|查看).*?(优惠券|券)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询优惠券信息",
                    description="查询优惠券列表和使用情况",
                    query="SELECT name, type, value, total_stock, remain_stock, is_active FROM coupons WHERE shop_id = :shop_id ORDER BY created_at DESC",
                    is_critical=True,
                ),
            ],
            priority=5,
        ))
        
        # Skill 10: 评价查询
        self.register(Skill(
            id="feedback_query",
            name="评价查询",
            description="查询顾客评价",
            keywords=["评价", "反馈", "评分", "满意度", "投诉"],
            patterns=[
                r"(评价|反馈|评分|满意度|投诉).*?(查询|查看|有哪些|最近)",
                r"(查询|查看).*?(评价|反馈|评分)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询评价信息",
                    description="查询顾客评价",
                    query="SELECT f.rating, f.content, f.feedback_type, c.nickname, f.created_at FROM feedbacks f LEFT JOIN customers c ON f.customer_id = c.id WHERE f.shop_id = :shop_id ORDER BY f.created_at DESC LIMIT 20",
                    is_critical=True,
                ),
                SkillStep(
                    step=2,
                    agent="llm",
                    task="分析评价情况",
                    description="分析评价数据，给出改进建议",
                    depends_on=[1],
                    is_critical=False,
                ),
            ],
            priority=5,
        ))
        
        # Skill 11: 顾客信息查询
        self.register(Skill(
            id="customer_info_query",
            name="顾客信息查询",
            description="查询顾客基本信息",
            keywords=["顾客", "客户", "会员", "查", "查询", "信息"],
            patterns=[
                r"(查|查询|查看|找).*?(顾客|客户|会员).*?(信息|详情|资料)",
                r"(顾客|客户|会员).*?(查|查询|查看)",
                r"(手机|电话|联系方式).*?(查|查询)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询顾客信息",
                    description="查询顾客基本信息和余额",
                    query="SELECT c.id, c.nickname, c.phone, c.gender, c.source, c.tags, c.created_at, COALESCE(w.balance, 0) as balance FROM customers c LEFT JOIN customer_wallets w ON c.id = w.customer_id WHERE c.shop_id = :shop_id AND c.is_deleted = 0 ORDER BY c.created_at DESC LIMIT 20",
                    is_critical=True,
                ),
            ],
            priority=6,
        ))
        
        # Skill 12: 顾客套餐剩余次数
        self.register(Skill(
            id="customer_package_remaining",
            name="顾客套餐剩余次数",
            description="查询顾客套餐剩余次数",
            keywords=["剩余", "次数", "还有", "套餐", "没用完", "可用"],
            patterns=[
                r"(剩余|还有|剩下).*?(次数|次|天)",
                r"(顾客|客户|会员).*?(剩余|还有|套餐)",
                r"(套餐|卡).*?(剩余|还有|没用完)",
            ],
            steps=[
                SkillStep(
                    step=1,
                    agent="nl2sql",
                    task="查询顾客套餐剩余次数",
                    description="查询顾客各套餐的剩余次数",
                    query="SELECT c.nickname, p.name as package_name, p.type as package_type, COUNT(CASE WHEN cs.status = 1 THEN 1 END) as remaining_sessions, COUNT(cs.id) as total_sessions FROM customers c JOIN purchases pu ON c.id = pu.customer_id AND pu.shop_id = :shop_id AND pu.status = 1 JOIN packages p ON pu.package_id = p.id LEFT JOIN customer_sessions cs ON pu.id = cs.purchase_id WHERE c.shop_id = :shop_id AND c.is_deleted = 0 GROUP BY c.id, c.nickname, p.id, p.name, p.type HAVING COUNT(CASE WHEN cs.status = 1 THEN 1 END) > 0 ORDER BY c.nickname LIMIT 20",
                    is_critical=True,
                ),
            ],
            priority=6,
        ))
    
    def register(self, skill: Skill):
        """注册 Skill"""
        self._skills[skill.id] = skill
    
    def unregister(self, skill_id: str):
        """注销 Skill"""
        self._skills.pop(skill_id, None)
    
    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """获取 Skill"""
        return self._skills.get(skill_id)
    
    def get_all_skills(self) -> List[Skill]:
        """获取所有 Skills"""
        return list(self._skills.values())
    
    def match(self, query: str, min_score: float = 0.5) -> Optional[Tuple[Skill, float]]:
        """
        匹配用户查询
        
        Args:
            query: 用户查询
            min_score: 最低匹配分数
        
        Returns:
            (最佳匹配的 Skill, 匹配分数) 或 None
        """
        best_skill = None
        best_score = 0.0
        
        for skill in self._skills.values():
            if not skill.enabled:
                continue
            
            score = skill.matches(query)
            
            # 考虑优先级
            adjusted_score = score + (skill.priority * 0.01)
            
            if adjusted_score > best_score and score >= min_score:
                best_skill = skill
                best_score = adjusted_score
        
        if best_skill:
            return (best_skill, best_score)
        
        return None
    
    def match_all(self, query: str, min_score: float = 0.3) -> List[Tuple[Skill, float]]:
        """
        匹配所有符合条件的 Skills
        
        Args:
            query: 用户查询
            min_score: 最低匹配分数
        
        Returns:
            匹配的 (Skill, 分数) 列表，按分数降序排列
        """
        matches = []
        
        for skill in self._skills.values():
            if not skill.enabled:
                continue
            
            score = skill.matches(query)
            if score >= min_score:
                matches.append((skill, score))
        
        # 按分数降序排列
        matches.sort(key=lambda x: x[1], reverse=True)
        
        return matches


# 全局实例
_skill_manager = None


def get_skill_manager() -> SkillManager:
    """获取 Skill 管理器单例"""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager
