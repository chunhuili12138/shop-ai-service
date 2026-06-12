"""
SQL 查询优化建议器
基于 sqlglot AST 分析 SQL 性能并给出优化建议
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError
from app.nl2sql.sql_parser import SQLParser, ParsedSQL, parse_sql


class OptimizationType(Enum):
    """优化类型"""
    INDEX = "index"                 # 索引优化
    SELECT = "select"               # SELECT 优化
    JOIN = "join"                   # JOIN 优化
    WHERE = "where"                 # WHERE 优化
    SUBQUERY = "subquery"           # 子查询优化
    LIMIT = "limit"                 # LIMIT 优化
    FUNCTION = "function"           # 函数使用优化
    PATTERN = "pattern"             # 查询模式优化


@dataclass
class OptimizationSuggestion:
    """优化建议"""
    type: OptimizationType
    priority: str  # high, medium, low
    issue: str
    suggestion: str
    example: Optional[str] = None


@dataclass
class OptimizationReport:
    """优化报告"""
    score: int  # 0-100, 100 表示最优
    suggestions: List[OptimizationSuggestion] = field(default_factory=list)
    optimized_sql: Optional[str] = None  # sqlglot 优化后的 SQL
    
    @property
    def has_suggestions(self) -> bool:
        return len(self.suggestions) > 0
    
    @property
    def high_priority_count(self) -> int:
        return sum(1 for s in self.suggestions if s.priority == "high")
    
    def to_dict(self) -> Dict:
        return {
            "score": self.score,
            "suggestion_count": len(self.suggestions),
            "high_priority_count": self.high_priority_count,
            "optimized_sql": self.optimized_sql,
            "suggestions": [
                {
                    "type": s.type.value,
                    "priority": s.priority,
                    "issue": s.issue,
                    "suggestion": s.suggestion,
                    "example": s.example
                }
                for s in self.suggestions
            ]
        }


class QueryOptimizer:
    """查询优化器 - 基于 sqlglot"""
    
    # 可能需要索引的列（根据常见查询模式）
    INDEX_CANDIDATES = {
        'shop_id', 'customer_id', 'package_id', 'staff_id',
        'material_id', 'category_id', 'supplier_id',
        'created_at', 'updated_at', 'status'
    }
    
    def __init__(self):
        self.parser = SQLParser()
    
    def analyze(self, sql: str, dialect: str = "mysql") -> OptimizationReport:
        """
        分析 SQL 并给出优化建议
        
        Args:
            sql: SQL 语句
            dialect: SQL 方言
        
        Returns:
            优化报告
        """
        report = OptimizationReport(score=100)
        
        # 1. 解析 SQL
        parsed = self.parser.parse(sql, dialect=dialect)
        
        if not parsed.is_valid:
            report.suggestions.append(OptimizationSuggestion(
                type=OptimizationType.PATTERN,
                priority="high",
                issue="SQL 解析失败",
                suggestion="请检查 SQL 语法是否正确"
            ))
            report.score = 0
            return report
        
        # 2. 使用 sqlglot 优化 SQL
        try:
            ast = parse_one(sql, dialect=dialect)
            optimized = sqlglot.optimize(ast, dialect=dialect)
            report.optimized_sql = optimized.sql(dialect=dialect)
        except Exception:
            report.optimized_sql = sql
        
        # 3. 检查 SELECT *
        self._check_select_star(parsed, sql, report)
        
        # 4. 检查缺少 LIMIT
        self._check_missing_limit(parsed, report)
        
        # 5. 检查索引使用
        self._check_index_usage(parsed, sql, report)
        
        # 6. 检查子查询
        self._check_subqueries(parsed, sql, report)
        
        # 7. 检查 JOIN 优化
        self._check_join_optimization(parsed, sql, report)
        
        # 8. 检查 WHERE 条件
        self._check_where_conditions(parsed, sql, report)
        
        # 9. 检查函数使用
        self._check_function_usage(parsed, sql, report)
        
        # 10. 检查 LIKE 模式
        self._check_like_patterns(sql, report)
        
        # 11. 检查 OR 条件
        self._check_or_conditions(sql, report)
        
        # 计算最终分数
        report.score = max(0, 100 - len(report.suggestions) * 10)
        
        return report
    
    def _check_select_star(self, parsed: ParsedSQL, sql: str, report: OptimizationReport):
        """检查 SELECT *"""
        if '*' in parsed.columns:
            report.suggestions.append(OptimizationSuggestion(
                type=OptimizationType.SELECT,
                priority="medium",
                issue="使用了 SELECT *",
                suggestion="明确指定需要的列名，避免返回不必要的数据",
                example="SELECT id, name, price FROM packages"
            ))
    
    def _check_missing_limit(self, parsed: ParsedSQL, report: OptimizationReport):
        """检查缺少 LIMIT"""
        if not parsed.has_limit and parsed.statement_type.value == "SELECT":
            report.suggestions.append(OptimizationSuggestion(
                type=OptimizationType.LIMIT,
                priority="medium",
                issue="缺少 LIMIT 子句",
                suggestion="添加 LIMIT 限制返回行数，避免返回大量数据",
                example="SELECT * FROM purchases WHERE shop_id = 1 LIMIT 100"
            ))
    
    def _check_index_usage(self, parsed: ParsedSQL, sql: str, report: OptimizationReport):
        """检查索引使用"""
        # 检查 WHERE 条件中的列
        where_columns = set()
        for condition in parsed.where_conditions:
            # 提取列名
            col_match = re.search(r'(\w+)\s*(=|!=|<>|>|<|>=|<=|LIKE|IN|BETWEEN)', condition, re.IGNORECASE)
            if col_match:
                where_columns.add(col_match.group(1).lower())
        
        # 检查是否使用了可能需要索引的列
        missing_index_cols = where_columns & self.INDEX_CANDIDATES
        
        if missing_index_cols:
            report.suggestions.append(OptimizationSuggestion(
                type=OptimizationType.INDEX,
                priority="medium",
                issue=f"WHERE/JOIN 条件中的列可能需要索引: {', '.join(missing_index_cols)}",
                suggestion="确保这些列有索引以提高查询性能",
                example=f"CREATE INDEX idx_table_column ON table_name ({', '.join(list(missing_index_cols)[:3])})"
            ))
    
    def _check_subqueries(self, parsed: ParsedSQL, sql: str, report: OptimizationReport):
        """检查子查询"""
        if parsed.subqueries:
            # 检查是否可以用 JOIN 替代
            for subquery in parsed.subqueries:
                if 'IN' in sql.upper() and 'SELECT' in subquery.upper():
                    report.suggestions.append(OptimizationSuggestion(
                        type=OptimizationType.SUBQUERY,
                        priority="medium",
                        issue="使用了 IN 子查询",
                        suggestion="考虑使用 JOIN 替代 IN 子查询，通常性能更好",
                        example="SELECT * FROM purchases p JOIN customers c ON p.customer_id = c.id"
                    ))
                    break
    
    def _check_join_optimization(self, parsed: ParsedSQL, sql: str, report: OptimizationReport):
        """检查 JOIN 优化"""
        # 检查是否有多个 JOIN
        join_count = sql.upper().count('JOIN')
        
        if join_count > 3:
            report.suggestions.append(OptimizationSuggestion(
                type=OptimizationType.JOIN,
                priority="medium",
                issue=f"查询包含 {join_count} 个 JOIN",
                suggestion="过多的 JOIN 可能影响性能，考虑是否可以简化查询或使用物化视图"
            ))
        
        # 检查是否缺少 JOIN 条件
        if parsed.join_tables and not parsed.where_conditions:
            # 简单检查：有 JOIN 但没有 WHERE 条件
            if 'ON' not in sql.upper():
                report.suggestions.append(OptimizationSuggestion(
                    type=OptimizationType.JOIN,
                    priority="high",
                    issue="JOIN 可能缺少 ON 条件",
                    suggestion="确保每个 JOIN 都有明确的 ON 条件，避免笛卡尔积"
                ))
    
    def _check_where_conditions(self, parsed: ParsedSQL, sql: str, report: OptimizationReport):
        """检查 WHERE 条件"""
        # 检查 OR 条件
        if ' OR ' in sql.upper():
            report.suggestions.append(OptimizationSuggestion(
                type=OptimizationType.WHERE,
                priority="low",
                issue="使用了 OR 条件",
                suggestion="OR 条件可能导致索引失效，考虑使用 UNION ALL 替代"
            ))
        
        # 检查 NOT IN
        if 'NOT IN' in sql.upper():
            report.suggestions.append(OptimizationSuggestion(
                type=OptimizationType.WHERE,
                priority="medium",
                issue="使用了 NOT IN",
                suggestion="NOT IN 可能导致性能问题，考虑使用 LEFT JOIN ... IS NULL 替代"
            ))
    
    def _check_function_usage(self, parsed: ParsedSQL, sql: str, report: OptimizationReport):
        """检查函数使用"""
        # 检查 WHERE 条件中使用函数
        func_in_where = re.search(r'WHERE\s+.*?\b(\w+)\s*\(', sql, re.IGNORECASE | re.DOTALL)
        if func_in_where:
            func_name = func_in_where.group(1).upper()
            if func_name in ('DATE', 'YEAR', 'MONTH', 'DAY', 'UPPER', 'LOWER'):
                report.suggestions.append(OptimizationSuggestion(
                    type=OptimizationType.FUNCTION,
                    priority="medium",
                    issue=f"WHERE 条件中使用了函数: {func_name}",
                    suggestion="在列上使用函数会导致索引失效，考虑改写条件",
                    example="WHERE DATE(created_at) = '2024-01-01' -> WHERE created_at >= '2024-01-01' AND created_at < '2024-01-02'"
                ))
    
    def _check_like_patterns(self, sql: str, report: OptimizationReport):
        """检查 LIKE 模式"""
        # 检查前缀通配符
        if re.search(r"LIKE\s+'%", sql, re.IGNORECASE):
            report.suggestions.append(OptimizationSuggestion(
                type=OptimizationType.INDEX,
                priority="high",
                issue="LIKE 使用了前缀通配符 (%)",
                suggestion="前缀通配符会导致索引失效，考虑使用全文索引或后缀通配符"
            ))
    
    def _check_or_conditions(self, sql: str, report: OptimizationReport):
        """检查 OR 条件优化"""
        # 检查多个 OR 条件
        or_count = sql.upper().count(' OR ')
        if or_count > 2:
            report.suggestions.append(OptimizationSuggestion(
                type=OptimizationType.WHERE,
                priority="low",
                issue=f"使用了 {or_count} 个 OR 条件",
                suggestion="多个 OR 条件可能影响性能，考虑使用 IN 或 UNION ALL"
            ))


# 全局实例
query_optimizer = QueryOptimizer()


def optimize_query(sql: str, dialect: str = "mysql") -> Dict:
    """
    分析查询优化（API 接口）
    
    Args:
        sql: SQL 语句
        dialect: SQL 方言
    
    Returns:
        优化报告字典
    """
    report = query_optimizer.analyze(sql, dialect)
    return report.to_dict()
