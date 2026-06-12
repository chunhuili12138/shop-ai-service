"""
查询结果解释生成模块
将 SQL 查询结果转换为易懂的自然语言描述
"""

from typing import Any, Dict, List, Optional
from langchain_core.prompts import ChatPromptTemplate
from app.llm import get_chat_llm


class ResultExplainer:
    """查询结果解释器"""
    
    def __init__(self):
        pass
    
    async def explain(
        self,
        question: str,
        sql: str,
        results: List[Dict[str, Any]],
        max_results_shown: int = 10
    ) -> str:
        """
        生成查询结果解释
        
        Args:
            question: 用户原始问题
            sql: 执行的 SQL
            results: 查询结果
            max_results_shown: 最多展示的结果数
        
        Returns:
            自然语言解释
        """
        if not results:
            return "查询结果为空，没有找到匹配的数据。"
        
        # 准备结果摘要
        result_summary = self._prepare_result_summary(results, max_results_shown)
        
        # 调用 LLM 生成解释
        explain_prompt = ChatPromptTemplate.from_template("""
你是一个数据分析助手，负责将 SQL 查询结果转换为易懂的自然语言描述。

## 用户问题
{question}

## 执行的 SQL
```sql
{sql}
```

## 查询结果（共 {total_count} 条）
{result_summary}

## 要求
1. 用简洁的中文描述查询结果
2. 突出关键数据和趋势
3. 如果是统计数据，说明具体数值
4. 如果是排名，按顺序列出
5. 使用友好的语气，避免技术术语
6. 如果结果较多，只总结主要信息

请生成结果解释：""")
        
        try:
            llm = get_chat_llm(temperature=0.3)
            chain = explain_prompt | llm
            
            response = await chain.ainvoke({
                "question": question,
                "sql": sql,
                "total_count": len(results),
                "result_summary": result_summary
            })
            
            return response.content.strip()
        
        except Exception as e:
            # 如果 LLM 调用失败，返回基本描述
            return self._generate_basic_explanation(question, results)
    
    def _prepare_result_summary(
        self,
        results: List[Dict[str, Any]],
        max_rows: int
    ) -> str:
        """准备结果摘要"""
        if not results:
            return "无数据"
        
        # 获取列名
        columns = list(results[0].keys())
        
        # 构建表格形式的摘要
        lines = []
        
        # 表头
        lines.append(" | ".join(columns))
        lines.append(" | ".join(["---"] * len(columns)))
        
        # 数据行（限制数量）
        for i, row in enumerate(results[:max_rows]):
            values = []
            for col in columns:
                val = row.get(col, "")
                # 格式化数值
                if isinstance(val, float):
                    val = f"{val:.2f}"
                elif val is None:
                    val = "NULL"
                values.append(str(val))
            lines.append(" | ".join(values))
        
        if len(results) > max_rows:
            lines.append(f"... 还有 {len(results) - max_rows} 条数据")
        
        return "\n".join(lines)
    
    def _generate_basic_explanation(
        self,
        question: str,
        results: List[Dict[str, Any]]
    ) -> str:
        """生成基本解释（LLM 调用失败时的备选方案）"""
        count = len(results)
        
        # 检测查询类型
        question_lower = question.lower()
        
        if any(kw in question_lower for kw in ["多少", "数量", "总数", "统计"]):
            # 统计类查询
            if count == 1:
                # 单行结果，可能是聚合值
                first_row = results[0]
                values = list(first_row.values())
                if len(values) == 1:
                    return f"查询结果为：{values[0]}"
                else:
                    return f"查询到 {count} 条统计结果。"
            else:
                return f"查询到 {count} 条统计数据。"
        
        elif any(kw in question_lower for kw in ["排名", "排行", "top", "最高", "最低"]):
            # 排名类查询
            return f"查询到 {count} 条排名数据，详见结果列表。"
        
        elif any(kw in question_lower for kw in ["列表", "明细", "详情"]):
            # 列表类查询
            return f"查询到 {count} 条记录。"
        
        else:
            return f"查询完成，共返回 {count} 条结果。"
    
    async def generate_insights(
        self,
        question: str,
        results: List[Dict[str, Any]]
    ) -> List[str]:
        """
        生成数据洞察
        
        Args:
            question: 用户问题
            results: 查询结果
        
        Returns:
            洞察列表
        """
        if not results or len(results) < 2:
            return []
        
        insights_prompt = ChatPromptTemplate.from_template("""
基于以下查询结果，生成 2-3 个数据洞察或建议。

## 用户问题
{question}

## 查询结果（共 {count} 条）
{result_summary}

## 要求
1. 洞察要基于数据，不要编造
2. 每个洞察用一句话描述
3. 如果发现异常或趋势，指出来
4. 可以给出简单的建议

请直接返回洞察列表，每行一个：""")
        
        try:
            result_summary = self._prepare_result_summary(results, 5)
            
            llm = get_chat_llm(temperature=0.3)
            chain = insights_prompt | llm
            
            response = await chain.ainvoke({
                "question": question,
                "count": len(results),
                "result_summary": result_summary
            })
            
            # 解析洞察列表
            insights = [
                line.strip().lstrip("0123456789.-) ")
                for line in response.content.strip().split("\n")
                if line.strip()
            ]
            
            return insights[:3]  # 最多返回 3 个洞察
        
        except Exception:
            return []


# 全局实例
result_explainer = ResultExplainer()


async def explain_query_result(
    question: str,
    sql: str,
    results: List[Dict[str, Any]]
) -> str:
    """解释查询结果"""
    return await result_explainer.explain(question, sql, results)


async def generate_data_insights(
    question: str,
    results: List[Dict[str, Any]]
) -> List[str]:
    """生成数据洞察"""
    return await result_explainer.generate_insights(question, results)
