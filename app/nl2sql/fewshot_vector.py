"""
动态 Few-shot 向量检索模块
基于向量相似度检索最相关的 SQL 样例
"""

import os
from typing import Dict, List, Optional
from dataclasses import dataclass
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma
from app.config import settings
from app.chroma_config import chroma_settings


@dataclass
class FewShotExample:
    """Few-shot 样例"""
    question: str
    sql: str
    category: str = ""  # 查询类别
    difficulty: int = 1  # 难度等级 1-3


# 预定义的 NL2SQL 样例库（扩展版）
DEFAULT_FEW_SHOT_EXAMPLES = [
    # 营业额查询
    FewShotExample(
        question="今天营业额是多少",
        sql="SELECT COALESCE(SUM(paid_amount), 0) as today_revenue FROM purchases WHERE shop_id = :shop_id AND DATE(created_at) = CURDATE() AND status = 1",
        category="revenue",
        difficulty=1
    ),
    FewShotExample(
        question="本月总营收",
        sql="SELECT COALESCE(SUM(paid_amount), 0) as monthly_revenue FROM purchases WHERE shop_id = :shop_id AND MONTH(created_at) = MONTH(NOW()) AND YEAR(created_at) = YEAR(NOW()) AND status = 1",
        category="revenue",
        difficulty=1
    ),
    FewShotExample(
        question="最近7天每天的营业额",
        sql="SELECT DATE(created_at) as date, COALESCE(SUM(paid_amount), 0) as daily_revenue FROM purchases WHERE shop_id = :shop_id AND created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) AND status = 1 GROUP BY DATE(created_at) ORDER BY date",
        category="revenue",
        difficulty=2
    ),
    
    # 顾客查询
    FewShotExample(
        question="本月新顾客数量",
        sql="SELECT COUNT(*) as new_customers FROM customers WHERE shop_id = :shop_id AND MONTH(created_at) = MONTH(NOW()) AND YEAR(created_at) = YEAR(NOW())",
        category="customer",
        difficulty=1
    ),
    FewShotExample(
        question="消费金额最高的前10名顾客",
        sql="SELECT c.nickname, c.phone, SUM(pu.paid_amount) as total_spent FROM purchases pu JOIN customers c ON pu.customer_id = c.id WHERE pu.shop_id = :shop_id AND pu.status = 1 GROUP BY c.id ORDER BY total_spent DESC LIMIT 10",
        category="customer",
        difficulty=2
    ),
    FewShotExample(
        question="最近30天没有消费的顾客",
        sql="SELECT c.id, c.nickname, c.phone FROM customers c WHERE c.shop_id = :shop_id AND c.id NOT IN (SELECT DISTINCT customer_id FROM purchases WHERE shop_id = :shop_id AND created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY))",
        category="customer",
        difficulty=3
    ),
    
    # 套餐查询
    FewShotExample(
        question="各套餐销量排名",
        sql="SELECT p.name, COUNT(*) as sales_count, SUM(pu.paid_amount) as total_amount FROM purchases pu JOIN packages p ON pu.package_id = p.id WHERE pu.shop_id = :shop_id AND pu.status = 1 GROUP BY p.id ORDER BY sales_count DESC",
        category="package",
        difficulty=2
    ),
    FewShotExample(
        question="周卡和月卡的销售对比",
        sql="SELECT p.type, COUNT(*) as sales_count, SUM(pu.paid_amount) as total_amount FROM purchases pu JOIN packages p ON pu.package_id = p.id WHERE pu.shop_id = :shop_id AND p.type IN (2, 3) AND pu.status = 1 GROUP BY p.type",
        category="package",
        difficulty=2
    ),
    
    # 库存查询
    FewShotExample(
        question="库存不足的物料",
        sql="SELECT m.name, m.sku, i.quantity, m.min_stock FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.shop_id = :shop_id AND i.quantity <= m.min_stock",
        category="inventory",
        difficulty=1
    ),
    FewShotExample(
        question="各分类库存总值",
        sql="SELECT m.category, SUM(i.quantity) as total_quantity FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.shop_id = :shop_id GROUP BY m.category ORDER BY total_quantity DESC",
        category="inventory",
        difficulty=2
    ),
    
    # 员工查询
    FewShotExample(
        question="各员工核销数量",
        sql="SELECT s.name, COUNT(*) as checkin_count FROM game_sessions gs JOIN staff s ON gs.staff_id = s.id WHERE gs.shop_id = :shop_id AND gs.status = 2 AND MONTH(gs.end_time) = MONTH(NOW()) GROUP BY s.id ORDER BY checkin_count DESC",
        category="staff",
        difficulty=2
    ),
    FewShotExample(
        question="本月员工绩效排名",
        sql="SELECT s.name, COUNT(*) as completed_sessions, SUM(TIMESTAMPDIFF(MINUTE, gs.start_time, gs.end_time)) as total_minutes FROM game_sessions gs JOIN staff s ON gs.staff_id = s.id WHERE gs.shop_id = :shop_id AND gs.status = 2 AND MONTH(gs.end_time) = MONTH(NOW()) GROUP BY s.id ORDER BY completed_sessions DESC",
        category="staff",
        difficulty=3
    ),
    
    # 收支查询
    FewShotExample(
        question="本月收入支出统计",
        sql="SELECT '收入' as type, COALESCE(SUM(amount), 0) as total FROM revenue_records WHERE shop_id = :shop_id AND MONTH(created_at) = MONTH(NOW()) UNION ALL SELECT '支出' as type, COALESCE(SUM(amount), 0) as total FROM expenses WHERE shop_id = :shop_id AND MONTH(expense_date) = MONTH(NOW())",
        category="finance",
        difficulty=2
    ),
    FewShotExample(
        question="各支出分类的金额",
        sql="SELECT ec.name as category_name, SUM(e.amount) as total_amount FROM expenses e JOIN expense_categories ec ON e.category_id = ec.id WHERE e.shop_id = :shop_id AND MONTH(e.expense_date) = MONTH(NOW()) GROUP BY ec.id ORDER BY total_amount DESC",
        category="finance",
        difficulty=2
    ),
    
    # ==================== 复杂查询示例 ====================
    
    # 跨表聚合 - 收入支出利润
    FewShotExample(
        question="上个月的净利润是多少",
        sql="SELECT COALESCE(revenue.total, 0) - COALESCE(expense.total, 0) AS net_profit FROM (SELECT SUM(rr.amount) AS total FROM revenue_records rr WHERE rr.shop_id = :shop_id AND rr.created_at >= DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 MONTH), '%Y-%m-01') AND rr.created_at < DATE_FORMAT(CURDATE(), '%Y-%m-01')) revenue CROSS JOIN (SELECT SUM(e.amount) AS total FROM expenses e WHERE e.shop_id = :shop_id AND e.expense_date >= DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 MONTH), '%Y-%m-01') AND e.expense_date < DATE_FORMAT(CURDATE(), '%Y-%m-01')) expense",
        category="finance",
        difficulty=3
    ),
    
    # 顾客活跃度分析
    FewShotExample(
        question="按顾客活跃度统计人数",
        sql="SELECT CASE WHEN last_purchase >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) THEN '7天内' WHEN last_purchase >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) THEN '7-30天' WHEN last_purchase >= DATE_SUB(CURDATE(), INTERVAL 90 DAY) THEN '30-90天' ELSE '90天以上' END AS activity_level, COUNT(*) AS customer_count FROM (SELECT c.id, MAX(p.created_at) AS last_purchase FROM customers c LEFT JOIN purchases p ON c.id = p.customer_id AND p.shop_id = :shop_id WHERE c.shop_id = :shop_id GROUP BY c.id) t GROUP BY activity_level ORDER BY FIELD(activity_level, '7天内', '7-30天', '30-90天', '90天以上')",
        category="customer",
        difficulty=3
    ),
    
    # 环比增长率
    FewShotExample(
        question="本月营业额环比增长率",
        sql="SELECT this_month.revenue AS this_month_revenue, last_month.revenue AS last_month_revenue, ROUND((this_month.revenue - last_month.revenue) / last_month.revenue * 100, 2) AS growth_rate FROM (SELECT COALESCE(SUM(paid_amount), 0) AS revenue FROM purchases WHERE shop_id = :shop_id AND MONTH(created_at) = MONTH(NOW()) AND YEAR(created_at) = YEAR(NOW()) AND status = 1) this_month CROSS JOIN (SELECT COALESCE(SUM(paid_amount), 0) AS revenue FROM purchases WHERE shop_id = :shop_id AND MONTH(created_at) = MONTH(DATE_SUB(CURDATE(), INTERVAL 1 MONTH)) AND YEAR(created_at) = YEAR(DATE_SUB(CURDATE(), INTERVAL 1 MONTH)) AND status = 1) last_month",
        category="revenue",
        difficulty=3
    ),
    
    # 顾客消费频次分布
    FewShotExample(
        question="顾客消费频次分布",
        sql="SELECT CASE WHEN purchase_count = 1 THEN '1次' WHEN purchase_count BETWEEN 2 AND 3 THEN '2-3次' WHEN purchase_count BETWEEN 4 AND 6 THEN '4-6次' ELSE '7次以上' END AS frequency_group, COUNT(*) AS customer_count FROM (SELECT c.id, COUNT(p.id) AS purchase_count FROM customers c LEFT JOIN purchases p ON c.id = p.customer_id AND p.shop_id = :shop_id WHERE c.shop_id = :shop_id GROUP BY c.id) t GROUP BY frequency_group ORDER BY FIELD(frequency_group, '1次', '2-3次', '4-6次', '7次以上')",
        category="customer",
        difficulty=3
    ),
    
    # 热销套餐排名
    FewShotExample(
        question="本月热销套餐TOP5",
        sql="SELECT p.name AS package_name, COUNT(*) AS sales_count, SUM(pu.paid_amount) AS total_amount FROM purchases pu JOIN packages p ON pu.package_id = p.id WHERE pu.shop_id = :shop_id AND pu.status = 1 AND MONTH(pu.created_at) = MONTH(NOW()) AND YEAR(pu.created_at) = YEAR(NOW()) GROUP BY p.id ORDER BY sales_count DESC LIMIT 5",
        category="package",
        difficulty=2
    ),
    
    # 员工提成计算
    FewShotExample(
        question="本月员工提成明细",
        sql="SELECT s.name AS staff_name, COUNT(gs.id) AS session_count, COALESCE(SUM(rr.amount), 0) AS total_revenue, ROUND(COALESCE(SUM(rr.amount), 0) * cr.value / 100, 2) AS commission_amount FROM staff s JOIN game_sessions gs ON s.id = gs.staff_id JOIN revenue_records rr ON gs.id = rr.game_session_id JOIN staff_roles sr ON s.id = sr.staff_id JOIN commission_rules cr ON sr.role_id = cr.role_id WHERE gs.shop_id = :shop_id AND gs.status = 2 AND MONTH(gs.end_time) = MONTH(NOW()) AND cr.is_active = 1 GROUP BY s.id ORDER BY commission_amount DESC",
        category="staff",
        difficulty=3
    ),
    
    # 库存周转率
    FewShotExample(
        question="本月物料库存周转率",
        sql="SELECT m.name AS material_name, i.quantity AS current_stock, COALESCE(outbound.total_out, 0) AS outbound_quantity, ROUND(COALESCE(outbound.total_out, 0) / i.quantity * 100, 2) AS turnover_rate FROM inventory i JOIN materials m ON i.material_id = m.id LEFT JOIN (SELECT material_id, SUM(quantity) AS total_out FROM inventory_transactions WHERE shop_id = :shop_id AND transaction_type = 2 AND MONTH(created_at) = MONTH(NOW()) GROUP BY material_id) outbound ON m.id = outbound.material_id WHERE i.shop_id = :shop_id AND i.quantity > 0 ORDER BY turnover_rate DESC",
        category="inventory",
        difficulty=3
    ),
    
    # ==================== 充值相关示例 ====================
    
    # 充值最多的顾客
    FewShotExample(
        question="哪个顾客充值最多",
        sql="SELECT c.nickname, cw.total_recharged FROM customer_wallets cw JOIN customers c ON cw.customer_id = c.id WHERE cw.shop_id = :shop_id ORDER BY cw.total_recharged DESC LIMIT 1",
        category="customer",
        difficulty=1
    ),
    
    # 顾客余额查询
    FewShotExample(
        question="顾客余额查询",
        sql="SELECT c.nickname, cw.balance, cw.total_recharged, cw.total_spent FROM customer_wallets cw JOIN customers c ON cw.customer_id = c.id WHERE cw.shop_id = :shop_id ORDER BY cw.balance DESC",
        category="customer",
        difficulty=1
    ),
    
    # 本月充值总额
    FewShotExample(
        question="本月充值总额",
        sql="SELECT COALESCE(SUM(amount), 0) as total_recharge FROM wallet_transactions WHERE shop_id = :shop_id AND type = 1 AND MONTH(created_at) = MONTH(NOW()) AND YEAR(created_at) = YEAR(NOW())",
        category="finance",
        difficulty=1
    ),
    
    # 充值排行TOP10
    FewShotExample(
        question="充值金额最多的前10名顾客",
        sql="SELECT c.nickname, c.phone, cw.total_recharged FROM customer_wallets cw JOIN customers c ON cw.customer_id = c.id WHERE cw.shop_id = :shop_id ORDER BY cw.total_recharged DESC LIMIT 10",
        category="customer",
        difficulty=1
    ),
]


class VectorFewShotRetriever:
    """基于向量的 Few-shot 检索器"""
    
    def __init__(self, embeddings: Optional[Embeddings] = None):
        """
        初始化向量检索器
        
        Args:
            embeddings: 嵌入模型，如果不提供则使用默认配置
        """
        self.embeddings = embeddings
        self.vectorstore: Optional[Chroma] = None
        self.examples: List[FewShotExample] = []
        self._initialized = False
    
    def _get_embeddings(self) -> Embeddings:
        """获取嵌入模型"""
        if self.embeddings:
            return self.embeddings
        
        # 使用统一的嵌入模型配置
        from app.rag.embeddings import get_embeddings
        return get_embeddings()
    
    def _init_vectorstore(self):
        """初始化向量库"""
        if self._initialized:
            return
        
        embeddings = self._get_embeddings()
        
        # 创建向量库目录
        persist_dir = os.path.join(settings.CHROMA_PERSIST_DIR, "fewshot")
        os.makedirs(persist_dir, exist_ok=True)
        
        # 初始化 Chroma 向量库（禁用遥测）
        self.vectorstore = Chroma(
            collection_name="nl2sql_fewshot",
            embedding_function=embeddings,
            persist_directory=persist_dir,
            client_settings=chroma_settings,
        )
        
        self._initialized = True
    
    def add_examples(self, examples: List[FewShotExample]):
        """
        添加样例到向量库
        
        Args:
            examples: Few-shot 样例列表
        """
        self._init_vectorstore()
        
        # 准备文档
        documents = []
        metadatas = []
        ids = []
        
        for i, example in enumerate(examples):
            # 文档内容是问题（用于向量化）
            doc = Document(
                page_content=example.question,
                metadata={
                    "sql": example.sql,
                    "category": example.category,
                    "difficulty": example.difficulty
                }
            )
            documents.append(doc)
            ids.append(f"example_{len(self.examples) + i}")
        
        # 添加到向量库
        self.vectorstore.add_documents(documents, ids=ids)
        self.examples.extend(examples)
    
    def init_default_examples(self):
        """初始化默认样例"""
        if not self.examples:
            self.add_examples(DEFAULT_FEW_SHOT_EXAMPLES)
    
    def retrieve(self, question: str, k: int = 3) -> List[Dict]:
        """
        检索相似样例
        
        Args:
            question: 用户问题
            k: 返回数量
        
        Returns:
            相似样例列表
        """
        self._init_vectorstore()
        
        # 如果没有样例，初始化默认样例
        if not self.examples:
            self.init_default_examples()
        
        # 向量检索
        results = self.vectorstore.similarity_search_with_score(
            question,
            k=min(k, len(self.examples))
        )
        
        # 格式化结果
        examples = []
        for doc, score in results:
            examples.append({
                "question": doc.page_content,
                "sql": doc.metadata.get("sql", ""),
                "category": doc.metadata.get("category", ""),
                "difficulty": doc.metadata.get("difficulty", 1),
                "similarity_score": 1 - score  # 转换为相似度分数
            })
        
        return examples
    
    def retrieve_by_category(self, question: str, category: str, k: int = 3) -> List[Dict]:
        """
        按类别检索相似样例
        
        Args:
            question: 用户问题
            category: 查询类别
            k: 返回数量
        
        Returns:
            相似样例列表
        """
        self._init_vectorstore()
        
        if not self.examples:
            self.init_default_examples()
        
        # 带过滤的向量检索
        results = self.vectorstore.similarity_search_with_score(
            question,
            k=k * 2,  # 多检索一些，后面过滤
            filter={"category": category}
        )
        
        examples = []
        for doc, score in results[:k]:
            examples.append({
                "question": doc.page_content,
                "sql": doc.metadata.get("sql", ""),
                "category": doc.metadata.get("category", ""),
                "difficulty": doc.metadata.get("difficulty", 1),
                "similarity_score": 1 - score
            })
        
        return examples


# 全局实例
fewshot_retriever = VectorFewShotRetriever()


def get_few_shot_examples(question: str, k: int = 3) -> List[Dict]:
    """获取 Few-shot 样例"""
    fewshot_retriever.init_default_examples()
    return fewshot_retriever.retrieve(question, k)


def format_few_shot_prompt(examples: List[Dict]) -> str:
    """将样例格式化为 Prompt"""
    if not examples:
        return ""
    
    formatted = "## 参考示例\n\n"
    formatted += "以下是类似的查询示例，请参考其 SQL 写法：\n\n"
    
    for i, ex in enumerate(examples, 1):
        formatted += f"### 示例 {i}\n"
        formatted += f"问题：{ex['question']}\n"
        formatted += f"SQL：\n```sql\n{ex['sql']}\n```\n\n"
    
    return formatted
