"""
动态Few-shot检索
根据用户问题，从向量库检索相似的SQL样例
"""

from langchain_core.documents import Document

# 预定义的NL2SQL样例库
FEW_SHOT_EXAMPLES = [
    {
        "question": "今天营业额是多少",
        "sql": "SELECT COALESCE(SUM(paid_amount), 0) as today_revenue FROM purchases WHERE shop_id = ? AND DATE(created_at) = CURDATE() AND status = 1",
    },
    {
        "question": "本月新顾客数量",
        "sql": "SELECT COUNT(DISTINCT id) as new_customers FROM customers WHERE shop_id = ? AND MONTH(created_at) = MONTH(NOW()) AND YEAR(created_at) = YEAR(NOW())",
    },
    {
        "question": "各套餐销量排名",
        "sql": "SELECT p.name, COUNT(*) as sales_count FROM purchases pu JOIN packages p ON pu.package_id = p.id WHERE pu.shop_id = ? AND pu.status = 1 GROUP BY p.id ORDER BY sales_count DESC LIMIT 10",
    },
    {
        "question": "库存不足的物料",
        "sql": "SELECT m.name, i.quantity, m.min_stock FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.shop_id = ? AND i.quantity <= m.min_stock",
    },
    {
        "question": "本月收入支出统计",
        "sql": "SELECT '收入' as type, COALESCE(SUM(amount), 0) as total FROM revenue_records WHERE shop_id = ? AND MONTH(created_at) = MONTH(NOW()) UNION ALL SELECT '支出' as type, COALESCE(SUM(amount), 0) as total FROM expenses WHERE shop_id = ? AND MONTH(created_at) = MONTH(NOW())",
    },
    {
        "question": "各员工核销数量",
        "sql": "SELECT s.name, COUNT(*) as checkin_count FROM game_sessions gs JOIN staff s ON gs.staff_id = s.id WHERE gs.shop_id = ? AND gs.status = 2 AND MONTH(gs.end_time) = MONTH(NOW()) GROUP BY s.id ORDER BY checkin_count DESC",
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
