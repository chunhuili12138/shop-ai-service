"""
NL2SQL 模块测试用例
测试 Schema Linking、Few-shot 检索、SQL 生成、安全校验、自修正等功能
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock

# 设置测试环境
import os
os.environ["ENVIRONMENT"] = "test"
os.environ["LLM_API_KEY"] = "test_key"
os.environ["MYSQL_URL"] = "sqlite:///test.db"


class TestSchemaLinker:
    """Schema Linker 测试"""
    
    def test_extract_keywords(self):
        """测试关键词提取"""
        from app.nl2sql.schema_linker import SchemaLinker
        
        linker = SchemaLinker()
        keywords = linker.extract_keywords("今天营业额是多少")
        
        assert "今天" in keywords or "营业额" in keywords
    
    def test_match_tables_revenue(self):
        """测试营业额相关表匹配"""
        from app.nl2sql.schema_linker import SchemaLinker
        
        linker = SchemaLinker()
        keywords = ["营业额", "收入", "销售"]
        table_scores = linker.match_tables(keywords)
        
        assert "purchases" in table_scores
    
    def test_match_tables_customer(self):
        """测试顾客相关表匹配"""
        from app.nl2sql.schema_linker import SchemaLinker
        
        linker = SchemaLinker()
        keywords = ["顾客", "客户", "会员"]
        table_scores = linker.match_tables(keywords)
        
        assert "customers" in table_scores
    
    def test_match_tables_inventory(self):
        """测试库存相关表匹配"""
        from app.nl2sql.schema_linker import SchemaLinker
        
        linker = SchemaLinker()
        keywords = ["库存", "物料", "存货"]
        table_scores = linker.match_tables(keywords)
        
        assert "inventory" in table_scores
        assert "materials" in table_scores
    
    def test_link_revenue_question(self):
        """测试营业额问题的 Schema Linking"""
        from app.nl2sql.schema_linker import get_schema_link
        
        result = get_schema_link("今天营业额是多少")
        
        assert "purchases" in result.relevant_tables
        assert result.confidence > 0
    
    def test_link_customer_question(self):
        """测试顾客问题的 Schema Linking"""
        from app.nl2sql.schema_linker import get_schema_link
        
        result = get_schema_link("本月新顾客数量")
        
        assert "customers" in result.relevant_tables
    
    def test_link_inventory_question(self):
        """测试库存问题的 Schema Linking"""
        from app.nl2sql.schema_linker import get_schema_link
        
        result = get_schema_link("库存不足的物料有哪些")
        
        assert "inventory" in result.relevant_tables
        assert "materials" in result.relevant_tables
    
    def test_format_for_prompt(self):
        """测试 Prompt 格式化"""
        from app.nl2sql.schema_linker import SchemaLinker, get_schema_link
        
        linker = SchemaLinker()
        result = get_schema_link("今天营业额")
        formatted = linker.format_for_prompt(result)
        
        assert "purchases" in formatted
        assert "shop_id" in formatted


class TestFewShotRetriever:
    """Few-shot 检索器测试"""
    
    def test_default_examples_loaded(self):
        """测试默认样例加载"""
        from app.nl2sql.fewshot_vector import DEFAULT_FEW_SHOT_EXAMPLES
        
        assert len(DEFAULT_FEW_SHOT_EXAMPLES) > 0
        
        # 检查样例结构
        for example in DEFAULT_FEW_SHOT_EXAMPLES:
            assert example.question
            assert example.sql
            assert "SELECT" in example.sql.upper()
    
    def test_format_few_shot_prompt(self):
        """测试 Few-shot Prompt 格式化"""
        from app.nl2sql.fewshot_vector import format_few_shot_prompt
        
        examples = [
            {
                "question": "今天营业额",
                "sql": "SELECT SUM(amount) FROM purchases",
                "category": "revenue",
                "difficulty": 1,
                "similarity_score": 0.9
            }
        ]
        
        formatted = format_few_shot_prompt(examples)
        
        assert "今天营业额" in formatted
        assert "SELECT" in formatted
    
    def test_format_empty_examples(self):
        """测试空样例格式化"""
        from app.nl2sql.fewshot_vector import format_few_shot_prompt
        
        formatted = format_few_shot_prompt([])
        assert formatted == ""


class TestSQLSafety:
    """SQL 安全校验测试"""
    
    def test_validate_select(self):
        """测试 SELECT 语句校验"""
        from app.nl2sql.safety import validate_sql
        
        is_safe, msg = validate_sql("SELECT * FROM purchases WHERE shop_id = 1")
        assert is_safe is True
    
    def test_reject_delete(self):
        """测试拒绝 DELETE 语句"""
        from app.nl2sql.safety import validate_sql
        
        is_safe, msg = validate_sql("DELETE FROM purchases WHERE id = 1")
        assert is_safe is False
        assert "危险操作" in msg or "只允许" in msg
    
    def test_reject_drop(self):
        """测试拒绝 DROP 语句"""
        from app.nl2sql.safety import validate_sql
        
        is_safe, msg = validate_sql("DROP TABLE purchases")
        assert is_safe is False
    
    def test_reject_update(self):
        """测试拒绝 UPDATE 语句"""
        from app.nl2sql.safety import validate_sql
        
        is_safe, msg = validate_sql("UPDATE purchases SET status = 2 WHERE id = 1")
        assert is_safe is False
    
    def test_reject_insert(self):
        """测试拒绝 INSERT 语句"""
        from app.nl2sql.safety import validate_sql
        
        is_safe, msg = validate_sql("INSERT INTO purchases (amount) VALUES (100)")
        assert is_safe is False
    
    def test_sanitize_sql(self):
        """测试 SQL 清理"""
        from app.nl2sql.safety import sanitize_sql
        
        sql = "  SELECT   *   FROM   purchases  ;  "
        cleaned = sanitize_sql(sql)
        
        assert cleaned == "SELECT   *   FROM   purchases"
    
    def test_add_limit(self):
        """测试添加 LIMIT"""
        from app.nl2sql.safety import add_limit
        
        sql = "SELECT * FROM purchases"
        limited = add_limit(sql, 50)
        
        assert "LIMIT" in limited.upper()
        assert "50" in limited
    
    def test_add_limit_existing(self):
        """测试已有 LIMIT 的 SQL"""
        from app.nl2sql.safety import add_limit
        
        sql = "SELECT * FROM purchases LIMIT 10"
        limited = add_limit(sql, 50)
        
        # 应该保持原有的 LIMIT
        assert "LIMIT 10" in limited
    
    def test_add_shop_filter(self):
        """测试添加店铺过滤"""
        from app.nl2sql.safety import add_shop_filter
        
        sql = "SELECT * FROM purchases WHERE status = 1"
        filtered = add_shop_filter(sql, 5)
        
        assert "shop_id = 5" in filtered
    
    def test_add_shop_filter_no_where(self):
        """测试没有 WHERE 的 SQL 添加店铺过滤"""
        from app.nl2sql.safety import add_shop_filter
        
        sql = "SELECT COUNT(*) FROM purchases"
        filtered = add_shop_filter(sql, 5)
        
        assert "shop_id = 5" in filtered


class TestSelfCorrection:
    """SQL 自修正测试"""
    
    def test_classify_column_error(self):
        """测试列名错误分类"""
        from app.nl2sql.self_correction import SQLSelfCorrection
        
        corrector = SQLSelfCorrection()
        error_type, hint = corrector.classify_error("Unknown column 'amount' in 'field list'")
        
        assert error_type == "column_not_found"
    
    def test_classify_table_error(self):
        """测试表名错误分类"""
        from app.nl2sql.self_correction import SQLSelfCorrection
        
        corrector = SQLSelfCorrection()
        error_type, hint = corrector.classify_error("Table 'shop_operate_system.purchase' doesn't exist")
        
        assert error_type == "table_not_found"
    
    def test_classify_syntax_error(self):
        """测试语法错误分类"""
        from app.nl2sql.self_correction import SQLSelfCorrection
        
        corrector = SQLSelfCorrection()
        error_type, hint = corrector.classify_error("You have an error in your SQL syntax")
        
        assert error_type == "syntax_error"
    
    def test_extract_error_details(self):
        """测试错误详情提取"""
        from app.nl2sql.self_correction import SQLSelfCorrection
        
        corrector = SQLSelfCorrection()
        details = corrector.extract_error_details("Unknown column 'amount' in 'field list'")
        
        assert details.get("unknown_column") == "amount"


class TestResultExplainer:
    """结果解释器测试"""
    
    @pytest.mark.asyncio
    async def test_explain_empty_results(self):
        """测试空结果解释"""
        from app.nl2sql.result_explainer import ResultExplainer
        
        explainer = ResultExplainer()
        explanation = await explainer.explain(
            question="今天营业额",
            sql="SELECT SUM(amount) FROM purchases",
            results=[]
        )
        
        assert "为空" in explanation or "没有" in explanation
    
    def test_prepare_result_summary(self):
        """测试结果摘要准备"""
        from app.nl2sql.result_explainer import ResultExplainer
        
        explainer = ResultExplainer()
        results = [
            {"name": "周卡", "sales": 10},
            {"name": "月卡", "sales": 5}
        ]
        
        summary = explainer._prepare_result_summary(results, 10)
        
        assert "周卡" in summary
        assert "月卡" in summary
    
    def test_generate_basic_explanation(self):
        """测试基本解释生成"""
        from app.nl2sql.result_explainer import ResultExplainer
        
        explainer = ResultExplainer()
        results = [{"count": 42}]
        
        explanation = explainer._generate_basic_explanation(
            "今天有多少订单",
            results
        )
        
        assert "1" in explanation  # 1 条结果


class TestNL2SQLIntegration:
    """NL2SQL 集成测试"""
    
    @pytest.mark.asyncio
    async def test_nl2sql_endpoint_structure(self):
        """测试 NL2SQL 端点结构"""
        from app.nl2sql.router import NL2SQLRequest, NL2SQLResponse
        
        # 测试请求模型
        request = NL2SQLRequest(question="今天营业额", shop_id=1)
        assert request.question == "今天营业额"
        assert request.shop_id == 1
        assert request.enable_correction is True
        
        # 测试响应模型
        response = NL2SQLResponse(
            question="今天营业额",
            sql="SELECT 1",
            results=[],
            formatted_results="",
            is_safe=True
        )
        assert response.is_safe is True
        assert response.correction_applied is False


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
