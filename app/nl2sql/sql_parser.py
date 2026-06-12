"""
SQL 解析器模块
基于 sqlglot 库实现 SQL 语句的 AST 解析
"""

from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import sqlglot
from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError


class StatementType(Enum):
    """SQL 语句类型"""
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    CREATE = "CREATE"
    ALTER = "ALTER"
    DROP = "DROP"
    UNKNOWN = "UNKNOWN"


@dataclass
class ParsedSQL:
    """解析后的 SQL 结构"""
    statement_type: StatementType
    tables: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    where_conditions: List[str] = field(default_factory=list)
    join_tables: List[str] = field(default_factory=list)
    subqueries: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    has_limit: bool = False
    has_order_by: bool = False
    has_group_by: bool = False
    has_having: bool = False
    is_valid: bool = True
    parse_errors: List[str] = field(default_factory=list)
    ast: Optional[exp.Expression] = None  # 原始 AST 对象


class SQLParser:
    """SQL 解析器 - 基于 sqlglot"""
    
    # 危险函数列表
    DANGEROUS_FUNCTIONS = {
        'sleep', 'benchmark', 'load_file', 'into_outfile', 'into_dumpfile',
        'extractvalue', 'updatexml', 'gtid_subset', 'gtid_subtract',
        'st_linemfromtext', 'st_linempointfromtext', 'st_pointfromtext',
        'geomfromtext', 'polygonfromtext', 'linefromtext', 'pointfromtext',
        'multilinestringfromtext', 'multipointfromtext', 'multipolygonfromtext',
    }
    
    # 危险关键词组合
    DANGEROUS_PATTERNS = [
        'union all select',
        'union select',
        'into outfile',
        'into dumpfile',
        'load data infile',
        'execute immediate',
    ]
    
    def parse(self, sql: str, dialect: str = "mysql") -> ParsedSQL:
        """
        解析 SQL 语句
        
        Args:
            sql: SQL 语句
            dialect: SQL 方言，默认 mysql
        
        Returns:
            ParsedSQL 结构化对象
        """
        result = ParsedSQL(statement_type=StatementType.UNKNOWN)
        
        try:
            # 清理 SQL
            sql = self._clean_sql(sql)
            
            # 使用 sqlglot 解析
            ast = parse_one(sql, dialect=dialect)
            result.ast = ast
            
            # 获取语句类型
            result.statement_type = self._get_statement_type(ast)
            
            # 提取表名
            result.tables = self._extract_tables(ast)
            
            # 提取列名
            result.columns = self._extract_columns(ast)
            
            # 提取 WHERE 条件
            result.where_conditions = self._extract_where_conditions(ast)
            
            # 提取 JOIN 表
            result.join_tables = self._extract_join_tables(ast)
            
            # 提取子查询
            result.subqueries = self._extract_subqueries(ast)
            
            # 提取函数
            result.functions = self._extract_functions(ast)
            
            # 检查特殊子句
            result.has_limit = self._has_limit(ast)
            result.has_order_by = self._has_order_by(ast)
            result.has_group_by = self._has_group_by(ast)
            result.has_having = self._has_having(ast)
            
        except SqlglotError as e:
            result.is_valid = False
            result.parse_errors.append(f"SQL 解析错误: {str(e)}")
        except Exception as e:
            result.is_valid = False
            result.parse_errors.append(f"未知错误: {str(e)}")
        
        return result
    
    def _clean_sql(self, sql: str) -> str:
        """清理 SQL 语句"""
        import re
        # 移除注释
        sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
        sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        # 移除多余空白
        sql = re.sub(r'\s+', ' ', sql).strip()
        # 移除末尾分号
        if sql.endswith(';'):
            sql = sql[:-1].strip()
        return sql
    
    def _get_statement_type(self, ast: exp.Expression) -> StatementType:
        """获取语句类型"""
        if isinstance(ast, exp.Select):
            return StatementType.SELECT
        elif isinstance(ast, exp.Insert):
            return StatementType.INSERT
        elif isinstance(ast, exp.Update):
            return StatementType.UPDATE
        elif isinstance(ast, exp.Delete):
            return StatementType.DELETE
        elif isinstance(ast, exp.Create):
            return StatementType.CREATE
        elif isinstance(ast, exp.Alter):
            return StatementType.ALTER
        elif isinstance(ast, exp.Drop):
            return StatementType.DROP
        return StatementType.UNKNOWN
    
    def _extract_tables(self, ast: exp.Expression) -> List[str]:
        """提取表名"""
        tables = set()
        
        # 查找所有 Table 节点
        for table in ast.find_all(exp.Table):
            table_name = table.name
            if table_name:
                tables.add(table_name)
        
        return list(tables)
    
    def _extract_columns(self, ast: exp.Expression) -> List[str]:
        """提取列名"""
        columns = set()
        
        # 查找 SELECT 中的列
        if isinstance(ast, exp.Select):
            for expression in ast.expressions:
                if isinstance(expression, exp.Star):
                    columns.add("*")
                elif isinstance(expression, exp.Column):
                    col_name = expression.name
                    table_name = expression.table
                    if table_name:
                        columns.add(f"{table_name}.{col_name}")
                    else:
                        columns.add(col_name)
                elif isinstance(expression, exp.Alias):
                    # 获取别名
                    alias_name = expression.alias
                    if alias_name:
                        columns.add(alias_name)
        
        return list(columns)
    
    def _extract_where_conditions(self, ast: exp.Expression) -> List[str]:
        """提取 WHERE 条件"""
        conditions = []
        
        # 查找 WHERE 子句
        where = ast.find(exp.Where)
        if where:
            # 递归提取条件
            conditions.extend(self._parse_condition(where.this))
        
        return conditions
    
    def _parse_condition(self, condition: exp.Expression) -> List[str]:
        """递归解析条件"""
        conditions = []
        
        if isinstance(condition, exp.And):
            conditions.extend(self._parse_condition(condition.left))
            conditions.extend(self._parse_condition(condition.right))
        elif isinstance(condition, exp.Or):
            conditions.extend(self._parse_condition(condition.left))
            conditions.extend(self._parse_condition(condition.right))
        elif isinstance(condition, (exp.EQ, exp.NE, exp.GT, exp.GTE, exp.LT, exp.LTE)):
            conditions.append(condition.sql())
        elif isinstance(condition, exp.Like):
            conditions.append(condition.sql())
        elif isinstance(condition, exp.In):
            conditions.append(condition.sql())
        elif isinstance(condition, exp.Between):
            conditions.append(condition.sql())
        else:
            conditions.append(condition.sql())
        
        return conditions
    
    def _extract_join_tables(self, ast: exp.Expression) -> List[str]:
        """提取 JOIN 表"""
        join_tables = []
        
        for join in ast.find_all(exp.Join):
            table = join.this
            if isinstance(table, exp.Table):
                join_tables.append(table.name)
        
        return join_tables
    
    def _extract_subqueries(self, ast: exp.Expression) -> List[str]:
        """提取子查询"""
        subqueries = []
        
        for subquery in ast.find_all(exp.Subquery):
            subqueries.append(subquery.sql())
        
        return subqueries
    
    def _extract_functions(self, ast: exp.Expression) -> List[str]:
        """提取函数"""
        functions = set()
        
        for func in ast.find_all(exp.Func):
            func_name = func.sql_name().lower() if hasattr(func, 'sql_name') else func.key.lower()
            functions.add(func_name)
        
        return list(functions)
    
    def _has_limit(self, ast: exp.Expression) -> bool:
        """检查是否有 LIMIT"""
        return ast.find(exp.Limit) is not None
    
    def _has_order_by(self, ast: exp.Expression) -> bool:
        """检查是否有 ORDER BY"""
        return ast.find(exp.Order) is not None
    
    def _has_group_by(self, ast: exp.Expression) -> bool:
        """检查是否有 GROUP BY"""
        return ast.find(exp.Group) is not None
    
    def _has_having(self, ast: exp.Expression) -> bool:
        """检查是否有 HAVING"""
        return ast.find(exp.Having) is not None
    
    def check_dangerous_patterns(self, sql: str) -> List[str]:
        """
        检查危险模式
        
        Args:
            sql: SQL 语句
        
        Returns:
            检测到的危险模式列表
        """
        warnings = []
        sql_lower = sql.lower()
        
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern in sql_lower:
                warnings.append(f"检测到危险模式: {pattern}")
        
        return warnings
    
    def check_dangerous_functions(self, ast: exp.Expression) -> List[str]:
        """
        检查危险函数
        
        Args:
            ast: SQL AST
        
        Returns:
            检测到的危险函数列表
        """
        warnings = []
        
        for func in ast.find_all(exp.Func):
            func_name = func.sql_name().lower() if hasattr(func, 'sql_name') else func.key.lower()
            if func_name in self.DANGEROUS_FUNCTIONS:
                warnings.append(f"检测到危险函数: {func_name}")
        
        return warnings
    
    def to_sql(self, ast: exp.Expression, dialect: str = "mysql") -> str:
        """
        将 AST 转换回 SQL
        
        Args:
            ast: SQL AST
            dialect: 目标方言
        
        Returns:
            SQL 语句
        """
        return ast.sql(dialect=dialect)
    
    def optimize(self, sql: str, dialect: str = "mysql") -> str:
        """
        优化 SQL
        
        Args:
            sql: SQL 语句
            dialect: SQL 方言
        
        Returns:
            优化后的 SQL
        """
        try:
            ast = parse_one(sql, dialect=dialect)
            optimized = sqlglot.optimize(ast, dialect=dialect)
            return optimized.sql(dialect=dialect)
        except Exception:
            return sql


# 全局实例
sql_parser = SQLParser()


def parse_sql(sql: str, dialect: str = "mysql") -> ParsedSQL:
    """解析 SQL 语句"""
    return sql_parser.parse(sql, dialect)


def check_sql_dangerous(sql: str) -> List[str]:
    """检查 SQL 危险模式和函数"""
    warnings = []
    warnings.extend(sql_parser.check_dangerous_patterns(sql))
    
    try:
        ast = parse_one(sql, dialect="mysql")
        warnings.extend(sql_parser.check_dangerous_functions(ast))
    except Exception:
        pass
    
    return warnings


def sql_to_ast(sql: str, dialect: str = "mysql") -> Optional[exp.Expression]:
    """将 SQL 转换为 AST"""
    try:
        return parse_one(sql, dialect=dialect)
    except Exception:
        return None


def ast_to_sql(ast: exp.Expression, dialect: str = "mysql") -> str:
    """将 AST 转换为 SQL"""
    return ast.sql(dialect=dialect)
