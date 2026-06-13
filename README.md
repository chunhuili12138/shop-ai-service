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
│   │   ├── router.py            # 聊天路由（POST /stream + 会话管理）
│   │   └── stream_handler.py    # SSE 流式处理（含计划执行 + 全流程日志）
│   ├── common/                  # 公共模块
│   │   ├── auth.py              # Token 认证（TTLCache 缓存 + SSL 环境控制）
│   │   └── user_context.py      # 用户上下文
│   ├── multi_agent/             # 多 Agent 模块
│   │   ├── router.py            # 智能路由（LLM 判断 + Skills）
│   │   ├── supervisor.py        # Supervisor 调度器
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
│   │   ├── agent_loop.py        # Agent 循环（带超时保护）
│   │   ├── inventory.py         # 库存操作（事务包裹）
│   │   └── permissions.py       # 角色权限控制
│   ├── hitl/                    # 人机协作审批
│   │   ├── interrupt.py         # 中断管理器（Redis 持久化）
│   │   └── approval.py          # 审批流程（可配置阈值）
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

### 1. 任务计划执行流程

```
用户问题
    ↓
【Router 分析】LLM 判断意图 → mode/agent/plan
    ↓
【按计划执行】每步调用对应 Agent → 记录耗时和结果
    ↓
【汇总输出】LLM 汇总所有步骤结果 → 最终答案
```

### 2. 安全机制

```
请求 → Token 认证（TTLCache 缓存）
    → SSL 验证（生产环境启用）
    → 角色权限校验（is_tool_allowed）
    → SQL 安全校验（注入防护 + shop_id 强制过滤）
    → 工具执行超时保护（AGENT_TIMEOUT）
```

### 3. HITL 审批流程

```
高风险操作 → 检查审批阈值（可配置）
    → 创建中断点（Redis 持久化 + UUID）
    → 等待人工审批
    → 执行或拒绝
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
python -m pytest tests/ -v
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

**SSE 输出格式**：

```json
// 理解问题
{"type": "thinking", "content": "用户想要查询今天的营业额数据", "step": "理解问题", "done": false}

// 执行计划
{"type": "plan", "content": "1. 查询今日营业额", "step": "执行计划", "done": false}

// 执行步骤
{"type": "processing", "content": "步骤 1/1: 查询今日营业额...", "step": "步骤 1", "done": false}
{"type": "processing", "content": "✓ 步骤 1 完成", "step": "步骤 1", "done": false}

// 最终答案
{"type": "answer", "content": "今日营业额为 ¥2,580.00，共 8 笔订单", "step": "最终答案", "done": false}

// 完成
{"type": "done", "content": "", "step": "完成", "done": true}
```

### 确认操作接口

```
POST /api/chat/confirm
Authorization: Bearer-{shopId}-{token}

{
  "action": "material_inbound",
  "params": {"shop_id": 5, "material_id": 1, "quantity": 100}
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
