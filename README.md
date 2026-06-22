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
│   │   ├── router.py            # 智能路由（_check_question + COMPLEXITY_PROMPT）
│   │   ├── supervisor.py        # Supervisor 调度器（支持批量确认）
│   │   ├── protocol.py          # 协议定义（SubTask 增加 tool_name）
│   │   ├── rag_agent.py         # RAG 知识问答
│   │   ├── nl2sql_agent.py      # NL2SQL 数据查询（并行候选 + 输出规范）
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
│   │   ├── agent_loop.py        # Agent 循环（ReAct + 探索工具 + 后台导航）
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
├── data/                        # 数据文件
│   └── system_capabilities.json # 后台系统页面能力文档
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
    ├── 需要追问 → 返回追问提示
    ├── 纯文本上下文 → LLM Agent 基于历史回答
    ├── 确认性回复 → 根据助手上一个问题判断
    └── 有效 → 继续路由
    ↓
【Router 分析】COMPLEXITY_PROMPT → mode/agent/plan
    ├── single + nl2sql → 数据查询（统一使用 nl2sql）
    ├── single + tool → 操作工具调用
    ├── single + rag → 知识问答
    ├── single + llm → 分析总结
    └── multi → 多任务拆分
```

### 2. Agent Loop（ReAct 循环）

```
用户问题 → LLM 决策 → 调用工具 → 观察结果 → 继续决策 → 最终回答
                ↑                              ↓
                └──────── 循环（最多 5 轮）──────┘

可用工具：
- execute_sql_query: 通用 SQL 查询
- list_tables: 列出数据库表
- describe_table: 查看表结构
- search_docs: 搜索知识库
- query_refunds: 查询退款记录
- refund_approve: 批准退款
- ... 其他操作工具
```

### 3. 多任务批量确认流程

```
用户: "同意林志玲退款，拒绝黄晓明的"
    ↓
【Router】mode=multi
    ↓
【Supervisor】拆分子任务
    ├── 子任务1: NL2SQL 查询退款信息 [nl2sql]
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
| `answer` | 最终答案（流式输出） |
| `confirm` | 单个确认弹窗 |
| `batch_confirm` | 批量确认弹窗 |
| `select` | 选择弹窗 |
| `quick_questions` | 快速问题建议 |
| `warning` | 评审警告 |
| `success` | 操作成功 |
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

### 探索工具（Agent Loop）

| 工具 | 说明 |
|------|------|
| `execute_sql_query` | 通用 SQL 查询（只允许 SELECT） |
| `list_tables` | 列出数据库表（按关键字过滤） |
| `describe_table` | 查看表结构（字段名、类型、说明） |
| `search_docs` | 搜索知识库文档 |

### 查询工具（query_*）

| 工具 | 说明 |
|------|------|
| `query_coupons` | 查询优惠券 |
| `query_customer` | 查询顾客 |
| `query_refunds` | 查询退款记录 |
| `query_feedbacks` | 查询评价 |
| `query_inventory` | 查询库存 |
| `query_game_sessions` | 查询场次 |

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

### Skills（预设任务模板）

| # | Skill | 步骤 | 说明 |
|---|-------|------|------|
| 1 | 本月经营情况分析 | 6 | 营收+顾客+支出+退款+热销套餐+分析 |
| 2 | 今日经营概况 | 6 | 营业额+核销+新顾客+热销套餐+库存预警+汇总 |
| 3 | 顾客消费分析 | 2 | 消费统计+分析 |
| 4 | 库存查询 | 2 | 库存状态+分析 |
| 5 | 套餐查询 | 2 | 套餐列表+分析 |
| 6 | 员工查询 | 2 | 员工信息+核销统计 |
| 7 | 收支查询 | 3 | 收入+支出+利润分析 |
| 8 | 排班查询 | 1 | 排班信息 |
| 9 | 优惠券查询 | 2 | 优惠券信息+分析 |
| 10 | 评价查询 | 2 | 评价列表+分析 |
| 11 | 顾客信息查询 | 1 | 顾客基本信息 |
| 12 | 顾客套餐剩余次数 | 1 | 剩余次数查询 |
| 13 | 退款分析 | 3 | 状态统计+原因分布+分析建议 |
| 14 | 员工绩效 | 3 | 核销统计+考勤统计+绩效分析 |
| 15 | 月度对比 | 3 | 本月+上月+对比分析 |
| 16 | 营销效果 | 2 | 优惠券使用+效果分析 |
| 17 | 顾客画像 | 3 | 消费频次+来源分布+画像分析 |

---

## 后台系统导航

当智能助手无法直接解决问题时，引导用户到后台系统操作：

| 页面 | 路径 | 功能 |
|------|------|------|
| 退款管理 | /trade/refund | 批准/拒绝退款、查看退款记录 |
| 顾客管理 | /customer | 查看顾客信息、管理顾客 |
| 库存管理 | /inventory | 查看库存、入库/出库 |
| 优惠券管理 | /marketing/coupon | 创建/发放优惠券 |
| 员工管理 | /system/staff | 管理员工账号 |
| 角色管理 | /system/role | 管理角色和权限 |
| 字典管理 | /system/dict | 管理系统字典 |
| 套餐管理 | /package | 管理服务套餐 |
| 评价管理 | /feedback | 查看/回复评价 |
| 排班管理 | /finance/schedule | 管理员工排班 |

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

### v0.8.0 (2026-06-22)

**Router 优化**
- `_check_question` prompt 增加操作类请求不追问规则
- 动态快捷问题生成（根据追问上下文生成相关问题）
- quick_questions SSE 事件顺序修复（移到 done 之前）
- `_generate_dynamic_quick_questions` 增加关键词匹配

**NL2SQL 优化**
- 并行候选数量限制为 2（避免超出 LLM API batch size 限制）
- NL2SQL 缓存 key 优化（用 original_task 做 key）

**Agent Loop 优化**
- 选择弹窗标题优化（使用中文描述而非字段名）
- 物料不存在时返回详细提示（引导到后台添加）
- 修复 TOOL_DISPLAY_NAMES 作用域问题
- Agent Loop 不校验 required 参数（由工具 confirm 弹窗处理）

**LLM Agent 优化**
- 提示词增加工具能力列表（防止 LLM 编造"不支持"）
- 提示词增加后台系统导航信息

**图片上传**
- 实现 handleUpload 功能（调用 uploadFile API）
- 新增图片预览栏（显示缩略图 + 移除按钮）
- Vision Agent 使用 base64 编码（替代 file:// URL）
- 配置静态文件服务（/file/upload/ 路径）

**其他优化**
- Supervisor 任务在 SSE 断开后自动取消
- 流式输出与 session 内容一致性修复

### v0.7.0 (2026-06-21)

**Skill 体系优化**
- 优化"今日经营概况"：3步→6步，新增新顾客数、热销套餐、库存预警
- 优化"本月经营情况分析"：4步→6步，新增退款统计、热销套餐
- 新增 5 个 Skill：退款分析、员工绩效、月度对比、营销效果、顾客画像
- 现有 Skill 增加分析步骤（套餐查询、员工查询、优惠券查询）
- 所有 Skill SQL 查询对照数据库 schema 验证通过

**Supervisor 重试机制**
- `_execute_sub_tasks_serial_with_confirm` 添加重试逻辑（最多 2 次）
- 查询型和操作型子任务都支持重试
- 重试时发送进度通知

**任务结果结构化传递**
- `_execute_query_sub_task` 传递 `task_results` 参数
- LLM Agent 接收独立的任务执行结果（不混入任务描述）
- 系统提示词增加任务执行结果使用规则

**Router 优化**
- 合并重复的 `route()` 方法
- `_check_question` 增加 `need_requery` 判断
- 确认性回复规则（"是的"等确认语句）

### v0.6.0 (2026-06-21)

**LLM 自主探索能力**
- 新增探索工具：`list_tables`、`describe_table`、`search_docs`
- LLM 可以主动查询数据库结构和知识库
- 遇到不确定信息时主动探索，而非猜测

**后台系统导航**
- 新增 `data/system_capabilities.json` 记录所有后台页面功能
- Agent Loop 系统提示词增加执行规则和后台导航
- 无法解决时引导用户到对应页面操作

**NL2SQL 输出规范**
- 状态字段必须映射为中文标签（CASE WHEN）
- 列名使用中文别名
- 金额字段使用 FORMAT 格式化

**Router 优化**
- 合并三个检查方法为 `_check_question`（一次 LLM 调用）
- 新增 `need_requery` 判断（用户需要查询数据）
- 统一数据查询路由（所有查询走 nl2sql）

**批量确认优化**
- SubTask 增加 tool_name 字段
- Supervisor 支持操作型子任务的确认流程
- 新增 POST /api/chat/batch_confirm 端点
- 前端 BatchConfirmCard 组件

**流式输出优化**
- NL2SQL 并行生成候选 SQL（3 个候选并行，节省 30 秒）
- Session 保存 LLM 格式化后的内容（非原始 SQL 输出）

**操作工具统一**
- 所有 9 个操作工具改为调用 Java 后端 API
- 新增 backend_client.py 封装 Java API 调用

### v0.5.0 (2026-06-20)

**Agent Loop**
- LLM 自主规划参数获取（TOOL_REQUIREMENTS 驱动）
- 支持 extract 模式（first/all_concat/value）
- 支持排除逻辑（exclude_ids/exclude_names）
- 参数类型自动转换

**Router 优化**
- JSON 解析失败重试机制（最多 2 次）
- 智能 fallback（操作类→TOOL，其他→RAG）

### v0.4.0 (2026-06-13)

**安全修复**
- 移除 GET /stream 端点，统一 POST + Authorization Header
- Token 缓存改用 TTLCache(maxsize=10000)
- SSL 验证按环境控制
- confirm 操作添加角色权限二次校验

**稳定性修复**
- HITL 改用 Redis 持久化
- 库存操作添加事务包裹
- 工具执行添加超时保护

**测试**
- 新增 44 个单元测试（auth/hitl/safety）

### v1.0 (2026-06-01)
- 初始版本

---

## 部署说明

### 环境要求

| 依赖 | 版本 |
|------|------|
| Python | 3.10+ |
| MySQL | 8.0+ |
| Redis | 6.0+ |
| Node.js | 20+ (前端) |

### 打包部署

```bash
# 后端打包
cd shop-ai-service
pip install -r requirements.txt
python -m app.main

# 前端打包
cd shop-copilot-chat
pnpm install
pnpm build
```

### 环境变量

```bash
# 必需配置
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-llm-endpoint
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DATABASE=shop_operate_system
REDIS_HOST=localhost
REDIS_PORT=6379
BACKEND_URL=http://localhost:8081
ENVIRONMENT=production

# 可选配置
TOKEN_CACHE_TTL=300
AGENT_TIMEOUT=60
HITL_REFUND_THRESHOLD=100.0
```

### 生产环境注意事项

1. **SSL 证书**：生产环境必须配置 SSL（`ENVIRONMENT=production`）
2. **Redis**：确保 Redis 连接正常，用于 Token 缓存和防重复提交
3. **MySQL**：确保数据库已初始化（执行 `shop_operate_system_db.sql`）
4. **日志**：生产环境日志级别建议设为 WARNING
5. **超时**：工具执行超时默认 60 秒，可根据需要调整

---

## License

MIT
