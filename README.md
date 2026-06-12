# ShopCopilot - 店铺智能助手 AI Service

基于 FastAPI + LangChain 构建的 AI Agent 服务，为店铺提供智能问答、数据分析、工具调用等功能。

## 🆕 最新更新（v2.1）

### 1. 任务计划执行机制
- **Router 分析**：LLM 分析问题，生成执行计划
- **按计划执行**：按步骤执行任务，每个步骤的结果传递给下一步骤
- **结果汇总**：所有步骤完成后，LLM 汇总结果并输出

### 2. Skills 预设任务机制
- **预设 Skills**：12 个常见业务场景的预设执行步骤
- **智能匹配**：根据用户问题自动匹配最合适的 Skill
- **高成功率**：预定义 SQL 查询，避免 LLM 生成错误

### 3. 经验池系统
- **自动学习**：成功/失败的查询自动记录到经验池
- **解决流程**：记录完整的解决步骤，供后续参考
- **智能检索**：相似问题自动匹配历史经验

### 4. LLM Agent
- **专门用于**：总结、分析、建议等任务
- **不触发搜索**：避免不必要的互联网搜索
- **上下文感知**：基于店铺信息和历史对话

### 5. 历史上下文支持
- **会话记忆**：同一会话内的对话历史自动保留
- **智能压缩**：超过 5 轮的历史自动压缩为纪要
- **上下文注入**：Router 分析问题时就注入历史上下文

### 6. 搜索优化
- **关键词优化**：LLM 自动优化搜索关键词
- **中文搜索**：指定中文语言，避免英文结果
- **内容评审**：搜索结果自动评审相关性

### 7. NL2SQL 增强
- **CoT 推理**：分步思考，提高 SQL 准确性
- **多候选选择**：生成 3 个候选 SQL，选择最佳
- **错误分类修复**：根据错误类型针对性修复
- **MySQL 规则库**：内置常见错误避免规则

### 8. 进度输出优化
- **步骤展示**：显示"步骤 1/5: 正在执行..."
- **状态图标**：✓ 完成、✗ 失败、⏳ 执行中
- **重试提示**：显示"重试第 2 次"

---

## 技术栈

| 类别 | 技术 |
|------|------|
| **Web 框架** | FastAPI |
| **LLM** | MiMo v2.5 / MiMo v2.5 Pro |
| **向量数据库** | Chroma |
| **关系数据库** | MySQL 8.0+ |
| **缓存** | Redis |
| **可观测性** | LangFuse |

---

## 项目结构

```
shop-ai-service/
├── app/
│   ├── chat/                    # 聊天模块
│   │   ├── router.py            # 聊天路由
│   │   └── stream_handler.py    # SSE 流式处理（含计划执行）
│   ├── multi_agent/             # 多 Agent 模块
│   │   ├── router.py            # 智能路由（LLM 判断 + Skills）
│   │   ├── supervisor.py        # Supervisor 调度器
│   │   ├── rag_agent.py         # RAG 知识问答
│   │   ├── nl2sql_agent.py      # NL2SQL 数据查询
│   │   ├── tool_agent.py        # 工具调用
│   │   └── llm_agent.py         # LLM 总结分析
│   ├── skills/                  # 预设 Skills
│   │   └── manager.py           # Skills 管理器
│   ├── experience/              # 经验池系统
│   │   ├── models.py            # 数据模型
│   │   └── pool.py              # 经验池管理
│   ├── rag/                     # RAG 模块
│   ├── nl2sql/                  # NL2SQL 模块
│   ├── search/                  # 搜索模块
│   │   └── tavily_client.py     # Tavily 搜索
│   └── chroma_config.py         # Chroma 配置
└── .env                         # 环境变量
```

---

## 核心架构

### 1. 任务计划执行流程

```
用户问题
    ↓
【Router 分析】
    understanding: "用户想要..."
    analysis: "需要..."
    plan: [
        {action: "步骤1", tool: "nl2sql"},
        {action: "步骤2", tool: "llm"},
    ]
    ↓
【按计划执行】
    步骤1: NL2SQL 查询数据 → 结果1
    步骤2: LLM 分析结果 → 结果2（基于结果1）
    ↓
【汇总输出】
    "根据查询结果，分析如下..."
```

### 2. 路由判断逻辑

```
用户问题
    ↓
上下文相关问题？ → 是 → LLM Agent
    ↓ 否
匹配 Skills？ → 是 → 执行预设步骤
    ↓ 否
LLM 判断类型 → nl2sql/rag/tool/llm
    ↓
执行任务
```

### 3. 经验池学习

```
执行成功 → 记录解决方案 + 解决流程
    ↓
下次遇到相似问题 → 检索经验池
    ↓
直接使用经验 或 参考解决流程
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
```

### 3. 启动服务

```bash
python -m app.main
```

---

## API 接口

### 聊天接口（SSE 流式）

```
GET /api/chat/stream?message={message}&session_id={session_id}&token={token}&shop_id={shop_id}
```

**SSE 输出格式**：

```json
// 理解问题
{"type": "thinking", "content": "用户想要查询本月的销售数据", "step": "理解问题", "done": false}

// 执行计划
{"type": "plan", "content": "1. 查询本月营收数据\n2. 查询本月顾客数据", "step": "执行计划", "done": false}

// 执行步骤
{"type": "processing", "content": "步骤 1/2: 查询本月营收数据...", "step": "步骤 1", "done": false}
{"type": "processing", "content": "✓ 步骤 1 完成", "step": "步骤 1", "done": false}

// 最终答案
{"type": "answer", "content": "本月经营情况分析...", "step": "最终答案", "done": false}
```

---

## Skills 预设任务

| Skill | 触发关键词 | 功能 |
|-------|-----------|------|
| 本月经营分析 | 本月、经营、分析 | 查询营收/顾客/支出并分析 |
| 今日经营概况 | 今天、今日、日报 | 查询今日销售/核销数据 |
| 顾客信息查询 | 查XX顾客、顾客信息 | 查询顾客基本信息和余额 |
| 顾客套餐剩余 | 剩余次数、还有多少次 | 查询顾客各套餐剩余次数 |
| 库存查询 | 库存、物料、缺货 | 查询当前库存状态 |
| 收支查询 | 收入、支出、利润 | 查询收入支出并计算利润 |

---

## 更新日志

### v2.1 (2026-06-13)
- ✨ 新增任务计划执行机制
- 🔧 优化 Router 使用 LLM 判断问题类型
- 🔧 优化上下文传递（Router → Agent）
- 🐛 修复历史上下文注入问题
- 🐛 修复 Chroma 遥测错误

### v2.0 (2026-06-12)
- ✨ 新增 Skills 预设任务机制
- ✨ 新增经验池系统
- ✨ 新增 LLM Agent
- ✨ 新增历史上下文支持
- 🔧 优化 NL2SQL（CoT 推理、多候选、错误修复）
- 🔧 优化搜索（关键词优化、中文搜索、内容评审）

### v1.0 (2026-06-01)
- 🎉 初始版本
- ✨ 多 Agent 协作架构
- ✨ RAG + NL2SQL + Tool + Vision
- ✨ SSE 流式输出

---

## License

MIT
