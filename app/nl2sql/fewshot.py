"""
动态Few-shot检索
根据用户问题，从向量库检索相似的SQL样例
"""

from langchain_core.documents import Document

# 预定义的NL2SQL样例库
FEW_SHOT_EXAMPLES = [
    # 营业额查询
    {
        "question": "今天营业额是多少",
        "sql": "SELECT COALESCE(SUM(paid_amount), 0) as today_revenue FROM purchases WHERE shop_id = :shop_id AND DATE(created_at) = CURDATE() AND status = 1 AND is_deleted = 0",
    },
    {
        "question": "本月营业额多少",
        "sql": "SELECT COALESCE(SUM(paid_amount), 0) as monthly_revenue FROM purchases WHERE shop_id = :shop_id AND YEAR(created_at) = YEAR(NOW()) AND MONTH(created_at) = MONTH(NOW()) AND status = 1 AND is_deleted = 0",
    },
    {
        "question": "上个月营业额",
        "sql": "SELECT COALESCE(SUM(paid_amount), 0) as last_month_revenue FROM purchases WHERE shop_id = :shop_id AND YEAR(created_at) = YEAR(DATE_SUB(NOW(), INTERVAL 1 MONTH)) AND MONTH(created_at) = MONTH(DATE_SUB(NOW(), INTERVAL 1 MONTH)) AND status = 1 AND is_deleted = 0",
    },
    # 顾客查询
    {
        "question": "本月新顾客数量",
        "sql": "SELECT COUNT(*) as new_customers FROM customers WHERE shop_id = :shop_id AND YEAR(created_at) = YEAR(NOW()) AND MONTH(created_at) = MONTH(NOW()) AND is_deleted = 0",
    },
    {
        "question": "查一下顾客小灰灰的信息",
        "sql": "SELECT id, nickname, phone, gender, created_at FROM customers WHERE shop_id = :shop_id AND nickname LIKE '%小灰灰%' AND is_deleted = 0",
    },
    # 退款查询
    {
        "question": "有没有待审核的退款",
        "sql": "SELECT rr.id, c.nickname, rr.refund_amount, rr.reason, rr.created_at FROM refund_records rr JOIN purchases pu ON rr.purchase_id = pu.id LEFT JOIN customers c ON pu.customer_id = c.id WHERE pu.shop_id = :shop_id AND rr.status = 1 AND rr.is_deleted = 0",
    },
    {
        "question": "已拒绝的退款记录",
        "sql": "SELECT rr.id, c.nickname, rr.refund_amount, rr.reason, rr.created_at FROM refund_records rr JOIN purchases pu ON rr.purchase_id = pu.id LEFT JOIN customers c ON pu.customer_id = c.id WHERE pu.shop_id = :shop_id AND rr.status = 3 AND rr.is_deleted = 0",
    },
    # 套餐查询
    {
        "question": "各套餐销量排名",
        "sql": "SELECT p.name, COUNT(*) as sales_count FROM purchases pu JOIN packages p ON pu.package_id = p.id WHERE pu.shop_id = :shop_id AND pu.status = 1 AND pu.is_deleted = 0 GROUP BY p.id ORDER BY sales_count DESC LIMIT 10",
    },
    {
        "question": "店里有哪些套餐",
        "sql": "SELECT id, name, type, price, duration_minutes FROM packages WHERE shop_id = :shop_id AND is_deleted = 0 AND is_active = 1",
    },
    # 库存查询
    {
        "question": "库存不足的物料",
        "sql": "SELECT m.name, i.quantity, m.min_stock FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.shop_id = :shop_id AND i.quantity <= m.min_stock AND m.is_deleted = 0",
    },
    {
        "question": "拼豆124色还有多少库存",
        "sql": "SELECT m.name, i.quantity, m.unit FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.shop_id = :shop_id AND m.name LIKE '%124色%' AND m.is_deleted = 0",
    },
    # 员工查询
    {
        "question": "各员工核销数量",
        "sql": "SELECT s.name, COUNT(*) as checkin_count FROM game_sessions gs JOIN staff s ON gs.staff_id = s.id WHERE gs.shop_id = :shop_id AND gs.status = 2 AND MONTH(gs.end_time) = MONTH(NOW()) AND YEAR(gs.end_time) = YEAR(NOW()) GROUP BY s.id ORDER BY checkin_count DESC",
    },
    {
        "question": "店里有几个员工",
        "sql": "SELECT COUNT(*) as staff_count FROM staff s JOIN staff_shops ss ON s.id = ss.staff_id WHERE ss.shop_id = :shop_id AND s.is_deleted = 0",
    },
    # 排班查询
    {
        "question": "今天的排班情况",
        "sql": "SELECT s.name, ss.start_time, ss.end_time FROM staff_schedules ss JOIN staff s ON ss.staff_id = s.id WHERE ss.shop_id = :shop_id AND ss.schedule_date = CURDATE()",
    },
    # 优惠券查询
    {
        "question": "现在有哪些优惠券",
        "sql": "SELECT id, name, type, value, remain_stock, total_stock FROM coupons WHERE shop_id = :shop_id AND is_active = 1",
    },
    # 收支统计
    {
        "question": "本月收入支出统计",
        "sql": "SELECT '收入' as type, COALESCE(SUM(paid_amount), 0) as total FROM purchases WHERE shop_id = :shop_id AND status = 1 AND MONTH(created_at) = MONTH(NOW()) AND YEAR(created_at) = YEAR(NOW()) UNION ALL SELECT '支出', COALESCE(SUM(amount), 0) FROM expenses WHERE shop_id = :shop_id AND MONTH(expense_date) = MONTH(NOW()) AND YEAR(expense_date) = YEAR(NOW())",
    },
]


def get_few_shot_examples() -> list[dict]:
    """获取预定义的Few-shot样例"""
    return FEW_SHOT_EXAMPLES


def retrieve_similar_examples(question: str, k: int = 3) -> list[dict]:
    """
    根据问题检索相似样例
    简单版本：基于关键词匹配
    后续可升级为向量检索
    """
    results = []
    question_lower = question.lower()

    for example in FEW_SHOT_EXAMPLES:
        # 简单的关键词匹配评分
        score = 0
        keywords = example["question"].replace("?", "").replace("？", "").split()
        for keyword in keywords:
            if keyword in question_lower:
                score += 1

        if score > 0:
            results.append({**example, "score": score})

    # 按分数排序，取top-k
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:k]


def format_few_shot_prompt(examples: list[dict]) -> str:
    """将样例格式化为Prompt"""
    if not examples:
        return ""

    formatted = "以下是类似的SQL查询示例：\n\n"
    for i, ex in enumerate(examples, 1):
        formatted += f"问题{i}: {ex['question']}\n"
        formatted += f"SQL{i}: {ex['sql']}\n\n"
    return formatted
