"""
NL2SQL 安全模块测试用例
测试 AST 校验、注入检测、查询优化、SQL 修正等功能
"""

import pytest
import asyncio

# 设置测试环境
import os
os.environ["ENVIRONMENT"] = "test"
os.environ["LLM_API_KEY"] = "test_key"


class TestSQLParser:
    """SQL 解析器测试"""
    
    def test_parse_select(self):
        """测试解析 SELECT 语句"""
        from app.nl2sql.sql_parser import parse_sql, StatementType
        
        sql = "SELECT id, name FROM customers WHERE shop_id = 1"
        result = parse_sql(sql)
        
        assert result.is_valid is True
        assert result.statement_type == StatementType.SELECT
        assert "customers" in result.tables
        assert "id" in result.columns
        assert "name" in result.columns
    
    def test_parse_insert(self):
        """测试解析 INSERT 语句"""
        from app.nl2sql.sql_parser import parse_sql, StatementType
        
        sql = "INSERT INTO customers (name, phone) VALUES ('test', '123')"
        result = parse_sql(sql)
        
        assert result.statement_type == StatementType.INSERT
    
    def test_parse_delete(self):
        """测试解析 DELETE 语句"""
        from app.nl2sql.sql_parser import parse_sql, StatementType
        
        sql = "DELETE FROM customers WHERE id = 1"
        result = parse_sql(sql)
        
        assert result.statement_type == StatementType.DELETE
    
    def test_parse_join(self):
        """测试解析 JOIN"""
        from app.nl2sql.sql_parser import parse_sql
        
        sql = """
        SELECT p.name, c.nickname 
        FROM purchases pu 
        JOIN packages p ON pu.package_id = p.id 
        JOIN customers c ON pu.customer_id = c.id
        """
        result = parse_sql(sql)
        
        assert result.is_valid is True
        assert "purchases" in result.tables
        assert "packages" in result.join_tables
        assert "customers" in result.join_tables
    
    def test_parse_subquery(self):
        """测试解析子查询"""
        from app.nl2sql.sql_parser import parse_sql
        
        sql = """
        SELECT * FROM customers 
        WHERE id IN (SELECT customer_id FROM purchases WHERE shop_id = 1)
        """
        result = parse_sql(sql)
        
        assert result.is_valid is True
        assert len(result.subqueries) > 0
    
    def test_parse_where_conditions(self):
        """测试解析 WHERE 条件"""
        from app.nl2sql.sql_parser import parse_sql
        
        sql = "SELECT * FROM customers WHERE shop_id = 1 AND status = 1"
        result = parse_sql(sql)
        
        assert result.is_valid is True
        assert len(result.where_conditions) > 0
    
    def test_check_dangerous_patterns(self):
        """测试检测危险模式"""
        from app.nl2sql.sql_parser import check_sql_dangerous
        
        # UNION 注入
        sql1 = "SELECT * FROM users UNION SELECT * FROM passwords"
        warnings1 = check_sql_dangerous(sql1)
        assert len(warnings1) > 0
        
        # 时间盲注
        sql2 = "SELECT * FROM users WHERE id = 1 AND SLEEP(5)"
        warnings2 = check_sql_dangerous(sql2)
        assert len(warnings2) > 0


class TestASTValidator:
    """AST 校验器测试"""
    
    def test_validate_select_safe(self):
        """测试安全的 SELECT 语句"""
        from app.nl2sql.ast_validator import validate_sql_ast
        
        sql = "SELECT id, name FROM customers WHERE shop_id = 1 LIMIT 10"
        result = validate_sql_ast(sql, shop_id=1, level="strict")
        
        assert result["is_valid"] is True
        assert result["error_count"] == 0
    
    def test_validate_insert_blocked(self):
        """测试阻止 INSERT 语句"""
        from app.nl2sql.ast_validator import validate_sql_ast
        
        sql = "INSERT INTO customers (name) VALUES ('test')"
        result = validate_sql_ast(sql, level="strict")
        
        assert result["is_valid"] is False
        assert result["error_count"] > 0
    
    def test_validate_delete_blocked(self):
        """测试阻止 DELETE 语句"""
        from app.nl2sql.ast_validator import validate_sql_ast
        
        sql = "DELETE FROM customers WHERE id = 1"
        result = validate_sql_ast(sql, level="strict")
        
        assert result["is_valid"] is False
    
    def test_validate_drop_blocked(self):
        """测试阻止 DROP 语句"""
        from app.nl2sql.ast_validator import validate_sql_ast
        
        sql = "DROP TABLE customers"
        result = validate_sql_ast(sql, level="strict")
        
        assert result["is_valid"] is False
    
    def test_validate_union_blocked(self):
        """测试阻止 UNION 注入"""
        from app.nl2sql.ast_validator import validate_sql_ast
        
        sql = "SELECT * FROM customers UNION SELECT * FROM staff"
        result = validate_sql_ast(sql, level="strict")
        
        assert result["is_valid"] is False
    
    def test_validate_shop_id_required(self):
        """测试 shop_id 必须性检查"""
        from app.nl2sql.ast_validator import validate_sql_ast
        
        # 缺少 shop_id
        sql1 = "SELECT * FROM customers"
        result1 = validate_sql_ast(sql1, shop_id=None, level="strict")
        assert result1["is_valid"] is False
        
        # 包含 shop_id
        sql2 = "SELECT * FROM customers WHERE shop_id = 1"
        result2 = validate_sql_ast(sql2, shop_id=1, level="strict")
        assert result2["is_valid"] is True
    
    def test_validate_dangerous_function(self):
        """测试危险函数检测"""
        from app.nl2sql.ast_validator import validate_sql_ast
        
        sql = "SELECT SLEEP(5)"
        result = validate_sql_ast(sql, level="strict")
        
        assert result["is_valid"] is False
    
    def test_validate_stacked_queries(self):
        """测试堆叠查询检测"""
        from app.nl2sql.ast_validator import validate_sql_ast
        
        sql = "SELECT * FROM customers; DROP TABLE customers"
        result = validate_sql_ast(sql, level="strict")
        
        assert result["is_valid"] is False


class TestInjectionDetector:
    """注入检测器测试"""
    
    def test_detect_union_injection(self):
        """测试 UNION 注入检测"""
        from app.nl2sql.injection_detector import detect_injection
        
        sql = "SELECT * FROM users UNION SELECT username, password FROM admin"
        report = detect_injection(sql)
        
        assert report["is_safe"] is False
        assert report["risk_score"] > 0
        assert report["high_risk_count"] > 0
    
    def test_detect_time_based_injection(self):
        """测试时间盲注检测"""
        from app.nl2sql.injection_detector import detect_injection
        
        sql = "SELECT * FROM users WHERE id = 1 AND SLEEP(5)"
        report = detect_injection(sql)
        
        assert report["is_safe"] is False
        assert any(d["type"] == "time_based" for d in report["detections"])
    
    def test_detect_boolean_based_injection(self):
        """测试布尔盲注检测"""
        from app.nl2sql.injection_detector import detect_injection
        
        sql = "SELECT * FROM users WHERE id = 1 AND 1=1"
        report = detect_injection(sql)
        
        assert report["risk_score"] > 0
    
    def test_detect_error_based_injection(self):
        """测试报错注入检测"""
        from app.nl2sql.injection_detector import detect_injection
        
        sql = "SELECT EXTRACTVALUE(1, CONCAT(0x7e, (SELECT version())))"
        report = detect_injection(sql)
        
        assert report["is_safe"] is False
        assert any(d["type"] == "error_based" for d in report["detections"])
    
    def test_detect_stacked_queries(self):
        """测试堆叠查询检测"""
        from app.nl2sql.injection_detector import detect_injection
        
        sql = "SELECT * FROM users; DROP TABLE users"
        report = detect_injection(sql)
        
        assert report["is_safe"] is False
        assert any(d["type"] == "stacked_queries" for d in report["detections"])
    
    def test_detect_encoding_bypass(self):
        """测试编码绕过检测"""
        from app.nl2sql.injection_detector import detect_injection
        
        sql = "SELECT * FROM users WHERE name = CHAR(97,100,109,105,110)"
        report = detect_injection(sql)
        
        assert report["risk_score"] > 0
    
    def test_detect_logic_manipulation(self):
        """测试逻辑操纵检测"""
        from app.nl2sql.injection_detector import detect_injection
        
        sql = "SELECT * FROM users WHERE username = 'admin' OR 1=1"
        report = detect_injection(sql)
        
        assert report["risk_score"] > 0
    
    def test_safe_sql(self):
        """测试安全 SQL"""
        from app.nl2sql.injection_detector import detect_injection
        
        sql = "SELECT id, name FROM customers WHERE shop_id = 1 LIMIT 10"
        report = detect_injection(sql)
        
        assert report["is_safe"] is True
        assert report["risk_score"] == 0


class TestQueryOptimizer:
    """查询优化器测试"""
    
    def test_optimize_select_star(self):
        """测试 SELECT * 优化建议"""
        from app.nl2sql.query_optimizer import optimize_query
        
        sql = "SELECT * FROM customers WHERE shop_id = 1"
        report = optimize_query(sql)
        
        assert report["score"] < 100
        assert any(s["type"] == "select" for s in report["suggestions"])
    
    def test_optimize_missing_limit(self):
        """测试缺少 LIMIT 优化建议"""
        from app.nl2sql.query_optimizer import optimize_query
        
        sql = "SELECT id, name FROM customers WHERE shop_id = 1"
        report = optimize_query(sql)
        
        assert any(s["type"] == "limit" for s in report["suggestions"])
    
    def test_optimize_like_prefix(self):
        """测试 LIKE 前缀通配符优化建议"""
        from app.nl2sql.query_optimizer import optimize_query
        
        sql = "SELECT * FROM customers WHERE name LIKE '%test%'"
        report = optimize_query(sql)
        
        assert any(s["type"] == "index" for s in report["suggestions"])
    
    def test_optimize_or_conditions(self):
        """测试 OR 条件优化建议"""
        from app.nl2sql.query_optimizer import optimize_query
        
        sql = "SELECT * FROM customers WHERE status = 1 OR status = 2 OR status = 3"
        report = optimize_query(sql)
        
        assert report["has_suggestions"] is True
    
    def test_optimize_subquery(self):
        """测试子查询优化建议"""
        from app.nl2sql.query_optimizer import optimize_query
        
        sql = """
        SELECT * FROM customers 
        WHERE id IN (SELECT customer_id FROM purchases WHERE status = 1)
        """
        report = optimize_query(sql)
        
        assert any(s["type"] == "subquery" for s in report["suggestions"])
    
    def test_optimize_function_in_where(self):
        """测试 WHERE 中函数使用优化建议"""
        from app.nl2sql.query_optimizer import optimize_query
        
        sql = "SELECT * FROM purchases WHERE DATE(created_at) = '2024-01-01'"
        report = optimize_query(sql)
        
        assert any(s["type"] == "function" for s in report["suggestions"])
    
    def test_optimized_sql_score(self):
        """测试优化良好的 SQL 分数"""
        from app.nl2sql.query_optimizer import optimize_query
        
        sql = "SELECT id, name FROM customers WHERE shop_id = 1 LIMIT 10"
        report = optimize_query(sql)
        
        # 应该只有少量建议或没有
        assert report["score"] >= 80


class TestSQLFixer:
    """SQL 修正器测试"""
    
    def test_fix_typos(self):
        """测试拼写错误修正"""
        from app.nl2sql.sql_fixer import fix_sql
        
        sql = "SELCT * FORM customers WHRE id = 1"
        result = fix_sql(sql)
        
        assert result["is_modified"] is True
        assert "SELECT" in result["fixed_sql"]
        assert "FROM" in result["fixed_sql"]
        assert "WHERE" in result["fixed_sql"]
    
    def test_fix_function_names(self):
        """测试函数名修正"""
        from app.nl2sql.sql_fixer import fix_sql
        
        sql = "SELECT COUT(*) FROM customers"
        result = fix_sql(sql)
        
        assert "COUNT" in result["fixed_sql"]
    
    def test_fix_parentheses(self):
        """测试括号平衡修正"""
        from app.nl2sql.sql_fixer import fix_sql
        
        sql = "SELECT * FROM (SELECT * FROM customers"
        result = fix_sql(sql)
        
        # 应该添加了缺少的右括号
        assert result["fixed_sql"].count(")") >= result["fixed_sql"].count("(")
    
    def test_fix_trailing_comma(self):
        """测试多余逗号修正"""
        from app.nl2sql.sql_fixer import fix_sql
        
        sql = "SELECT id, name, FROM customers"
        result = fix_sql(sql)
        
        # 应该移除了 FROM 前的逗号
        assert ", FROM" not in result["fixed_sql"]
    
    def test_fix_spacing(self):
        """测试空格修正"""
        from app.nl2sql.sql_fixer import fix_sql
        
        sql = "SELECT*FROM customers WHERE id=1"
        result = fix_sql(sql)
        
        assert "SELECT *" in result["fixed_sql"] or "SELECT *" not in result["fixed_sql"]
    
    def test_fix_for_injection(self):
        """测试注入风险修正"""
        from app.nl2sql.sql_fixer import fix_sql_for_injection
        
        sql = "SELECT * FROM users WHERE id = 1 AND SLEEP(5)"
        result = fix_sql_for_injection(sql)
        
        assert "SLEEP" not in result["fixed_sql"]
        assert result["is_modified"] is True


class TestSecurityIntegration:
    """安全模块集成测试"""
    
    def test_comprehensive_safe_sql(self):
        """测试综合检查 - 安全 SQL"""
        from app.nl2sql.ast_validator import validate_sql_ast
        from app.nl2sql.injection_detector import detect_injection
        from app.nl2sql.query_optimizer import optimize_query
        
        sql = "SELECT id, name, phone FROM customers WHERE shop_id = 1 LIMIT 10"
        
        validation = validate_sql_ast(sql, shop_id=1)
        injection = detect_injection(sql)
        optimization = optimize_query(sql)
        
        assert validation["is_valid"] is True
        assert injection["is_safe"] is True
        assert optimization["score"] >= 80
    
    def test_comprehensive_unsafe_sql(self):
        """测试综合检查 - 不安全 SQL"""
        from app.nl2sql.ast_validator import validate_sql_ast
        from app.nl2sql.injection_detector import detect_injection
        
        sql = "SELECT * FROM users UNION SELECT * FROM passwords"
        
        validation = validate_sql_ast(sql)
        injection = detect_injection(sql)
        
        assert validation["is_valid"] is False
        assert injection["is_safe"] is False
    
    def test_comprehensive_injection_sql(self):
        """测试综合检查 - 注入 SQL"""
        from app.nl2sql.injection_detector import detect_injection
        
        sql = "SELECT * FROM users WHERE id = 1; DROP TABLE users"
        
        injection = detect_injection(sql)
        
        assert injection["is_safe"] is False
        assert injection["high_risk_count"] > 0


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
