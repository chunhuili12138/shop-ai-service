"""
NL2SQL Agent - 数据查询 Agent
调用现有 NL2SQL 模块进行数据查询
集成经验池和 MySQL 规则库
"""

import re
import asyncio
from datetime import datetime
from typing import Optional, List
from langchain_core.messages import HumanMessage
from app.llm import get_chat_llm
from app.common.user_context import UserContext
from app.multi_agent.protocol import AgentResult, AgentType
from app.nl2sql.schema import get_schema_info
from app.nl2sql.schema_linker import get_relevant_schema
from app.nl2sql.fewshot_vector import get_few_shot_examples, format_few_shot_prompt
from app.nl2sql.safety import validate_sql, sanitize_sql, add_limit, add_shop_filter
from app.nl2sql.executor import execute_sql_with_retry, format_results_for_llm
from app.experience.pool import get_experience_pool
from app.nl2sql.mysql_rules import ALL_MYSQL_RULES
from app.utils.json_parser import safe_parse_json


# SQL 生成 Prompt(集成 CoT 推理、经验池和 MySQL 规则)
SQL_GENERATION_PROMPT = """你是一个专业的 MySQL 数据分析专家，负责将自然语言问题转换为 SQL 查询。

当前日期：{current_date}

## 数据库方言
MySQL 8.0

## 数据库结构
{relevant_schema}

## 相关示例
{few_shot_prompt}

{experience_prompt}

## 业务规则（重要）

### 收入相关查询

1. **"营收/营业额/销售额/订单金额"** → 查 `purchases` 表的 `paid_amount` 字段
   - 这是顾客的**订单金额**，包含已核销和未核销的订单
   - SQL: `SELECT COALESCE(SUM(p.paid_amount), 0) FROM purchases p WHERE p.shop_id = :shop_id AND p.status = 1`

2. **"实际收入/确认收入/核销收入"** → 查 `revenue_records` 表的 `amount` 字段
   - 这是**实际核销确认的收入**，只有顾客消费后才会计入
   - SQL: `SELECT COALESCE(SUM(rr.amount), 0) FROM revenue_records rr WHERE rr.shop_id = :shop_id`

3. **"收入/进账"** → 默认查 `revenue_records` 表（更准确反映实际收入）

### 支出相关查询

- **"支出/花费/成本"** → 查 `expenses` 表的 `amount` 字段

### 顾客相关查询

- **"新顾客"** → 查 `customers` 表，按 `created_at` 筛选
- **"活跃顾客"** → 查 `purchases` 表，按 `customer_id` 去重

### 退款相关查询

- **"退款金额"** → 查 `refund_records` 表的 `refund_amount` 字段
- **"退款状态"** → status: 1=处理中, 2=已完成, 3=已拒绝

## 用户问题
{task}

{mysql_rules}

## 输出要求（必须遵守）
1. **只返回 SQL 语句**，不要返回任何解释、分析、思考过程
2. 不要返回 markdown 代码块或 "```sql"
3. 直接返回 SELECT 语句

## SQL 规则
1. 使用表别名（如 c=customers, p=purchases）
2. 所有列必须带表别名
3. 子查询必须有别名
4. WHERE 条件中使用 p.shop_id = :shop_id
5. **日期过滤必须使用 NOW() 函数，禁止硬编码年份**
   - "本月" → YEAR(列) = YEAR(NOW()) AND MONTH(列) = MONTH(NOW())
   - "上个月" → YEAR(列) = YEAR(DATE_SUB(NOW(), INTERVAL 1 MONTH)) AND MONTH(列) = MONTH(DATE_SUB(NOW(), INTERVAL 1 MONTH))
   - "今天" → DATE(列) = CURDATE()
   - "昨天" → DATE(列) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)
   - "本周" → YEARWEEK(列) = YEARWEEK(NOW())
   - 禁止写 YEAR(列) = 2025 或 MONTH(列) = 6 这种硬编码值
6. **退款相关查询必须使用 refund_records 表**，不要使用 wallet_transactions 或其他表
   - 退款状态：1=处理中/待审核, 2=已完成, 3=已拒绝
   - "待审核退款" → WHERE rr.status = 1
   - "已拒绝退款" → WHERE rr.status = 3

## 探索规则（重要）
1. 如果不确定某个字段的值映射，查询 sys_dicts 表：
   `SELECT dict_label, dict_value FROM sys_dicts WHERE dict_code = 'xxx'`
2. 如果不确定表结构，查询 INFORMATION_SCHEMA：
   `SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'xxx'`
3. 如果不确定数据在哪个表，查询所有表：
   `SELECT TABLE_NAME, TABLE_COMMENT FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE()`
4. 生成的 SQL 必须包含人类可读的标签（使用 CASE WHEN）

## 输出规范（必须遵守）
1. **所有输出必须是人类可读的**，不能使用原始代码或数字指代
2. 状态字段必须映射为中文标签：
   - 退款状态(status)：`CASE WHEN 1 THEN '处理中' WHEN 2 THEN '已完成' WHEN 3 THEN '已拒绝' END`
   - 套餐类型(type)：`CASE WHEN 1 THEN '单次' WHEN 2 THEN '周卡' WHEN 3 THEN '月卡' END`
   - 优惠券类型(type)：`CASE WHEN 1 THEN '固定金额' WHEN 2 THEN '百分比' WHEN 3 THEN '兑换券' END`
   - 支付方式(payment_method)：`CASE WHEN 'wechat' THEN '微信' WHEN 'alipay' THEN '支付宝' WHEN 'cash' THEN '现金' END`
3. 如果不确定某个字段的映射，查询 sys_dicts 表获取：
   `SELECT dict_label, dict_value FROM sys_dicts WHERE dict_code = 'xxx'`
4. 列名使用中文别名：
   - status → 状态
   - refund_amount → 退款金额
   - nickname → 顾客姓名
   - created_at → 创建时间
5. 金额字段使用 FORMAT 函数格式化：`FORMAT(amount, 2)`

请直接返回 SQL 语句："""


# 错误类型分类和修复指南
ERROR_TYPE_GUIDE = """
## 常见错误类型和修复指南

### 1. ambiguous_column(列名歧义)
**错误信息**:Column 'xxx' in where clause is ambiguous
**原因**:多表 JOIN 时，列名在多个表中存在
**修复方案**:为所有列添加表别名
```sql
-- 错误
SELECT id, name FROM orders JOIN customers ...
-- 正确
SELECT o.id, c.name FROM orders o JOIN customers c ...
```

### 2. unknown_column(未知列)
**错误信息**:Unknown column 'xxx'
**原因**:列名拼写错误或不存在
**修复方案**:检查数据库结构，使用正确的列名

### 3. syntax_error(语法错误)
**错误信息**:You have an error in your SQL syntax
**原因**:括号、引号、关键字拼写错误
**修复方案**:检查 SQL 语法

### 4. group_by_error(GROUP BY 错误)
**错误信息**:xxx isn't in GROUP BY
**原因**:SELECT 中的非聚合列不在 GROUP BY 中
**修复方案**:将非聚合列添加到 GROUP BY
```sql
-- 错误
SELECT name, COUNT(*) FROM table
-- 正确
SELECT name, COUNT(*) FROM table GROUP BY name
```

### 5. group_by_alias(GROUP BY 别名错误)
**错误信息**:Can't group on 'xxx'
**原因**:MySQL 不支持在 GROUP BY 中使用列别名
**修复方案**:重复完整表达式或使用子查询
```sql
-- 错误
SELECT CASE WHEN ... END AS level, COUNT(*) FROM ... GROUP BY level
-- 正确方案1:重复表达式
SELECT CASE WHEN ... END AS level, COUNT(*) FROM ... GROUP BY CASE WHEN ... END
-- 正确方案2:子查询
SELECT level, COUNT(*) FROM (
    SELECT id, CASE WHEN ... END AS level FROM ...
) t GROUP BY level
```

### 6. table_not_found(表不存在)
**错误信息**:Table 'xxx' doesn't exist
**原因**:表名拼写错误
**修复方案**:检查数据库结构

### 7. function_not_found(函数不存在)
**错误信息**:FUNCTION xxx does not exist
**原因**:函数名拼写错误或 MySQL 版本不支持
**修复方案**:检查函数名和 MySQL 版本
"""

# SQL 修复 Prompt(集成错误类型分类)
SQL_REPAIR_PROMPT = """修复以下 MySQL SQL 错误。

## 数据库结构
{schema}

## 原始问题
{task}

## 错误 SQL
{sql}

## 错误信息
{error}

## 错误类型
{error_type}

{error_guide}

## 修复要求
1. 分析错误原因
2. 根据错误类型选择对应的修复方案
3. 返回修复后的完整 SQL(只返回 SQL，不要其他内容)

请返回修复后的 SQL:"""


# 任务分解 Prompt
QUERY_DECOMPOSE_PROMPT = """分析以下查询，判断是否需要分解为多个子查询。

用户问题:{task}

## 业务规则（重要）

### 收入相关查询

1. **"营收/营业额/销售额/订单金额"** → 查 `purchases` 表的 `paid_amount` 字段
   - 这是顾客的**订单金额**，包含已核销和未核销的订单
   - entity: "purchases"

2. **"实际收入/确认收入/核销收入"** → 查 `revenue_records` 表的 `amount` 字段
   - 这是**实际核销确认的收入**，只有顾客消费后才会计入
   - entity: "revenue_records"

3. **"收入/进账"** → 默认查 `revenue_records` 表（更准确反映实际收入）

### 支出相关查询

- **"支出/花费/成本"** → 查 `expenses` 表的 `amount` 字段

## 判断标准

### 不需要分解的情况（一个 SQL 即可完成）：
1. **单表查询**：只涉及一个表的查询
   - "今天营业额多少？"
   - "有多少顾客？"

2. **排序/筛选查询**：对单个实体进行排序或筛选
   - "哪个顾客消费最多？" → SELECT ... FROM purchases GROUP BY customer_id ORDER BY SUM DESC
   - "哪些套餐卖得最好？" → SELECT ... FROM purchases GROUP BY package_id ORDER BY COUNT DESC
   - "哪个员工核销最多？" → SELECT ... FROM game_sessions GROUP BY staff_id ORDER BY COUNT DESC

3. **聚合查询**：对单个实体进行统计
   - "本月总营收多少？" → SELECT SUM(amount) FROM purchases WHERE ...
   - "库存还有多少？" → SELECT ... FROM inventory

4. **关联查询**：通过 JOIN 可以一次获取的信息
   - "哪个顾客充的钱最多？" → SELECT ... FROM customers JOIN customer_wallets
   - "顾客张三的手机号？" → SELECT phone FROM customers WHERE nickname = '张三'

### 需要分解的情况（必须多个 SQL 才能完成）：
1. **跨数据源计算**：需要从多个不相关的表获取数据
   - "本月净利润是多少？" → 需要收入表 + 支出表
   - "本月经营情况分析" → 需要营收 + 顾客 + 支出 + 库存

2. **对比分析**：需要对比不同时间段的数据
   - "本月和上月的营业额对比" → 需要查询两个时间段
   - "同比增长率" → 需要本年和去年数据

3. **综合报告**：需要多个维度的数据汇总
   - "生成经营报告" → 需要多个维度
   - "分析经营趋势" → 需要多个时间段

4. **收入和营收对比**：需要从不同表获取数据
   - "本月收入和营收分别是多少？" → 需要 purchases 表 + revenue_records 表
   - "本月收入和支出分别是多少？" → 需要 revenue_records 表 + expenses 表

## 输出格式

如果不需要分解:
{{"need_decompose": false, "reason": "简单查询，一个 SQL 即可完成"}}

如果需要分解:
{{
    "need_decompose": true,
    "sub_queries": [
        {{"step": 1, "description": "查询本月收入", "entity": "revenue_records"}},
        {{"step": 2, "description": "查询本月支出", "entity": "expenses"}},
        {{"step": 3, "description": "计算净利润", "calculation": "revenue - expenses"}}
    ]
}}

## 重要：JSON 格式要求
1. 必须使用双引号，不能使用单引号
2. 只返回纯 JSON，不要包含 markdown 代码块
3. sub_queries 中的 description 必须明确指定查询的指标名称

请直接返回 JSON:"""


class NL2SQLAgent:
    """
    NL2SQL Agent - 数据查询
    
    功能:
    - 自然语言转 SQL 查询
    - 查询营业额、顾客数、库存等数据
    - SQL 错误自动修复
    - SQL 验证(语法、列名、表名)
    - 集成经验池学习
    - 多候选选择
    - 任务分解
    """
    
    async def _decompose_query(self, task: str) -> dict:
        """
        分解复杂查询
        
        Args:
            task: 用户问题
        
        Returns:
            分解结果
        """
        try:
            llm = get_chat_llm(temperature=0)
            prompt = QUERY_DECOMPOSE_PROMPT.format(task=task)
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            # 解析 JSON
            content = response.content.strip()
            result = safe_parse_json(content)
            
            if result and isinstance(result, dict):
                return result
            
            # 解析失败，返回默认值
            print(f"[NL2SQLAgent] 查询分解 JSON 解析失败，返回默认值")
            return {"need_decompose": False, "reason": "JSON 解析失败"}
        except Exception as e:
            print(f"[NL2SQLAgent] 查询分解失败: {str(e)}")
            return {"need_decompose": False, "reason": "分解失败"}
    
    async def _execute_decomposed_query(self, task: str, sub_queries: List[dict], 
                                         context: UserContext) -> str:
        """
        执行分解后的子查询
        
        Args:
            task: 原始问题
            sub_queries: 子查询列表
            context: 用户上下文
        
        Returns:
            合并后的结果
        """
        results = {}
        
        for sub_query in sub_queries:
            step = sub_query.get("step")
            description = sub_query.get("description", "")
            entity = sub_query.get("entity", "")
            calculation = sub_query.get("calculation", "")
            
            # 构建子查询问题
            sub_task = description
            
            # 执行子查询
            result = await self._execute_single_query(sub_task, context)
            
            if result.success:
                results[step] = result.result
            else:
                results[step] = f"查询失败: {result.error}"
        
        # 合并结果
        merged = f"查询结果:\n"
        for step, result in sorted(results.items()):
            merged += f"步骤 {step}: {result}\n"
        
        return merged
    
    async def _execute_single_query(self, task: str, context: UserContext) -> AgentResult:
        """
        执行单个查询(简化版)
        
        Args:
            task: 查询问题
            context: 用户上下文
        
        Returns:
            执行结果
        """
        try:
            # Schema Linking
            relevant_schema = get_relevant_schema(task)
            if not relevant_schema or "未找到" in relevant_schema:
                relevant_schema = get_schema_info()
            
            # Few-shot 检索
            similar_examples = get_few_shot_examples(task, k=3)
            few_shot_prompt = format_few_shot_prompt(similar_examples)
            
            # 生成 SQL
            llm = get_chat_llm(temperature=0)
            prompt = SQL_GENERATION_PROMPT.format(
                relevant_schema=relevant_schema,
                few_shot_prompt=few_shot_prompt,
                experience_prompt="",
                task=task,
                mysql_rules=ALL_MYSQL_RULES,
                current_date=datetime.now().strftime("%Y年%m月%d日"),
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            sql = sanitize_sql(response.content.strip())
            
            # 添加店铺过滤
            sql = add_shop_filter(sql, context.shop_id)
            sql = add_limit(sql)
            
            # 执行
            results = await asyncio.to_thread(execute_sql_with_retry, sql)
            formatted = format_results_for_llm(results)
            
            return AgentResult(
                agent=AgentType.NL2SQL,
                result=formatted,
                confidence=0.9,
                metadata={"sql": sql}
            )
        except Exception as e:
            return AgentResult(
                agent=AgentType.NL2SQL,
                result="",
                confidence=0.0,
                success=False,
                error=str(e)
            )
    
    async def _generate_candidates(self, task: str, schema: str, few_shot: str, 
                                    experience: str, count: int = 3, 
                                    history_context: str = "",
                                    route_context: str = "") -> List[str]:
        """
        生成多个候选 SQL（并行）
        
        Args:
            task: 用户问题
            schema: 数据库结构
            few_shot: Few-shot 示例
            experience: 经验池示例
            count: 候选数量（限制为最多 2 个，避免超出 LLM API batch size 限制）
            history_context: 历史上下文
            route_context: 路由分析结果（Router 的理解、计划等）
        
        Returns:
            候选 SQL 列表
        """
        import asyncio
        
        # 限制候选数量，避免超出 LLM API batch size 限制
        count = min(count, 2)
        
        llm = get_chat_llm(temperature=0.3)  # 使用较高温度增加多样性
        
        from datetime import datetime
        current_date = datetime.now().strftime("%Y年%m月%d日")
        
        # 构建增强的任务描述
        enhanced_task = task
        
        # 添加路由上下文（最重要！Router 的分析结果）
        if route_context:
            enhanced_task = f"""【Router 分析结果】
{route_context}

【用户原始问题】
{task}"""
        
        # 添加历史上下文
        if history_context:
            enhanced_task = f"""【历史对话】
{history_context}

{enhanced_task}

注意：如果当前问题是省略句（如"本月呢？"、"那昨天呢？"），请结合历史对话理解完整意图。"""
        
        # 构建 prompt（所有候选共享同一个 prompt）
        prompt = SQL_GENERATION_PROMPT.format(
            relevant_schema=schema,
            few_shot_prompt=few_shot,
            experience_prompt=experience,
            task=enhanced_task,
            mysql_rules=ALL_MYSQL_RULES,
            current_date=current_date,
        )
        
        # 并行生成候选 SQL
        async def generate_one(index: int):
            """生成单个候选 SQL"""
            try:
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                raw_content = response.content.strip()
                
                print(f"[NL2SQLAgent] 候选 {index+1} LLM 返回: {raw_content}")
                
                sql = sanitize_sql(raw_content)
                
                print(f"[NL2SQLAgent] 候选 {index+1} 清理后: {sql}")
                
                if sql.upper().startswith("SELECT"):
                    print(f"[NL2SQLAgent] 候选 {index+1} 有效")
                    return sql
                else:
                    print(f"[NL2SQLAgent] 候选 {index+1} 无效（不是 SELECT 语句）")
                    return None
            except Exception as e:
                print(f"[NL2SQLAgent] 候选 {index+1} 生成失败: {str(e)}")
                return None
        
        # 并行执行所有候选生成任务
        tasks = [generate_one(i) for i in range(count)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 收集有效结果
        candidates = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[NL2SQLAgent] 候选 {i+1} 异常: {str(result)}")
            elif result is not None:
                candidates.append(result)
        
        # 如果所有候选都为空，用更简单的 prompt 重试一次
        if not candidates:
            print(f"[NL2SQLAgent] 所有候选为空，用简化 prompt 重试")
            try:
                simple_prompt = f"""根据以下问题生成一个 MySQL SELECT 查询语句。

问题：{enhanced_task}

数据库表结构：
{schema}

要求：
1. 只返回 SQL 语句，不要其他文字
2. 必须以 SELECT 开头
3. 使用 shop_id = :shop_id 过滤店铺数据
4. 使用 is_deleted = 0 过滤已删除数据"""
                
                response = await llm.ainvoke([HumanMessage(content=simple_prompt)])
                raw_content = response.content.strip()
                sql = sanitize_sql(raw_content)
                
                print(f"[NL2SQLAgent] 重试 LLM 返回: {raw_content}")
                print(f"[NL2SQLAgent] 重试清理后: {sql}")
                
                if sql.upper().startswith("SELECT"):
                    candidates.append(sql)
                    print(f"[NL2SQLAgent] 重试成功")
                else:
                    print(f"[NL2SQLAgent] 重试失败（不是 SELECT 语句）")
            except Exception as e:
                print(f"[NL2SQLAgent] 重试异常: {str(e)}")
        
        return candidates
    
    async def _select_best_sql(self, candidates: List[str], task: str, 
                                shop_id: int) -> str:
        """
        从候选 SQL 中选择最佳的
        
        选择策略：
        1. 优先选择与问题语义相关的 SQL（检查表名是否匹配问题关键词）
        2. 其次选择有结果的 SQL
        3. 都没有结果时返回最后一个（而非第一个，因为最后一个通常是兜底）
        """
        if not candidates:
            return ""
        
        if len(candidates) == 1:
            return add_shop_filter(candidates[0], shop_id)
        
        # 问题关键词 → 期望的表名映射
        table_hints = {
            "退款": ["refund_records", "rr"],
            "充值": ["wallet_transactions", "wt"],
            "钱包": ["wallet_transactions", "customer_wallets"],
            "积分": ["points_records"],
            "优惠券": ["coupons", "coupon_usages"],
            "评价": ["feedbacks"],
            "排队": ["queue_entries"],
            "库存": ["inventory", "materials"],
            "采购": ["purchase_orders"],
            "员工": ["staff"],
            "考勤": ["attendance_records"],
            "排班": ["staff_schedules"],
        }
        
        # 确定问题期望的表
        expected_tables = set()
        for keyword, tables in table_hints.items():
            if keyword in task:
                expected_tables.update(tables)
        
        best_with_match = None  # 表匹配且有结果
        best_with_result = None  # 有结果但表不匹配
        last_valid = candidates[-1]  # 最后一个有效候选
        
        for sql in candidates:
            try:
                filtered_sql = add_shop_filter(sql, shop_id)
                filtered_sql = add_limit(filtered_sql)
                
                results = await asyncio.to_thread(execute_sql_with_retry, filtered_sql)
                
                if results and len(results) > 0:
                    # 检查 SQL 是否包含期望的表
                    sql_upper = sql.upper()
                    table_matched = any(t.upper() in sql_upper for t in expected_tables) if expected_tables else True
                    
                    if table_matched and best_with_match is None:
                        print(f"[NL2SQLAgent] 选择候选 SQL（表匹配+有结果）")
                        best_with_match = filtered_sql
                        break  # 表匹配且有结果，直接选这个
                    elif best_with_result is None:
                        best_with_result = filtered_sql
            except Exception as e:
                print(f"[NL2SQLAgent] 候选 SQL 执行失败: {str(e)}")
                continue
        
        # 优先级：表匹配+有结果 > 有结果 > 最后一个候选
        if best_with_match:
            return best_with_match
        if best_with_result:
            print(f"[NL2SQLAgent] 选择候选 SQL（有结果但表不完全匹配）")
            return best_with_result
        
        print(f"[NL2SQLAgent] 所有候选无结果，返回最后一个")
        return add_shop_filter(last_valid, shop_id)
    
    async def _validate_sql_syntax(self, sql: str) -> tuple:
        """
        验证 SQL 语法
        
        Args:
            sql: SQL 语句
        
        Returns:
            (is_valid, error_message)
        """
        try:
            from sqlglot import parse_one
            from sqlglot.errors import SqlglotError
            
            # 尝试解析 SQL
            parsed = parse_one(sql)
            
            # 检查是否是 SELECT 语句
            if parsed.key != "select":
                return False, "只允许 SELECT 查询语句"
            
            return True, ""
        except SqlglotError as e:
            return False, f"SQL 语法错误: {str(e)}"
        except Exception as e:
            return False, f"SQL 验证失败: {str(e)}"
    
    async def _validate_mysql_rules(self, sql: str) -> tuple:
        """
        验证 MySQL 特定规则
        
        Args:
            sql: SQL 语句
        
        Returns:
            (is_valid, error_message)
        """
        import re
        
        # 检测 GROUP BY 使用别名的情况
        # 1. 找到所有 AS 别名定义
        aliases = re.findall(r'\bAS\s+(\w+)', sql, re.IGNORECASE)
        
        # 2. 检查 GROUP BY 是否使用了这些别名
        group_by_match = re.search(r'GROUP\s+BY\s+(\w+)', sql, re.IGNORECASE)
        if group_by_match:
            group_by_value = group_by_match.group(1)
            if group_by_value in aliases:
                return False, f"MySQL 不支持在 GROUP BY 中使用列别名 '{group_by_value}'，请重复完整表达式或使用子查询"
        
        return True, ""
    
    async def _validate_execution_result(self, results: list, task: str) -> tuple:
        """
        验证执行结果是否合理
        
        Args:
            results: 查询结果
            task: 用户问题
        
        Returns:
            (is_valid, message)
        """
        if not results:
            return True, "查询结果为空"
        
        # 检查是否有异常值(如负数、超大值)
        for row in results:
            if isinstance(row, dict):
                for key, value in row.items():
                    if isinstance(value, (int, float)):
                        # 检查负数(某些字段不应该为负)
                        if value < 0 and any(keyword in task for keyword in ["金额", "收入", "支出", "利润"]):
                            # 利润可以为负，其他一般不为负
                            if "利润" not in task and "净" not in task:
                                return False, f"查询结果中 {key} 为负数: {value}"
        
        return True, "查询结果合理"
    
    def _classify_error(self, error: str) -> str:
        """
        分类 SQL 错误类型
        
        Args:
            error: 错误信息
        
        Returns:
            错误类型
        """
        error_lower = error.lower()
        
        if "ambiguous" in error_lower:
            return "ambiguous_column"
        elif "unknown column" in error_lower:
            return "unknown_column"
        elif "syntax" in error_lower or "parse" in error_lower:
            return "syntax_error"
        elif "isn't in group by" in error_lower or "group by" in error_lower:
            return "group_by_error"
        elif "can't group" in error_lower:
            return "group_by_alias"
        elif "doesn't exist" in error_lower or "not found" in error_lower:
            return "table_not_found"
        elif "function" in error_lower and "does not exist" in error_lower:
            return "function_not_found"
        else:
            return "unknown"
    
    async def _repair_sql(self, task: str, sql: str, error: str, schema: str) -> str:
        """
        SQL 错误自动修复 - 增强版:根据错误类型针对性修复
        
        Args:
            task: 原始问题
            sql: 错误 SQL
            error: 错误信息
            schema: 数据库结构
        
        Returns:
            修复后的 SQL
        """
        try:
            # 分类错误类型
            error_type = self._classify_error(error)
            print(f"[NL2SQLAgent] 错误类型: {error_type}")
            
            llm = get_chat_llm(temperature=0)
            prompt = SQL_REPAIR_PROMPT.format(
                schema=schema[:2000],  # 限制长度
                task=task,
                sql=sql,
                error=str(error)[:500],
                error_type=error_type,
                error_guide=ERROR_TYPE_GUIDE,
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            # 清理修复后的 SQL
            repaired_sql = response.content.strip()
            
            # 移除 markdown 代码块标记
            if repaired_sql.startswith("```sql"):
                repaired_sql = repaired_sql[6:]
            elif repaired_sql.startswith("```"):
                repaired_sql = repaired_sql[3:]
            if repaired_sql.endswith("```"):
                repaired_sql = repaired_sql[:-3]
            
            # 移除 SQL 注释(单行和多行)
            repaired_sql = re.sub(r'--[^\n]*', '', repaired_sql)  # 移除单行注释
            repaired_sql = re.sub(r'/\*.*?\*/', '', repaired_sql, flags=re.DOTALL)  # 移除多行注释
            
            # 修复双百分号问题
            repaired_sql = repaired_sql.replace('%%', '%')
            
            # 移除多余空格
            repaired_sql = re.sub(r'\s+', ' ', repaired_sql).strip()
            
            # 移除末尾分号
            while repaired_sql.endswith(';'):
                repaired_sql = repaired_sql[:-1].strip()
            
            # 验证修复后的 SQL 是否以 SELECT 开头
            if not repaired_sql.upper().startswith('SELECT'):
                print(f"[NL2SQLAgent] 修复后的 SQL 不完整: {repaired_sql[:100]}...")
                return sql  # 返回原 SQL
            
            print(f"[NL2SQLAgent] SQL 修复: {sql[:100]}... -> {repaired_sql[:100]}...")
            return repaired_sql
        except Exception as e:
            print(f"[NL2SQLAgent] SQL 修复失败: {str(e)}")
            return sql  # 修复失败返回原 SQL
    
    async def execute(self, task: str, context: UserContext, **kwargs) -> AgentResult:
        """
        执行 NL2SQL 任务(带自动修复和经验池学习)
        
        Args:
            task: 用户任务
            context: 用户上下文
            **kwargs: 额外参数
                - query: 预定义 SQL（Skill 使用）
                - history_context: 历史上下文
                - route_context: 路由分析结果（Router 的理解、计划等）
        
        Returns:
            执行结果
        """
        max_retries = 2
        experience_pool = get_experience_pool()
        
        # 检查是否有预定义查询（Skill 使用）
        predefined_query = kwargs.get("query", "")
        
        # 获取历史上下文
        history_context = kwargs.get("history_context", "")
        
        # 获取路由上下文（Router 的分析结果）
        route_context = kwargs.get("route_context", "")
        
        try:
            # 如果有预定义查询，直接执行
            if predefined_query:
                print(f"[NL2SQLAgent] 使用预定义查询: {predefined_query[:100]}...")
                
                # 替换占位符
                sql = predefined_query.replace(":shop_id", str(context.shop_id))
                sql = add_limit(sql)
                
                # 执行查询
                results = await asyncio.to_thread(execute_sql_with_retry, sql)
                formatted = format_results_for_llm(results)
                
                return AgentResult(
                    agent=AgentType.NL2SQL,
                    result=formatted,
                    confidence=0.95,  # 预定义查询置信度高
                    metadata={"sql": sql, "source": "skill"}
                )
            
            # 1. 检索经验池
            similar_exps = await experience_pool.retrieve_similar("nl2sql", task, k=3)
            experience_prompt = experience_pool.format_for_prompt(similar_exps)
            
            # 2. 查询分解(判断是否需要分解为多个子查询)
            decompose_result = await self._decompose_query(task)
            if decompose_result.get("need_decompose"):
                sub_queries = decompose_result.get("sub_queries", [])
                print(f"[NL2SQLAgent] 查询分解为 {len(sub_queries)} 个子查询")
                
                # 执行分解后的查询
                result_text = await self._execute_decomposed_query(task, sub_queries, context)
                
                return AgentResult(
                    agent=AgentType.NL2SQL,
                    result=result_text,
                    confidence=0.9,
                    metadata={"decomposed": True, "sub_queries": len(sub_queries)}
                )
            
            # 3. Schema Linking - 智能识别相关表和列
            relevant_schema = get_relevant_schema(task)
            
            # 如果 Schema Linker 置信度低，使用完整 Schema
            if not relevant_schema or "未找到" in relevant_schema:
                relevant_schema = get_schema_info()
            
            # 3. 检索相似的 Few-shot 样例
            similar_examples = get_few_shot_examples(task, k=3)
            few_shot_prompt = format_few_shot_prompt(similar_examples)
            
            # 4. 调用 LLM 生成 SQL(多候选选择)
            candidates = await self._generate_candidates(
                task, relevant_schema, few_shot_prompt, experience_prompt, count=3,
                history_context=history_context,
                route_context=route_context
            )
            
            if not candidates:
                return AgentResult(
                    agent=AgentType.NL2SQL,
                    result="无法生成有效的 SQL",
                    confidence=0.0,
                    success=False,
                    error="No valid SQL generated"
                )
            
            # 选择最佳候选 SQL
            sql = await self._select_best_sql(candidates, task, context.shop_id)
            
            # 6. 验证 SQL 语法
            is_valid_syntax, syntax_error = await self._validate_sql_syntax(sql)
            if not is_valid_syntax:
                print(f"[NL2SQLAgent] SQL 语法验证失败: {syntax_error}")
                # 尝试修复语法错误
                sql = await self._repair_sql(task, sql, syntax_error, relevant_schema)
                # 再次验证
                is_valid_syntax, syntax_error = await self._validate_sql_syntax(sql)
                if not is_valid_syntax:
                    # 记录失败案例
                    await experience_pool.record_failure_and_fix(
                        agent_type="nl2sql",
                        question=task,
                        error=syntax_error,
                        original_solution=raw_sql,
                    )
                    return AgentResult(
                        agent=AgentType.NL2SQL,
                        result=f"SQL 语法错误: {syntax_error}",
                        confidence=0.0,
                        success=False,
                        error=syntax_error
                    )
            
            # 7. 验证 MySQL 规则
            is_valid_mysql, mysql_error = await self._validate_mysql_rules(sql)
            if not is_valid_mysql:
                print(f"[NL2SQLAgent] MySQL 规则验证失败: {mysql_error}")
                # 尝试修复
                sql = await self._repair_sql(task, sql, mysql_error, relevant_schema)
            
            # 8. 安全校验
            is_safe, message = validate_sql(sql)
            
            if not is_safe:
                return AgentResult(
                    agent=AgentType.NL2SQL,
                    result=f"SQL校验失败: {message}",
                    confidence=0.0,
                    success=False,
                    error=message
                )
            
            # 9. 添加店铺过滤和限制
            sql = add_shop_filter(sql, context.shop_id)
            sql = add_limit(sql)
            
            # 10. 执行 SQL(带自动修复)
            last_error = None
            current_sql = sql
            
            for attempt in range(max_retries):
                try:
                    results = await asyncio.to_thread(execute_sql_with_retry, current_sql)
                    
                    # 11. 格式化结果
                    formatted = format_results_for_llm(results)
                    
                    # 构建解决流程
                    solving_process = [
                        {"step": 1, "description": "Schema Linking", "detail": f"识别相关表和列"},
                        {"step": 2, "description": "Few-shot 检索", "detail": f"检索相似 SQL 样例"},
                        {"step": 3, "description": "LLM 生成 SQL", "detail": f"生成初始 SQL"},
                        {"step": 4, "description": "SQL 验证", "detail": f"语法和规则验证"},
                        {"step": 5, "description": "SQL 执行", "detail": f"执行并返回结果"},
                    ]
                    
                    # 成功:记录到经验池
                    await experience_pool.record_success(
                        agent_type="nl2sql",
                        question=task,
                        solution=current_sql,
                        result_summary=formatted[:200],
                        solving_process=solving_process,
                    )
                    
                    return AgentResult(
                        agent=AgentType.NL2SQL,
                        result=formatted,
                        confidence=0.9,
                        metadata={
                            "sql": current_sql,
                            "results": results,
                            "attempts": attempt + 1,
                        }
                    )
                except Exception as sql_error:
                    last_error = sql_error
                    print(f"[NL2SQLAgent] 第 {attempt + 1} 次执行失败: {str(sql_error)}")
                    
                    if attempt < max_retries - 1:
                        # 尝试修复 SQL
                        fixed_sql = await self._repair_sql(task, current_sql, str(sql_error), relevant_schema)
                        
                        # 记录失败+修复案例
                        await experience_pool.record_failure_and_fix(
                            agent_type="nl2sql",
                            question=task,
                            error=str(sql_error),
                            original_solution=current_sql,
                            fixed_solution=fixed_sql,
                        )
                        
                        current_sql = fixed_sql
                        # 重新添加店铺过滤和限制
                        current_sql = add_shop_filter(current_sql, context.shop_id)
                        current_sql = add_limit(current_sql)
            
            # 所有重试都失败
            return AgentResult(
                agent=AgentType.NL2SQL,
                result=f"数据查询失败: {str(last_error)}",
                confidence=0.0,
                success=False,
                error=str(last_error)
            )
            
        except Exception as e:
            print(f"[NL2SQLAgent] 执行失败: {str(e)}")
            
            # 记录失败案例
            await experience_pool.record_failure_and_fix(
                agent_type="nl2sql",
                question=task,
                error=str(e),
                original_solution="",
            )
            
            return AgentResult(
                agent=AgentType.NL2SQL,
                result=f"数据查询失败: {str(e)}",
                confidence=0.0,
                success=False,
                error=str(e)
            )
