"""
日期时间与计算工具
提供日期获取、日期计算、算术计算等基础工具
"""

from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from datetime import datetime, timedelta
import re


# ==================== Input Schemas ====================

class GetCurrentDatetimeInput(BaseModel):
    """获取当前日期时间参数"""
    format: Optional[str] = Field(
        default="full",
        description="输出格式: full=完整日期时间, date=仅日期, time=仅时间, timestamp=时间戳"
    )


class CalculateDateInput(BaseModel):
    """日期计算参数"""
    base_date: Optional[str] = Field(
        default=None,
        description="基准日期，格式: yyyy-MM-dd（可选，默认今天）"
    )
    days: Optional[int] = Field(
        default=0,
        description="天数偏移（正数=未来，负数=过去）"
    )
    months: Optional[int] = Field(
        default=0,
        description="月份偏移（正数=未来，负数=过去）"
    )
    weeks: Optional[int] = Field(
        default=0,
        description="周数偏移（正数=未来，负数=过去）"
    )


class CalculatorInput(BaseModel):
    """算术计算参数"""
    expression: str = Field(
        description="数学表达式，如: 100 + 200, 1000 * 0.8, (50 + 30) / 2"
    )


class FormatDatetimeInput(BaseModel):
    """格式化日期时间参数"""
    datetime_str: str = Field(
        description="日期时间字符串，如: 2026-06-29, 2026-06-29 14:30:00"
    )
    format: Optional[str] = Field(
        default="yyyy-MM-dd",
        description="目标输出格式: yyyy-MM-dd, yyyy年MM月dd日, MM/dd, weekday=星期几"
    )


# ==================== Tools ====================

@tool(args_schema=GetCurrentDatetimeInput)
def get_current_datetime(format: str = "full") -> str:
    """
    获取当前日期和时间。
    用于回答用户关于"今天是几号"、"现在几点"等问题。
    """
    now = datetime.now()
    
    if format == "full":
        return f"当前日期时间: {now.strftime('%Y-%m-%d %H:%M:%S')}\n星期: {['一','二','三','四','五','六','日'][now.weekday()]}"
    elif format == "date":
        return f"当前日期: {now.strftime('%Y-%m-%d')}\n星期: {['一','二','三','四','五','六','日'][now.weekday()]}"
    elif format == "time":
        return f"当前时间: {now.strftime('%H:%M:%S')}"
    elif format == "timestamp":
        return f"当前时间戳: {int(now.timestamp())}"
    else:
        return f"当前日期时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"


@tool(args_schema=CalculateDateInput)
def calculate_date(base_date: Optional[str] = None, days: int = 0, months: int = 0, weeks: int = 0) -> str:
    """
    日期加减计算。
    用于回答"7天前是几号"、"上个月今天"、"下周一是几号"等问题。
    """
    try:
        if base_date:
            base = datetime.strptime(base_date, "%Y-%m-%d")
        else:
            base = datetime.now()
        
        # 计算偏移
        result = base + timedelta(days=days + weeks * 7)
        
        # 月份偏移需要特殊处理
        if months != 0:
            month = base.month + months
            year = base.year
            while month > 12:
                month -= 12
                year += 1
            while month < 1:
                month += 12
                year -= 1
            day = min(base.day, [31,29 if year%4==0 and (year%100!=0 or year%400==0) else 28,31,30,31,30,31,31,30,31,30,31][month-1])
            result = result.replace(year=year, month=month, day=day)
        
        weekday = ['一','二','三','四','五','六','日'][result.weekday()]
        
        return f"计算结果: {result.strftime('%Y-%m-%d')}\n星期: {weekday}\n说明: {base.strftime('%Y-%m-%d')} {'+' if days+weeks*7>=0 else ''}{days+weeks*7}天 {'+' if months>=0 else ''}{months}月"
    except Exception as e:
        return f"日期计算失败: {str(e)}"


@tool(args_schema=CalculatorInput)
def calculator(expression: str) -> str:
    """
    数学计算器。
    用于进行精确的数学计算，避免LLM计算错误。
    支持: +, -, *, /, //, %, **, 括号
    """
    try:
        # 安全检查：只允许数字和运算符
        safe_pattern = re.compile(r'^[\d\s\+\-\*\/\.\(\)\%\*]+$')
        if not safe_pattern.match(expression):
            return f"计算错误: 表达式包含不允许的字符"
        
        # 替换中文符号
        expression = expression.replace('×', '*').replace('÷', '/').replace('（', '(').replace('）', ')')
        
        # 计算
        result = eval(expression)
        
        # 格式化结果
        if isinstance(result, float):
            if result == int(result):
                return f"计算结果: {expression} = {int(result)}"
            else:
                return f"计算结果: {expression} = {result:.2f}"
        else:
            return f"计算结果: {expression} = {result}"
    except ZeroDivisionError:
        return "计算错误: 除数不能为零"
    except Exception as e:
        return f"计算错误: {str(e)}"


@tool(args_schema=FormatDatetimeInput)
def format_datetime(datetime_str: str, format: str = "yyyy-MM-dd") -> str:
    """
    格式化日期时间。
    将日期时间字符串转换为指定格式。
    """
    try:
        # 尝试解析日期时间
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"]:
            try:
                dt = datetime.strptime(datetime_str, fmt)
                break
            except ValueError:
                continue
        else:
            return f"无法解析日期: {datetime_str}"
        
        # 格式化输出
        if format == "yyyy-MM-dd":
            return f"格式化结果: {dt.strftime('%Y-%m-%d')}"
        elif format == "yyyy年MM月dd日":
            return f"格式化结果: {dt.strftime('%Y年%m月%d日')}"
        elif format == "MM/dd":
            return f"格式化结果: {dt.strftime('%m/%d')}"
        elif format == "weekday":
            weekday = ['一','二','三','四','五','六','日'][dt.weekday()]
            return f"格式化结果: {dt.strftime('%Y-%m-%d')} 星期{weekday}"
        else:
            return f"格式化结果: {dt.strftime(format)}"
    except Exception as e:
        return f"格式化失败: {str(e)}"


# 工具列表
DATETIME_TOOLS = [
    get_current_datetime,
    calculate_date,
    calculator,
    format_datetime,
]
