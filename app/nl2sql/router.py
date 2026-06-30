"""
NL2SQL模块路由
提供自然语言转SQL查询API
所有接口需要 Token 验证
"""

import time
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from langchain_core.prompts import ChatPromptTemplate
from app.llm import get_chat_llm
from app.nl2sql.schema import get_schema_info
from app.nl2sql.schema_linker import get_relevant_schema
from app.nl2sql.fewshot_vector import get_few_shot_examples, format_few_shot_prompt
from app.nl2sql.safety import validate_sql, sanitize_sql, add_limit, add_shop_filter
from app.nl2sql.executor import execute_sql_with_retry, format_results_for_llm
from app.nl2sql.self_correction import correct_sql_with_retry
from app.common.auth import verify_token, parse_authorization
from monitoring.langfuse_config import create_trace, create_span

router = APIRouter()


class NL2SQLRequest(BaseModel):
    """NL2SQL请求"""
    question: str
    enable_correction: bool = True  # 是否启用自修正


class NL2SQLResponse(BaseModel):
    """NL2SQL响应"""
    question: str
    sql: str
    results: list
    formatted_results: str
    is_safe: bool
    correction_applied: bool = False  # 是否应用了修正
    correction_attempts: int = 0  # 修正尝试次数


# 优化后的 NL2SQL 提示词模板
NL2SQL_PROMPT_TEMPLATE = """你是一个专业的数据分析专家，负责将自然语言问题转换为MySQL查询语句。

## 数据库结构
{schema}

{few_shot_examples}

## 业务规则（重要）

### 收入相关查询

1. **"营收/营业额/销售额/订单金额"** → 查 `purchases` 表的 `paid_amount` 字段
   - 这是顾客的**订单金额**，包含已核销和未核销的订单
   - SQL: `SELECT COALESCE(SUM(paid_amount), 0) FROM purchases WHERE shop_id = :shop_id AND status = 1`

2. **"实际收入/确认收入/核销收入"** → 查 `revenue_records` 表的 `amount` 字段
   - 这是**实际核销确认的收入**，只有顾客消费后才会计入
   - SQL: `SELECT COALESCE(SUM(amount), 0) FROM revenue_records WHERE shop_id = :shop_id`

3. **"收入/进账"** → 默认查 `revenue_records` 表（更准确反映实际收入）

### 支出相关查询

- **"支出/花费/成本"** → 查 `expenses` 表的 `amount` 字段

### 顾客相关查询

- **"新顾客"** → 查 `customers` 表，按 `created_at` 筛选
- **"活跃顾客"** → 查 `purchases` 表，按 `customer_id` 去重
- **"顾客来源"** → `customers.source`: store-门店, meituan-美团, douyin-抖音, miniapp-小程序, other-其他
- **"顾客标签"** → `customers.tags`: vip, regular, family, new, big, complaint, star, xin

### 退款相关查询

- **"退款金额"** → 查 `refund_records` 表的 `refund_amount` 字段
- **"退款状态"** → status: 1=处理中, 2=已完成, 3=已拒绝
- **"退款率"** → `退款金额 / 总销售额`（近30天）

### 套餐相关查询

- **"套餐类型"** → `packages.type`: 1=单次, 2=周卡, 3=月卡
- **"热销套餐"** → 按 `purchases.package_id` 分组统计

### 核销相关查询

- **"核销数/核销次数"** → 查 `game_sessions` 表，`status=2`（已完成）
- **"进行中"** → 查 `game_sessions` 表，`status=1`（进行中）

### 库存相关查询

- **"库存预警"** → `inventory.quantity <= materials.min_stock`
- **"物料类型"** → `materials.type`: 1=消耗品, 2=工具

### 考勤相关查询

- **"考勤状态"** → `attendance_records.status`: 1=正常, 2=迟到, 3=早退, 4=加班
- **"迟到"** → `status=2`
- **"加班"** → `status=4`

### 优惠券相关查询

- **"优惠券类型"** → `coupons.type`: 1=固定金额, 2=百分比, 3=兑换券
- **"未使用优惠券"** → `coupon_usages.status=1`

## 生成规则

1. **只生成 SELECT 查询语句**，禁止使用 INSERT、UPDATE、DELETE、DROP 等操作
2. **使用正确的表名和字段名**，参考上述数据库结构
3. **数据隔离**：所有查询必须包含 `shop_id = :shop_id` 条件
4. **字段别名**：为返回字段使用有意义的中文别名
5. **聚合函数**：统计查询使用 SUM、COUNT、AVG 等聚合函数
6. **时间处理**：
   - 今天：`DATE(created_at) = CURDATE()`
   - 本周：`YEARWEEK(created_at) = YEARWEEK(NOW())`
   - 本月：`MONTH(created_at) = MONTH(NOW()) AND YEAR(created_at) = YEAR(NOW())`
   - 本年：`YEAR(created_at) = YEAR(NOW())`
7. **排序**：默认按时间倒序或金额/数量降序
8. **限制**：返回结果不超过 100 行，使用 LIMIT 子句
9. **参数化**：使用 `:shop_id` 作为参数占位符

## 用户问题
{question}

请直接返回 SQL 语句，不要包含任何解释或说明："""


@router.post("/query", response_model=NL2SQLResponse)
async def nl2sql_query(
    request: NL2SQLRequest,
    authorization: str = Header(...)
):
    """
    自然语言转SQL查询

    支持的查询类型：
    - 营业额统计（今天/本周/本月/本年）
    - 顾客分析（新客/活跃/流失）
    - 套餐销量（排名/对比）
    - 库存查询（预警/分类）
    - 员工绩效（核销/排名）
    - 收支统计（收入/支出/利润）
    """
    # 创建追踪
    trace = create_trace("nl2sql_query", {"question": request.question})
    start_time = time.time()
    
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 2. Schema Linking - 智能识别相关表和列
        relevant_schema = get_relevant_schema(request.question)

        # 如果 Schema Linker 置信度低，使用完整 Schema
        if not relevant_schema or "未找到" in relevant_schema:
            relevant_schema = get_schema_info()

        # 记录 Schema Linking
        if trace:
            create_span(trace, "schema_linking", {
                "schema_length": len(relevant_schema),
            })

        # 3. 检索相似的 Few-shot 样例（向量检索）
        similar_examples = get_few_shot_examples(request.question, k=3)
        few_shot_prompt = format_few_shot_prompt(similar_examples)

        # 4. 调用 LLM 生成 SQL
        llm = get_chat_llm(temperature=0)

        prompt = ChatPromptTemplate.from_template(NL2SQL_PROMPT_TEMPLATE)
        chain = prompt | llm

        response = await chain.ainvoke({
            "schema": relevant_schema,
            "few_shot_examples": few_shot_prompt,
            "question": request.question,
        })

        raw_sql = response.content.strip()

        # 记录 SQL 生成
        if trace:
            create_span(trace, "sql_generation", {
                "raw_sql": raw_sql[:200],  # 截断过长 SQL
            })

        # 5. 清理 SQL
        sql = sanitize_sql(raw_sql)

        # 6. 安全校验
        is_safe, message = validate_sql(sql)

        if not is_safe:
            # 如果安全校验失败，尝试自修正
            if request.enable_correction:
                correction_result = await correct_sql_with_retry(
                    original_sql=sql,
                    error_message=message,
                    question=request.question,
                    execute_fn=lambda s: validate_sql(s)  # 校验函数
                )

                if correction_result.success:
                    sql = correction_result.corrected_sql
                    is_safe, message = validate_sql(sql)

            if not is_safe:
                # 记录安全校验失败
                if trace:
                    create_span(trace, "safety_check_failed", {
                        "sql": sql[:200],
                        "message": message,
                    })
                
                return NL2SQLResponse(
                    question=request.question,
                    sql=sql,
                    results=[],
                    formatted_results=f"SQL校验失败: {message}",
                    is_safe=False,
                )

        # 记录安全校验通过
        if trace:
            create_span(trace, "safety_check_passed", {"sql": sql[:200]})

        # 7. 添加店铺过滤和限制
        sql = add_shop_filter(sql, user_context.shop_id)
        sql = add_limit(sql)

        # 8. 执行 SQL（带自修正）
        correction_applied = False
        correction_attempts = 0

        if request.enable_correction:
            # 使用带重试的执行
            try:
                results = execute_sql_with_retry(sql)
            except Exception as e:
                # SQL 执行失败，尝试自修正
                correction_result = await correct_sql_with_retry(
                    original_sql=sql,
                    error_message=str(e),
                    question=request.question,
                    execute_fn=execute_sql_with_retry
                )

                if correction_result.success:
                    sql = correction_result.corrected_sql
                    results = execute_sql_with_retry(sql)
                    correction_applied = True
                    correction_attempts = correction_result.attempts
                else:
                    raise e
        else:
            results = execute_sql_with_retry(sql)

        # 记录 SQL 执行结果
        if trace:
            create_span(trace, "sql_execution", {
                "row_count": len(results),
                "correction_applied": correction_applied,
                "correction_attempts": correction_attempts,
            })

        # 9. 格式化结果
        formatted = format_results_for_llm(results)

        # 记录最终结果
        if trace:
            create_span(trace, "nl2sql_result", {
                "result_length": len(formatted),
                "duration_ms": (time.time() - start_time) * 1000,
            })

        return NL2SQLResponse(
            question=request.question,
            sql=sql,
            results=results,
            formatted_results=formatted,
            is_safe=True,
            correction_applied=correction_applied,
            correction_attempts=correction_attempts,
        )

    except HTTPException:
        raise
    except Exception as e:
        if trace:
            create_span(trace, "nl2sql_error", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/explain")
async def explain_query(
    question: str,
    authorization: str = Header(...)
):
    """
    解释查询（不执行）
    返回生成的 SQL 和解释
    """
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 2. Schema Linking
        relevant_schema = get_relevant_schema(question)
        if not relevant_schema or "未找到" in relevant_schema:
            relevant_schema = get_schema_info()

        # 3. Few-shot 检索
        similar_examples = get_few_shot_examples(question, k=3)
        few_shot_prompt = format_few_shot_prompt(similar_examples)

        # 4. 生成 SQL
        llm = get_chat_llm(temperature=0)
        prompt = ChatPromptTemplate.from_template(NL2SQL_PROMPT_TEMPLATE)
        chain = prompt | llm

        response = await chain.ainvoke({
            "schema": relevant_schema,
            "few_shot_examples": few_shot_prompt,
            "question": question,
        })

        sql = sanitize_sql(response.content.strip())
        sql = add_shop_filter(sql, user_context.shop_id)
        sql = add_limit(sql)

        # 5. 生成解释
        explain_prompt = ChatPromptTemplate.from_template("""
请用简洁的中文解释以下 SQL 查询的作用：

问题：{question}
SQL：
```sql
{sql}
```

解释：""")

        explain_chain = explain_prompt | llm
        explain_response = await explain_chain.ainvoke({
            "question": question,
            "sql": sql
        })

        return {
            "question": question,
            "sql": sql,
            "explanation": explain_response.content.strip(),
            "relevant_tables": relevant_schema
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解释失败: {str(e)}")
