"""
SQL Self-Correction 自修正模块
当 SQL 执行失败时，自动分析错误并修正
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from langchain_core.prompts import ChatPromptTemplate
from app.llm import get_chat_llm
from app.nl2sql.schema import get_schema_info


@dataclass
class CorrectionResult:
    """修正结果"""
    original_sql: str
    corrected_sql: str
    error_message: str
    correction_type: str  # syntax, column, table, logic
    success: bool
    attempts: int


# 常见 SQL 错误模式
ERROR_PATTERNS = {
    "column_not_found": {
        "pattern": r"Unknown column '(\w+)'",
        "description": "列名不存在",
        "hint": "检查列名是否正确，或使用表别名"
    },
    "table_not_found": {
        "pattern": r"Table '.*' doesn't exist",
        "description": "表名不存在",
        "hint": "检查表名是否正确"
    },
    "syntax_error": {
        "pattern": r"You have an error in your SQL syntax",
        "description": "SQL 语法错误",
        "hint": "检查 SQL 语法，特别是括号、引号和关键字"
    },
    "ambiguous_column": {
        "pattern": r"Column '(\w+)' in field list is ambiguous",
        "description": "列名歧义",
        "hint": "使用表别名指定列的来源表"
    },
    "group_by_error": {
        "pattern": r"isn't in GROUP BY",
        "description": "GROUP BY 错误",
        "hint": "确保 SELECT 中的非聚合列都在 GROUP BY 中"
    },
    "function_error": {
        "pattern": r"FUNCTION .* does not exist",
        "description": "函数不存在",
        "hint": "检查函数名是否正确，MySQL 版本是否支持"
    }
}


class SQLSelfCorrection:
    """SQL 自修正器"""
    
    def __init__(self, max_attempts: int = 3):
        """
        初始化自修正器
        
        Args:
            max_attempts: 最大修正尝试次数
        """
        self.max_attempts = max_attempts
    
    def classify_error(self, error_message: str) -> Tuple[str, str]:
        """
        分类 SQL 错误
        
        Args:
            error_message: 错误信息
        
        Returns:
            (错误类型, 提示信息)
        """
        for error_type, info in ERROR_PATTERNS.items():
            if re.search(info["pattern"], error_message, re.IGNORECASE):
                return error_type, info["hint"]
        
        return "unknown", "请检查 SQL 语句的语法和表结构"
    
    def extract_error_details(self, error_message: str) -> Dict:
        """
        提取错误详情
        
        Args:
            error_message: 错误信息
        
        Returns:
            错误详情字典
        """
        details = {"raw_error": error_message}
        
        # 提取列名
        column_match = re.search(r"Unknown column '(\w+)'", error_message)
        if column_match:
            details["unknown_column"] = column_match.group(1)
        
        # 提取表名
        table_match = re.search(r"Table '(.*?)' doesn't exist", error_message)
        if table_match:
            details["unknown_table"] = table_match.group(1)
        
        return details
    
    async def correct_sql(
        self,
        original_sql: str,
        error_message: str,
        question: str,
        schema_info: str = None
    ) -> CorrectionResult:
        """
        修正 SQL 语句
        
        Args:
            original_sql: 原始 SQL
            error_message: 错误信息
            question: 用户问题
            schema_info: Schema 信息（可选）
        
        Returns:
            修正结果
        """
        if schema_info is None:
            schema_info = get_schema_info()
        
        # 分类错误
        error_type, hint = self.classify_error(error_message)
        error_details = self.extract_error_details(error_message)
        
        # 构建修正提示
        correction_prompt = self._build_correction_prompt(
            original_sql=original_sql,
            error_message=error_message,
            error_type=error_type,
            hint=hint,
            question=question,
            schema_info=schema_info
        )
        
        # 调用 LLM 修正
        try:
            llm = get_chat_llm(temperature=0)
            prompt = ChatPromptTemplate.from_template(correction_prompt)
            chain = prompt | llm
            
            response = await chain.ainvoke({
                "original_sql": original_sql,
                "error_message": error_message,
                "question": question,
                "schema": schema_info
            })
            
            corrected_sql = self._extract_sql(response.content)
            
            return CorrectionResult(
                original_sql=original_sql,
                corrected_sql=corrected_sql,
                error_message=error_message,
                correction_type=error_type,
                success=True,
                attempts=1
            )
        
        except Exception as e:
            return CorrectionResult(
                original_sql=original_sql,
                corrected_sql=original_sql,
                error_message=f"修正失败: {str(e)}",
                correction_type=error_type,
                success=False,
                attempts=1
            )
    
    def _build_correction_prompt(
        self,
        original_sql: str,
        error_message: str,
        error_type: str,
        hint: str,
        question: str,
        schema_info: str
    ) -> str:
        """构建修正提示词"""
        
        prompt_template = """你是一个 SQL 专家，负责修正错误的 SQL 语句。

## 原始问题
{question}

## 数据库结构
{schema}

## 错误的 SQL
```sql
{original_sql}
```

## 错误信息
{error_message}

## 错误类型
{error_type}

## 修正提示
{hint}

## 修正要求
1. 仔细分析错误原因
2. 参考数据库结构，使用正确的表名和列名
3. 确保修正后的 SQL 语法正确
4. 保持查询逻辑与原始问题一致
5. 所有查询必须包含 shop_id 条件（数据隔离）

请直接返回修正后的 SQL 语句，不要包含其他解释："""
        
        return prompt_template.format(
            question=question,
            schema=schema_info,
            original_sql=original_sql,
            error_message=error_message,
            error_type=error_type,
            hint=hint
        )
    
    def _extract_sql(self, content: str) -> str:
        """从 LLM 响应中提取 SQL"""
        # 尝试提取代码块中的 SQL
        sql_match = re.search(r'```(?:sql)?\s*(.*?)```', content, re.DOTALL)
        if sql_match:
            return sql_match.group(1).strip()
        
        # 如果没有代码块，直接返回内容（清理后）
        sql = content.strip()
        # 移除可能的前缀说明
        sql = re.sub(r'^.*?(?:SELECT|WITH)', 'SELECT', sql, count=1, flags=re.IGNORECASE | re.DOTALL)
        return sql
    
    async def correct_with_retry(
        self,
        original_sql: str,
        error_message: str,
        question: str,
        execute_fn,
        schema_info: str = None
    ) -> CorrectionResult:
        """
        带重试的修正
        
        Args:
            original_sql: 原始 SQL
            error_message: 错误信息
            question: 用户问题
            execute_fn: 执行 SQL 的函数
            schema_info: Schema 信息
        
        Returns:
            修正结果
        """
        current_sql = original_sql
        current_error = error_message
        
        for attempt in range(self.max_attempts):
            # 尝试修正
            result = await self.correct_sql(
                current_sql,
                current_error,
                question,
                schema_info
            )
            
            if not result.success:
                continue
            
            # 尝试执行修正后的 SQL
            try:
                execute_fn(result.corrected_sql)
                result.attempts = attempt + 1
                return result
            except Exception as e:
                current_sql = result.corrected_sql
                current_error = str(e)
        
        # 所有尝试都失败
        return CorrectionResult(
            original_sql=original_sql,
            corrected_sql=current_sql,
            error_message=f"经过 {self.max_attempts} 次尝试仍无法修正",
            correction_type="max_attempts_exceeded",
            success=False,
            attempts=self.max_attempts
        )


# 全局实例
sql_corrector = SQLSelfCorrection()


async def correct_sql(
    original_sql: str,
    error_message: str,
    question: str
) -> CorrectionResult:
    """修正 SQL 语句"""
    return await sql_corrector.correct_sql(original_sql, error_message, question)


async def correct_sql_with_retry(
    original_sql: str,
    error_message: str,
    question: str,
    execute_fn
) -> CorrectionResult:
    """带重试的修正"""
    return await sql_corrector.correct_with_retry(
        original_sql, error_message, question, execute_fn
    )
