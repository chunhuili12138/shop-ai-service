"""
NL2SQL 安全模块路由
提供 SQL 安全校验、注入检测、优化建议等 API
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.nl2sql.ast_validator import validate_sql_ast
from app.nl2sql.injection_detector import detect_injection
from app.nl2sql.query_optimizer import optimize_query
from app.nl2sql.sql_fixer import fix_sql, fix_sql_for_injection
from app.nl2sql.sql_parser import parse_sql, check_sql_dangerous

router = APIRouter()


# ==================== Request / Response Models ====================

class SQLValidationRequest(BaseModel):
    """SQL 校验请求"""
    sql: str
    shop_id: Optional[int] = None
    level: str = "strict"  # strict, moderate, lenient


class SQLValidationResponse(BaseModel):
    """SQL 校验响应"""
    is_valid: bool
    level: str
    errors: list
    warnings: list
    error_count: int
    warning_count: int


class InjectionDetectionRequest(BaseModel):
    """注入检测请求"""
    sql: str


class InjectionDetectionResponse(BaseModel):
    """注入检测响应"""
    is_safe: bool
    risk_score: int
    detection_count: int
    high_risk_count: int
    detections: list


class OptimizationRequest(BaseModel):
    """优化建议请求"""
    sql: str


class OptimizationResponse(BaseModel):
    """优化建议响应"""
    score: int
    suggestion_count: int
    high_priority_count: int
    suggestions: list


class SQLFixRequest(BaseModel):
    """SQL 修正请求"""
    sql: str
    fix_injection: bool = False


class SQLFixResponse(BaseModel):
    """SQL 修正响应"""
    original_sql: str
    fixed_sql: str
    is_modified: bool
    fix_count: int
    fixes: list


class SQLParseRequest(BaseModel):
    """SQL 解析请求"""
    sql: str


class SQLParseResponse(BaseModel):
    """SQL 解析响应"""
    statement_type: str
    tables: list
    columns: list
    where_conditions: list
    join_tables: list
    subqueries: list
    functions: list
    has_limit: bool
    has_order_by: bool
    has_group_by: bool
    is_valid: bool
    parse_errors: list


class ComprehensiveCheckRequest(BaseModel):
    """综合检查请求"""
    sql: str
    shop_id: Optional[int] = None
    level: str = "strict"


class ComprehensiveCheckResponse(BaseModel):
    """综合检查响应"""
    sql: str
    is_safe: bool
    validation: dict
    injection: dict
    optimization: dict
    parsed: dict
    summary: dict


# ==================== Endpoints ====================

@router.post("/validate", response_model=SQLValidationResponse)
async def validate_sql(request: SQLValidationRequest):
    """
    SQL 安全校验
    
    基于 AST 分析的精确安全校验，检测：
    - 语句类型（只允许 SELECT）
    - 危险函数和模式
    - 子查询安全性
    - 数据隔离（shop_id）
    """
    try:
        result = validate_sql_ast(
            sql=request.sql,
            shop_id=request.shop_id,
            level=request.level
        )
        return SQLValidationResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"校验失败: {str(e)}")


@router.post("/detect-injection", response_model=InjectionDetectionResponse)
async def detect_sql_injection(request: InjectionDetectionRequest):
    """
    SQL 注入检测
    
    深度检测各种注入攻击模式：
    - UNION 注入
    - 时间盲注（SLEEP, BENCHMARK）
    - 布尔盲注
    - 报错注入
    - 堆叠查询
    - 编码绕过
    - 注释绕过
    - 逻辑操纵
    """
    try:
        result = detect_injection(request.sql)
        return InjectionDetectionResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检测失败: {str(e)}")


@router.post("/optimize", response_model=OptimizationResponse)
async def get_optimization_suggestions(request: OptimizationRequest):
    """
    查询优化建议
    
    分析 SQL 性能并给出优化建议：
    - 索引使用
    - SELECT * 问题
    - LIMIT 缺失
    - 子查询优化
    - JOIN 优化
    - WHERE 条件优化
    - 函数使用优化
    - LIKE 模式优化
    """
    try:
        result = optimize_query(request.sql)
        return OptimizationResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@router.post("/fix", response_model=SQLFixResponse)
async def fix_sql_statement(request: SQLFixRequest):
    """
    SQL 智能修正
    
    自动修正 SQL 中的问题：
    - 拼写错误
    - 函数名错误
    - 括号/引号平衡
    - 逗号问题
    - 空格问题
    
    如果 fix_injection=True，还会移除注入风险代码
    """
    try:
        if request.fix_injection:
            result = fix_sql_for_injection(request.sql)
        else:
            result = fix_sql(request.sql)
        return SQLFixResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"修正失败: {str(e)}")


@router.post("/parse", response_model=SQLParseResponse)
async def parse_sql_statement(request: SQLParseRequest):
    """
    SQL 解析
    
    将 SQL 解析为结构化对象：
    - 语句类型
    - 表名
    - 列名
    - WHERE 条件
    - JOIN 表
    - 子查询
    - 函数
    """
    try:
        result = parse_sql(request.sql)
        return SQLParseResponse(
            statement_type=result.statement_type.value,
            tables=result.tables,
            columns=result.columns,
            where_conditions=result.where_conditions,
            join_tables=result.join_tables,
            subqueries=result.subqueries,
            functions=result.functions,
            has_limit=result.has_limit,
            has_order_by=result.has_order_by,
            has_group_by=result.has_group_by,
            is_valid=result.is_valid,
            parse_errors=result.parse_errors
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")


@router.post("/comprehensive-check", response_model=ComprehensiveCheckResponse)
async def comprehensive_check(request: ComprehensiveCheckRequest):
    """
    综合安全检查
    
    一次性执行所有检查：
    1. SQL 解析
    2. 安全校验（AST）
    3. 注入检测
    4. 优化建议
    
    返回综合报告
    """
    try:
        # 1. SQL 解析
        parsed = parse_sql(request.sql)
        parsed_dict = {
            "statement_type": parsed.statement_type.value,
            "tables": parsed.tables,
            "columns": parsed.columns,
            "is_valid": parsed.is_valid,
            "parse_errors": parsed.parse_errors
        }
        
        # 2. 安全校验
        validation = validate_sql_ast(
            sql=request.sql,
            shop_id=request.shop_id,
            level=request.level
        )
        
        # 3. 注入检测
        injection = detect_injection(request.sql)
        
        # 4. 优化建议
        optimization = optimize_query(request.sql)
        
        # 5. 生成摘要
        is_safe = (
            validation.get("is_valid", False) and
            injection.get("is_safe", False)
        )
        
        summary = {
            "is_safe": is_safe,
            "statement_type": parsed.statement_type.value,
            "table_count": len(parsed.tables),
            "has_shop_id": request.shop_id is not None,
            "validation_errors": validation.get("error_count", 0),
            "injection_risk_score": injection.get("risk_score", 0),
            "optimization_score": optimization.get("score", 100),
            "recommendation": _get_recommendation(is_safe, validation, injection, optimization)
        }
        
        return ComprehensiveCheckResponse(
            sql=request.sql,
            is_safe=is_safe,
            validation=validation,
            injection=injection,
            optimization=optimization,
            parsed=parsed_dict,
            summary=summary
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"综合检查失败: {str(e)}")


def _get_recommendation(
    is_safe: bool,
    validation: dict,
    injection: dict,
    optimization: dict
) -> str:
    """生成综合建议"""
    recommendations = []
    
    if not is_safe:
        recommendations.append("SQL 存在安全风险，需要修正后才能执行")
    
    if validation.get("error_count", 0) > 0:
        recommendations.append(f"有 {validation['error_count']} 个安全校验错误需要修复")
    
    if injection.get("risk_score", 0) > 50:
        recommendations.append(f"注入风险分数较高（{injection['risk_score']}），建议检查并修正")
    
    if optimization.get("score", 100) < 70:
        recommendations.append(f"查询优化分数较低（{optimization['score']}），建议优化")
    
    if not recommendations:
        return "SQL 安全且性能良好，可以执行"
    
    return "；".join(recommendations) + "。"
