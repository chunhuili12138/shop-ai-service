"""
SQL 智能修正模块
基于 sqlglot AST 进行精确的 SQL 修正
"""

import re
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError
from app.nl2sql.sql_parser import SQLParser, ParsedSQL, parse_sql


@dataclass
class FixSuggestion:
    """修正建议"""
    original: str
    suggested: str
    reason: str
    confidence: float  # 0-1


@dataclass
class FixResult:
    """修正结果"""
    original_sql: str
    fixed_sql: str
    fixes_applied: List[FixSuggestion] = field(default_factory=list)
    is_modified: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "original_sql": self.original_sql,
            "fixed_sql": self.fixed_sql,
            "is_modified": self.is_modified,
            "fix_count": len(self.fixes_applied),
            "fixes": [
                {
                    "original": f.original,
                    "suggested": f.suggested,
                    "reason": f.reason,
                    "confidence": f.confidence
                }
                for f in self.fixes_applied
            ]
        }


class SQLFixer:
    """SQL 智能修正器 - 基于 sqlglot"""
    
    # 常见拼写错误映射
    COMMON_TYPOS = {
        'selct': 'select',
        'slect': 'select',
        'frome': 'from',
        'form': 'from',
        'wehere': 'where',
        'whre': 'where',
        'gruop': 'group',
        'gropu': 'group',
        'oredr': 'order',
        'oder': 'order',
        'lmit': 'limit',
        'limt': 'limit',
        'havng': 'having',
        'havig': 'having',
        'distict': 'distinct',
        'distint': 'distinct',
        'betwee': 'between',
        'betwen': 'between',
        'exists': 'exists',
        'exist': 'exists',
        'insert': 'insert',
        'insrt': 'insert',
        'update': 'update',
        'udpat': 'update',
        'delete': 'delete',
        'delet': 'delete',
    }
    
    # 常见函数名修正
    FUNCTION_TYPOS = {
        'cout': 'count',
        'coutn': 'count',
        'summ': 'sum',
        'avgerage': 'avg',
        'maximun': 'max',
        'minimun': 'min',
        'concet': 'concat',
        'group_concet': 'group_concat',
        'date_formate': 'date_format',
        'date_formt': 'date_format',
        'ifnl': 'ifnull',
        'coalasce': 'coalesce',
    }
    
    def __init__(self):
        self.parser = SQLParser()
    
    def fix(self, sql: str, dialect: str = "mysql") -> FixResult:
        """
        修正 SQL 语句
        
        Args:
            sql: SQL 语句
            dialect: SQL 方言
        
        Returns:
            修正结果
        """
        result = FixResult(original_sql=sql, fixed_sql=sql)
        
        # 1. 基础清理
        sql = self._basic_cleanup(sql, result)
        
        # 2. 修正拼写错误
        sql = self._fix_typos(sql, result)
        
        # 3. 修正函数名
        sql = self._fix_function_names(sql, result)
        
        # 4. 尝试用 sqlglot 解析和重新生成 SQL（自动修正格式）
        sql = self._fix_with_sqlglot(sql, result, dialect)
        
        # 5. 修正括号平衡
        sql = self._fix_parentheses(sql, result)
        
        # 6. 修正引号平衡
        sql = self._fix_quotes(sql, result)
        
        result.fixed_sql = sql
        result.is_modified = (result.original_sql != result.fixed_sql)
        
        return result
    
    def _basic_cleanup(self, sql: str, result: FixResult) -> str:
        """基础清理"""
        original = sql
        
        # 移除多余空白
        sql = re.sub(r'\s+', ' ', sql).strip()
        
        # 移除首尾空白
        sql = sql.strip()
        
        if sql != original:
            result.fixes_applied.append(FixSuggestion(
                original=original,
                suggested=sql,
                reason="清理多余空白",
                confidence=1.0
            ))
        
        return sql
    
    def _fix_typos(self, sql: str, result: FixResult) -> str:
        """修正拼写错误"""
        words = sql.split()
        fixed_words = []
        modified = False
        
        for word in words:
            word_lower = word.lower()
            if word_lower in self.COMMON_TYPOS:
                fixed = self.COMMON_TYPOS[word_lower]
                # 保持原始大小写风格
                if word.islower():
                    pass  # 已经是小写
                elif word.isupper():
                    fixed = fixed.upper()
                elif word[0].isupper():
                    fixed = fixed.capitalize()
                
                fixed_words.append(fixed)
                modified = True
                
                result.fixes_applied.append(FixSuggestion(
                    original=word,
                    suggested=fixed,
                    reason=f"修正拼写错误: {word} -> {fixed}",
                    confidence=0.9
                ))
            else:
                fixed_words.append(word)
        
        if modified:
            sql = ' '.join(fixed_words)
        
        return sql
    
    def _fix_function_names(self, sql: str, result: FixResult) -> str:
        """修正函数名"""
        modified = False
        
        for typo, correct in self.FUNCTION_TYPOS.items():
            pattern = re.compile(r'\b' + typo + r'\s*\(', re.IGNORECASE)
            if pattern.search(sql):
                sql = pattern.sub(correct + '(', sql)
                modified = True
                
                result.fixes_applied.append(FixSuggestion(
                    original=typo,
                    suggested=correct,
                    reason=f"修正函数名: {typo} -> {correct}",
                    confidence=0.85
                ))
        
        return sql
    
    def _fix_with_sqlglot(self, sql: str, result: FixResult, dialect: str = "mysql") -> str:
        """使用 sqlglot 修正和格式化 SQL"""
        try:
            # 尝试解析
            ast = parse_one(sql, dialect=dialect)
            
            # 重新生成 SQL（自动格式化）
            fixed_sql = ast.sql(dialect=dialect)
            
            if fixed_sql != sql:
                result.fixes_applied.append(FixSuggestion(
                    original=sql,
                    suggested=fixed_sql,
                    reason="使用 sqlglot 格式化 SQL",
                    confidence=0.95
                ))
                return fixed_sql
            
        except SqlglotError as e:
            # 解析失败，尝试清理后重试
            result.fixes_applied.append(FixSuggestion(
                original=sql,
                suggested=sql,
                reason=f"sqlglot 解析失败: {str(e)}",
                confidence=0.5
            ))
        
        return sql
    
    def _fix_parentheses(self, sql: str, result: FixResult) -> str:
        """修正括号平衡"""
        open_count = sql.count('(')
        close_count = sql.count(')')
        
        if open_count == close_count:
            return sql
        
        original = sql
        
        if open_count > close_count:
            # 缺少右括号
            missing = open_count - close_count
            sql = sql + ')' * missing
            
            result.fixes_applied.append(FixSuggestion(
                original=original,
                suggested=sql,
                reason=f"添加 {missing} 个缺少的右括号",
                confidence=0.7
            ))
        else:
            # 多余右括号，尝试从末尾移除
            excess = close_count - open_count
            for _ in range(excess):
                if sql.endswith(')'):
                    sql = sql[:-1]
            
            result.fixes_applied.append(FixSuggestion(
                original=original,
                suggested=sql,
                reason=f"移除 {excess} 个多余的右括号",
                confidence=0.6
            ))
        
        return sql
    
    def _fix_quotes(self, sql: str, result: FixResult) -> str:
        """修正引号平衡"""
        single_quote_count = sql.count("'")
        
        if single_quote_count % 2 == 0:
            return sql
        
        original = sql
        
        # 尝试在末尾添加引号
        sql = sql + "'"
        
        result.fixes_applied.append(FixSuggestion(
            original=original,
            suggested=sql,
            reason="添加缺少的单引号以平衡引号",
            confidence=0.5
        ))
        
        return sql
    
    def fix_for_injection(self, sql: str, dialect: str = "mysql") -> FixResult:
        """
        修正注入风险的 SQL
        
        Args:
            sql: SQL 语句
            dialect: SQL 方言
        
        Returns:
            修正结果
        """
        result = FixResult(original_sql=sql, fixed_sql=sql)
        
        # 移除危险函数
        dangerous_funcs = ['sleep', 'benchmark', 'load_file', 'extractvalue', 'updatexml']
        for func in dangerous_funcs:
            pattern = re.compile(func + r'\s*\([^)]*\)', re.IGNORECASE)
            if pattern.search(sql):
                sql = pattern.sub('NULL', sql)
                result.fixes_applied.append(FixSuggestion(
                    original=func,
                    suggested='NULL',
                    reason=f"移除危险函数 {func}",
                    confidence=1.0
                ))
        
        # 移除 UNION 注入
        sql = re.sub(r'UNION\s+(ALL\s+)?SELECT\s+.*$', '', sql, flags=re.IGNORECASE)
        
        # 移除堆叠查询
        sql = sql.split(';')[0].strip()
        
        # 尝试用 sqlglot 格式化
        try:
            ast = parse_one(sql, dialect=dialect)
            sql = ast.sql(dialect=dialect)
        except SqlglotError:
            pass
        
        result.fixed_sql = sql
        result.is_modified = (result.original_sql != result.fixed_sql)
        
        return result


# 全局实例
sql_fixer = SQLFixer()


def fix_sql(sql: str, dialect: str = "mysql") -> Dict:
    """
    修正 SQL（API 接口）
    
    Args:
        sql: SQL 语句
        dialect: SQL 方言
    
    Returns:
        修正结果字典
    """
    result = sql_fixer.fix(sql, dialect)
    return result.to_dict()


def fix_sql_for_injection(sql: str, dialect: str = "mysql") -> Dict:
    """
    修正注入风险的 SQL（API 接口）
    
    Args:
        sql: SQL 语句
        dialect: SQL 方言
    
    Returns:
        修正结果字典
    """
    result = sql_fixer.fix_for_injection(sql, dialect)
    return result.to_dict()
