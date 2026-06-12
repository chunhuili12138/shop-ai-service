"""NL2SQL模块 - 自然语言转SQL

包含以下子模块：
- schema: 数据库 Schema 定义
- schema_linker: 智能 Schema Linking
- fewshot: 静态 Few-shot 样例
- fewshot_vector: 向量检索 Few-shot
- safety: SQL 安全校验（基础版）
- executor: SQL 执行器
- self_correction: SQL 自修正
- result_explainer: 结果解释生成
- router: API 路由

Day 3 新增：
- sql_parser: SQL AST 解析器
- ast_validator: AST 级别安全校验
- injection_detector: SQL 注入检测
- query_optimizer: 查询优化建议
- sql_fixer: SQL 智能修正
- security_router: 安全模块 API 路由
"""

from app.nl2sql.schema import get_schema_info
from app.nl2sql.schema_linker import get_schema_link, get_relevant_schema
from app.nl2sql.fewshot_vector import get_few_shot_examples, format_few_shot_prompt
from app.nl2sql.safety import validate_sql, sanitize_sql
from app.nl2sql.executor import execute_sql, execute_sql_with_retry
from app.nl2sql.self_correction import correct_sql
from app.nl2sql.result_explainer import explain_query_result, generate_data_insights

# Day 3 新增导入
from app.nl2sql.sql_parser import parse_sql, check_sql_dangerous
from app.nl2sql.ast_validator import validate_sql_ast
from app.nl2sql.injection_detector import detect_injection
from app.nl2sql.query_optimizer import optimize_query
from app.nl2sql.sql_fixer import fix_sql, fix_sql_for_injection

__all__ = [
    # Day 2 模块
    "get_schema_info",
    "get_schema_link",
    "get_relevant_schema",
    "get_few_shot_examples",
    "format_few_shot_prompt",
    "validate_sql",
    "sanitize_sql",
    "execute_sql",
    "execute_sql_with_retry",
    "correct_sql",
    "explain_query_result",
    "generate_data_insights",
    # Day 3 模块
    "parse_sql",
    "check_sql_dangerous",
    "validate_sql_ast",
    "detect_injection",
    "optimize_query",
    "fix_sql",
    "fix_sql_for_injection",
]
