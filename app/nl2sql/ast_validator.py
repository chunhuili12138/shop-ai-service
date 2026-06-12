"""
AST 级别 SQL 校验器
基于 sqlglot AST 进行精确的安全校验
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError
from app.nl2sql.sql_parser import (
    SQLParser, ParsedSQL, StatementType, 
    parse_sql, check_sql_dangerous
)


class ValidationLevel(Enum):
    """校验级别"""
    STRICT = "strict"      # 严格模式（生产环境）
    MODERATE = "moderate"  # 中等模式
    LENIENT = "lenient"    # 宽松模式（开发环境）


@dataclass
class ValidationResult:
    """校验结果"""
    is_valid: bool
    level: ValidationLevel
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    parsed_sql: Optional[ParsedSQL] = None
    
    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0
    
    def to_dict(self) -> Dict:
        return {
            "is_valid": self.is_valid,
            "level": self.level.value,
            "errors": self.errors,
            "warnings": self.warnings,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings)
        }


class ASTValidator:
    """AST 级别 SQL 校验器 - 基于 sqlglot"""
    
    # 允许的语句类型（白名单）
    ALLOWED_STATEMENTS = {StatementType.SELECT}
    
    # 危险的语句类型
    DANGEROUS_STATEMENTS = {
        StatementType.INSERT,
        StatementType.UPDATE,
        StatementType.DELETE,
        StatementType.CREATE,
        StatementType.ALTER,
        StatementType.DROP,
    }
    
    # 必须包含 shop_id 的表
    SHOP_TABLES = {
        'customers', 'packages', 'purchases', 'game_sessions',
        'materials', 'inventory', 'staff', 'revenue_records',
        'expenses', 'expense_categories', 'coupons', 'articles',
        'feedbacks', 'queue_entries', 'daily_snapshots',
        'attendance_records', 'staff_schedules', 'commission_rules',
        'commission_settlements', 'invoices', 'suppliers',
        'purchase_orders', 'purchase_order_items', 'purchase_payments',
        'customer_wallets', 'wallet_transactions', 'points_records',
        'customer_sessions', 'refund_records', 'prepayments',
        'coupon_usages', 'article_categories', 'notification_logs',
        'operation_logs', 'inventory_transactions'
    }
    
    def __init__(self, level: ValidationLevel = ValidationLevel.STRICT):
        """
        初始化校验器
        
        Args:
            level: 校验级别
        """
        self.level = level
        self.parser = SQLParser()
    
    def validate(self, sql: str, shop_id: Optional[int] = None, dialect: str = "mysql") -> ValidationResult:
        """
        校验 SQL 安全性
        
        Args:
            sql: SQL 语句
            shop_id: 店铺 ID（用于检查数据隔离）
            dialect: SQL 方言
        
        Returns:
            校验结果
        """
        result = ValidationResult(is_valid=True, level=self.level)
        
        # 1. 解析 SQL
        parsed = self.parser.parse(sql, dialect=dialect)
        result.parsed_sql = parsed
        
        # 2. 检查解析是否成功
        if not parsed.is_valid:
            result.is_valid = False
            result.errors.extend(parsed.parse_errors)
            return result
        
        # 3. 检查语句类型
        self._check_statement_type(parsed, result)
        
        # 4. 检查危险模式和函数
        self._check_dangerous_patterns(sql, parsed, result)
        
        # 5. 检查子查询安全性
        self._check_subqueries(parsed, result, dialect)
        
        # 6. 检查数据隔离（shop_id）
        if shop_id is not None:
            self._check_data_isolation(parsed, sql, shop_id, result)
        
        # 7. 根据级别执行额外检查
        if self.level == ValidationLevel.STRICT:
            self._strict_checks(parsed, sql, result)
        
        # 设置最终结果
        if result.errors:
            result.is_valid = False
        
        return result
    
    def _check_statement_type(self, parsed: ParsedSQL, result: ValidationResult):
        """检查语句类型"""
        if parsed.statement_type not in self.ALLOWED_STATEMENTS:
            result.errors.append(
                f"不允许的语句类型: {parsed.statement_type.value}，只允许 SELECT 查询"
            )
    
    def _check_dangerous_patterns(self, sql: str, parsed: ParsedSQL, result: ValidationResult):
        """检查危险模式"""
        # 检查危险模式
        warnings = self.parser.check_dangerous_patterns(sql)
        result.warnings.extend(warnings)
        
        # 检查危险函数
        if parsed.ast:
            func_warnings = self.parser.check_dangerous_functions(parsed.ast)
            result.warnings.extend(func_warnings)
        
        # 严重危险模式直接报错
        critical_patterns = [
            'union select', 'union all select',
            'into outfile', 'into dumpfile',
            'load_file', 'load data'
        ]
        
        sql_lower = sql.lower()
        for pattern in critical_patterns:
            if pattern in sql_lower:
                result.errors.append(f"检测到严重安全风险: {pattern}")
    
    def _check_subqueries(self, parsed: ParsedSQL, result: ValidationResult, dialect: str = "mysql"):
        """检查子查询安全性"""
        for subquery in parsed.subqueries:
            # 递归检查子查询
            sub_result = self.validate(subquery, dialect=dialect)
            if not sub_result.is_valid:
                result.errors.append(f"子查询不安全: {sub_result.errors[0]}")
            if sub_result.warnings:
                result.warnings.extend([f"子查询警告: {w}" for w in sub_result.warnings])
    
    def _check_data_isolation(
        self, 
        parsed: ParsedSQL, 
        sql: str, 
        shop_id: int,
        result: ValidationResult
    ):
        """检查数据隔离"""
        # 检查是否包含 shop_id 条件
        has_shop_id = False
        
        # 检查 WHERE 条件
        for condition in parsed.where_conditions:
            if 'shop_id' in condition.lower():
                has_shop_id = True
                break
        
        # 检查原始 SQL（作为后备）
        if not has_shop_id:
            if f'shop_id = {shop_id}' in sql or f'shop_id={shop_id}' in sql:
                has_shop_id = True
        
        # 如果查询的表需要 shop_id 但没有，报错
        tables_needing_isolation = set(parsed.tables) & self.SHOP_TABLES
        if tables_needing_isolation and not has_shop_id:
            if self.level == ValidationLevel.STRICT:
                result.errors.append(
                    f"数据隔离违规: 查询表 {tables_needing_isolation} 缺少 shop_id 条件"
                )
            else:
                result.warnings.append(
                    f"建议添加 shop_id 条件以确保数据隔离"
                )
    
    def _strict_checks(self, parsed: ParsedSQL, sql: str, result: ValidationResult):
        """严格模式额外检查"""
        
        # 1. 检查 SELECT *
        if '*' in parsed.columns and not parsed.tables:
            result.warnings.append("使用了 SELECT *，建议明确指定列名")
        
        # 2. 检查缺少 LIMIT
        if not parsed.has_limit:
            result.warnings.append("缺少 LIMIT 子句，可能导致返回大量数据")
        
        # 3. 检查危险函数
        dangerous_funcs_in_sql = [f for f in parsed.functions if f in SQLParser.DANGEROUS_FUNCTIONS]
        if dangerous_funcs_in_sql:
            result.errors.append(f"检测到危险函数: {dangerous_funcs_in_sql}")
        
        # 4. 检查多语句（堆叠查询）
        if sql.count(';') > 0:
            # 移除末尾分号后的计数
            sql_clean = sql.rstrip(';').rstrip()
            if ';' in sql_clean:
                result.errors.append("检测到多语句查询（堆叠注入风险）")
        
        # 5. 检查注释（可能用于绕过检测）
        if '--' in sql or '/*' in sql:
            result.warnings.append("SQL 中包含注释，请确认安全性")
        
        # 6. 检查 HEX 编码
        if re.search(r'0x[0-9a-fA-F]+', sql):
            result.warnings.append("检测到 HEX 编码，可能用于绕过检测")
        
        # 7. 检查 CHAR() 函数调用
        if re.search(r'CHAR\s*\(\s*\d+', sql, re.IGNORECASE):
            result.warnings.append("检测到 CHAR() 函数，可能用于绕过检测")


# 全局实例
def get_validator(level: str = "strict") -> ASTValidator:
    """获取校验器实例"""
    level_map = {
        "strict": ValidationLevel.STRICT,
        "moderate": ValidationLevel.MODERATE,
        "lenient": ValidationLevel.LENIENT,
    }
    return ASTValidator(level_map.get(level, ValidationLevel.STRICT))


def validate_sql_ast(
    sql: str, 
    shop_id: Optional[int] = None,
    level: str = "strict",
    dialect: str = "mysql"
) -> Dict:
    """
    校验 SQL 安全性（API 接口）
    
    Args:
        sql: SQL 语句
        shop_id: 店铺 ID
        level: 校验级别
        dialect: SQL 方言
    
    Returns:
        校验结果字典
    """
    validator = get_validator(level)
    result = validator.validate(sql, shop_id, dialect=dialect)
    return result.to_dict()
