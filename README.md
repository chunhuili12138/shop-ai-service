# ShopCopilot - 店铺智能助手 AI Service

基于 FastAPI + LangChain 构建的 AI Agent 服务，为店铺提供智能问答、数据分析、工具调用等功能。

## 技术栈

| 类别 | 技术 |
|------|------|
| **Web 框架** | FastAPI |
| **LLM** | MiMo v2.5 / MiMo v2.5 Pro |
| **向量数据库** | Chroma |
| **关系数据库** | MySQL 8.0+ |
| **缓存** | Redis |
| **可观测性** | LangFuse |
| **密码加密** | cachetools (TTLCache) |

---

## 项目结构

```
shop-ai-service/
├── app/
│   ├── chat/                    # 聊天模块
│   │   ├── router.py            # 聊天路由（POST /stream + 会话管理 + batch_confirm）
│   │   └── stream_handler.py    # SSE 流式处理（含 Agent Loop + 批量确认）
│   ├── common/                  # 公共模块
│   │   ├── auth.py              # Token 认证（TTLCache 缓存 + SSL 环境控制）
│   │   ├── backend_client.py    # Java 后端 API 调用客户端
│   │   ├── user_context.py      # 用户上下文
│   │   └── system_prompts.py    # 系统提示词（角色/安全/合规）
│   ├── multi_agent/             # 多 Agent 模块
│   │   ├── router.py            # 智能路由（LLM 判断 + Skills + 综合问题检查）
│   │   ├── supervisor.py        # Supervisor 调度器（支持批量确认）
│   │   ├── protocol.py          # 协议定义（SubTask 增加 tool_name）
│   │   ├── rag_agent.py         # RAG 知识问答
│   │   ├── nl2sql_agent.py      # NL2SQL 数据查询
│   │   ├── tool_agent.py        # 工具调用
│   │   └── llm_agent.py         # LLM 总结分析
│   ├── rag/                     # RAG 模块
│   │   ├── agentic_rag.py       # Agentic RAG（CRAG + Self-RAG）
│   │   ├── intent_router.py     # 意图路由
│   │   └── session.py           # 会话管理
│   ├── nl2sql/                  # NL2SQL 模块
│   │   ├── safety.py            # SQL 安全校验（注入防护 + shop_id 过滤）
│   │   └── executor.py          # SQL 执行器（事务支持）
│   ├── tools/                   # 工具模块
│   │   ├── __init__.py          # 工具注册（TOOL_MAP + TOOL_DISPLAY_NAMES）
│   │   ├── agent_loop.py        # Agent 循环（带超时保护）
│   │   ├── param_plans.py       # 参数解析计划（查询工具参数配置）
│   │   ├── tool_requirements.py # 操作工具参数需求（Agent Loop 使用）
│   │   ├── coupon.py            # 优惠券工具（调用 Java API）
│   │   ├── trade.py             # 交易工具（退款/核销，调用 Java API）
│   │   ├── inventory.py         # 库存工具（入库/出库，调用 Java API）
│   │   ├── feedback.py          # 评价工具（回复，调用 Java API）
│   │   ├── notification.py      # 通知工具（发送，调用 Java API）
│   │   └── permissions.py       # 角色权限控制
│   ├── knowledge/               # 知识库模块
│   │   ├── scheduler.py         # 定时任务（动态 shop_id）
│   │   └── package_client.py    # 套餐客户端（异步）
│   ├── config.py                # 配置管理
│   └── main.py                  # 应用入口（结构化日志）
├── monitoring/                  # 监控模块
│   └── langfuse_config.py       # LangFuse 配置（兼容同步/异步）
├── tests/                       # 单元测试（44 个用例）
│   ├── test_auth_unit.py        # 认证模块测试
│   ├── test_hitl_unit.py        # HITL 中断管理器测试
│   └── test_safety_unit.py      # SQL 安全模块测试
├── requirements.txt             # Python 依赖
└── .env                         # 环境变量
```

---

## 核心架构

### 1. 任务路由流程

```
用户问题
    ↓
【综合检查】_check_question（一次 LLM 调用）
    ├── 无效输入 → 返回提示
    ├── 上下文问题 → LLM Agent 基于历史回答
    ├── 需要追问 → 返回追问提示
    └── 有效 → 继续路由
    ↓
【Router 分析】COMPLEXITY_PROMPT → mode/agent/plan
    ├── single + tool → 工具调用
    ├── single + nl2sql → 数据查询
    ├── single + rag → 知识问答
    └── multi → 多任务拆分
```

### 2. 操作工具执行流程（Agent Loop）

```
Router → tool: grant_coupon
    ↓
【Agent Loop】_execute_with_agent_loop
    ├── LLM 提取参数（从 TOOL_REQUIREMENTS）
    ├── 查询上下文（query_context）
    ├── NL2SQL 解析名称→ID
    └── 调用工具 → 返回 confirm 弹窗
    ↓
【用户确认】POST /api/chat/confirm
    ↓
【执行】调用 Java 后端 API
```

### 3. 多任务批量确认流程

```
用户: "同意林志玲退款，拒绝黄晓明的"
    ↓
【Router】mode=multi
    ↓
【Supervisor】拆分子任务
    ├── 子任务1: NL2SQL 查询退款信息
    ├── 子任务2: refund_approve(林志玲) [tool_name=refund_approve]
    └── 子任务3: refund_reject(黄晓明) [tool_name=refund_reject]
    ↓
【串行执行】
    ├── 子任务1: 查询 → refund_id=14, 15
    ├── 子任务2: Agent Loop → confirm_data
    └── 子任务3: Agent Loop → confirm_data（含 reason 字段）
    ↓
【批量确认】SSE batch_confirm 事件
    ↓
【前端】BatchConfirmCard（checkbox + 输入框）
    ↓
【用户确认】POST /api/chat/batch_confirm
    ↓
【执行】循环调用 Java 后端 API
```

### 4. 安全机制

```
请求 → Token 认证（TTLCache 缓存）
    → SSL 验证（生产环境启用）
    → 角色权限校验（is_tool_allowed）
    → SQL 安全校验（注入防护 + shop_id 强制过滤）
    → 工具执行超时保护（AGENT_TIMEOUT）
```

---

## 快速开始

### 1. 环境准备

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# LLM 配置
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
LLM_MODEL=mimo-v2.5

# 数据库配置
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DATABASE=shop_operate_system

# Redis 配置
REDIS_HOST=localhost
REDIS_PORT=6379

# 后台管理系统
BACKEND_URL=http://localhost:8081

# 环境（development/production）
ENVIRONMENT=development
```

### 3. 启动服务

```bash
python -m app.main
```

### 4. 运行测试

```bash
python -m pytest tests/test_auth_unit.py tests/test_hitl_unit.py tests/test_safety_unit.py -v
```

---

## API 接口

### 聊天接口（POST + SSE 流式）

```
POST /api/chat/stream
Authorization: Bearer-{shopId}-{token}
Content-Type: application/json

{
  "message": "今天营业额多少",
  "session_id": "可选-会话ID"
}
```

**SSE 事件类型**：

| 类型 | 说明 |
|------|------|
| `thinking` | 意图分析 |
| `plan` | 执行计划 |
| `processing` | 执行步骤 |
| `answer` | 最终答案 |
| `confirm` | 单个确认弹窗 |
| `batch_confirm` | 批量确认弹窗 |
| `select` | 选择弹窗 |
| `quick_questions` | 快速问题建议 |
| `done` | 完成 |
| `error` | 错误 |

### 确认操作接口

```
POST /api/chat/confirm
Authorization: Bearer-{shopId}-{token}

{
  "action": "refund_approve",
  "params": {"shop_id": 5, "refund_id": 14}
}
```

### 批量确认接口

```
POST /api/chat/batch_confirm
Authorization: Bearer-{shopId}-{token}

{
  "session_id": "会话ID",
  "operations": [
    {"action": "refund_approve", "params": {"shop_id": 5, "refund_id": 14}},
    {"action": "refund_reject", "params": {"shop_id": 5, "refund_id": 15, "reason": "超过退款期限"}}
  ]
}
```

### 会话管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/chat/sessions` | GET | 获取会话列表 |
| `/api/chat/sessions` | POST | 创建会话 |
| `/api/chat/sessions/{id}` | DELETE | 删除会话 |
| `/api/chat/sessions/{id}/messages` | GET | 获取会话历史 |

---

## 工具体系

### 查询工具（query_*）

| 工具 | 说明 | 支持的筛选条件 |
|------|------|---------------|
| `query_coupons` | 查询优惠券 | status |
| `query_customer` | 查询顾客 | keyword（姓名/手机号） |
| `query_refunds` | 查询退款 | status, customer_name |
| `query_feedbacks` | 查询评价 | status, customer_name |
| `query_inventory` | 查询库存 | keyword（物料名） |
| `query_game_sessions` | 查询场次 | status, customer_name |

### 操作工具（调用 Java 后端 API）

| 工具 | Java API | 说明 |
|------|----------|------|
| `grant_coupon` | POST /api/couponUsagesGrant | 发放优惠券 |
| `refund_approve` | PUT /api/purchasesRefundsApprove | 批准退款 |
| `refund_reject` | PUT /api/purchasesRefundsReject | 拒绝退款 |
| `game_session_checkin` | POST /api/gameSessionsCheckin | 核销入座 |
| `game_session_finish` | PUT /api/gameSessionsFinish | 结束游玩 |
| `material_inbound` | POST /api/inventoryInbound | 物料入库 |
| `material_outbound` | POST /api/inventoryOutbound | 物料出库 |
| `reply_feedback` | PUT /api/feedbacks/reply | 回复评价 |
| `send_notification` | POST /api/notificationsSend | 发送通知 |

---

## 日志说明

启动后控制台输出结构化日志，排查问题时可直接复制：

```
[StreamHandler] ========== 收到新请求 ==========
[StreamHandler] 用户消息: 今天营业额多少
[StreamHandler] 用户ID: 9, 店铺ID: 5, 角色: 店长
[StreamHandler] ========== 路由决策 ==========
[StreamHandler] 模式: single, Agent: nl2sql, 推理: ...
[StreamHandler] ========== 开始按计划执行 ==========
[StreamHandler:NL2SQL] 入参 original_task: ...
[StreamHandler:NL2SQL] 执行耗时: 1250ms
[StreamHandler:NL2SQL] 输出内容: 今日营业额为 ¥2,580.00...
[SSE] ➤ type=answer, step=最终答案, content=今日营业额...
[StreamHandler] ========== 请求处理完成 ==========
[StreamHandler] 总耗时: 3500ms
```

第三方库日志（httpcore/openai/chromadb）已静默，只显示应用层日志。

---

## 配置说明

### 审批阈值配置

```python
# app/config.py
HITL_REFUND_THRESHOLD: float = 100.0   # 退款超过此金额需要审批
HITL_TRANSFER_THRESHOLD: float = 1000.0 # 转账超过此金额需要审批
```

### 工具执行超时

```python
AGENT_TIMEOUT: int = 60  # 工具执行超时时间（秒）
```

### Token 缓存

```python
TOKEN_CACHE_TTL: int = 300  # Token 缓存过期时间（秒）
# 使用 cachetools.TTLCache(maxsize=10000) 自动淘汰
```

---

## 更新日志

### v0.5.0 (2026-06-20)

**Router 优化**
- 合并三个检查方法为 `_check_question`（一次 LLM 调用）
- 查询工具能力表，LLM 知道何时用 tool/nl2sql
- JSON 解析失败重试机制（最多 2 次）
- 智能 fallback（操作类→TOOL，其他→RAG）

**Agent Loop**
- LLM 自主规划参数获取（TOOL_REQUIREMENTS 驱动）
- 支持 extract 模式（first/all_concat/value）
- 支持排除逻辑（exclude_ids/exclude_names）
- 支持多值查询（如"张三和李四"）
- 参数类型自动转换

**多任务批量确认**
- SubTask 增加 tool_name 字段
- Supervisor 支持操作型子任务的确认流程
- 新增 POST /api/chat/batch_confirm 端点
- 前端 BatchConfirmCard 组件（checkbox + 输入框）

**操作工具统一**
- 所有 9 个操作工具改为调用 Java 后端 API
- 新增 backend_client.py 封装 Java API 调用
- 修复 token/operator_id 注入问题

**其他改进**
- `_check_question_validity` 和 `_check_need_clarification` 增加上下文传递
- Agent Loop 不校验 required 参数（由工具 confirm 弹窗处理）
- Supervisor 任务在 SSE 断开后自动取消

### v0.4.0 (2026-06-13)

**安全修复**
- 移除 GET /stream 端点，统一 POST + Authorization Header
- Token 缓存改用 TTLCache(maxsize=10000) 防止内存泄漏
- SSL 验证按环境控制，生产环境启用
- confirm 操作添加角色权限二次校验

**稳定性修复**
- HITL 改用 Redis 持久化，interrupt_id 改用 UUID
- 库存操作添加事务包裹
- 工具执行添加 asyncio.wait_for 超时保护
- 套餐客户端改为异步调用

**配置改进**
- 审批阈值从 settings 读取，不再硬编码
- 移除所有硬编码 shop_id=5
- NL2SQL_DANGLED_KEYWORDS → NL2SQL_DANGEROUS_KEYWORDS

**日志改造**
- 结构化日志（logging 模块）
- 第三方库日志静默（WARNING 级别）
- 流式处理全流程日志（请求/路由/步骤/耗时/SSE 事件）

**监控改进**
- LangFuse trace_function 兼容同步和异步函数

**测试**
- 新增 44 个单元测试（auth/hitl/safety）

### v2.1 (2026-06-13)
- 任务计划执行机制
- Skills 预设任务机制
- 经验池系统
- LLM Agent
- 历史上下文支持

### v1.0 (2026-06-01)
- 初始版本

---

## License

MIT
