# ShopCopilot - 店铺智能助手 AI Service

基于 FastAPI + LangChain 构建的 AI Agent 服务，为店铺提供智能问答、数据分析、工具调用等功能。

## 🆕 最新更新（v2.0）

### 1. Skills 预设任务机制
- **预设 Skills**：12 个常见业务场景的预设执行步骤
- **智能匹配**：根据用户问题自动匹配最合适的 Skill
- **高成功率**：预定义 SQL 查询，避免 LLM 生成错误

| Skill | 触发关键词 | 功能 |
|-------|-----------|------|
| 本月经营分析 | 本月、经营、分析 | 查询营收/顾客/支出并分析 |
| 今日经营概况 | 今天、今日、日报 | 查询今日销售/核销数据 |
| 顾客信息查询 | 查XX顾客、顾客信息 | 查询顾客基本信息和余额 |
| 顾客套餐剩余 | 剩余次数、还有多少次 | 查询顾客各套餐剩余次数 |
| 库存查询 | 库存、物料、缺货 | 查询当前库存状态 |
| 收支查询 | 收入、支出、利润 | 查询收入支出并计算利润 |
| 套餐查询 | 套餐、服务、价格 | 查询所有套餐信息 |
| 员工查询 | 员工、服务员 | 查询员工列表 |
| 排班查询 | 排班、班次、值班 | 查询排班信息 |
| 优惠券查询 | 优惠券、折扣 | 查询优惠券列表 |
| 评价查询 | 评价、反馈、评分 | 查询顾客评价 |
| 顾客消费分析 | 顾客、消费、会员 | 分析顾客消费情况 |

### 2. 经验池系统
- **自动学习**：成功/失败的查询自动记录到经验池
- **解决流程**：记录完整的解决步骤，供后续参考
- **智能检索**：相似问题自动匹配历史经验
- **自动清理**：7 天过期，低质量案例自动清理

### 3. LLM Agent（新增）
- **专门用于**：总结、分析、建议等任务
- **不触发搜索**：避免不必要的互联网搜索
- **上下文感知**：基于店铺信息和历史对话

### 4. 历史上下文支持
- **会话记忆**：同一会话内的对话历史自动保留
- **智能压缩**：超过 5 轮的历史自动压缩为纪要
- **上下文注入**：Router 分析问题时就注入历史上下文
- **跨会话隔离**：不同店铺的会话完全隔离

### 5. 搜索优化
- **关键词优化**：LLM 自动优化搜索关键词
- **中文搜索**：指定中文语言，避免英文结果
- **内容评审**：搜索结果自动评审相关性
- **智能重试**：不相关时自动重试（最多 2 次）

### 6. NL2SQL 增强
- **CoT 推理**：分步思考，提高 SQL 准确性
- **多候选选择**：生成 3 个候选 SQL，选择最佳
- **错误分类修复**：根据错误类型针对性修复
- **MySQL 规则库**：内置常见错误避免规则
- **同义词映射**：自动识别同义词（如"营收"→"revenue"）

### 7. JSON 解析优化
- **双层保障**：Prompt 明确要求 + 代码修复逻辑
- **ast.literal_eval**：安全处理 Python 字典格式
- **智能修复**：自动修复单引号、缺失括号等问题

### 8. 进度输出优化
- **步骤展示**：显示"步骤 1/5: 正在执行..."
- **状态图标**：✓ 完成、✗ 失败、⏳ 执行中
- **重试提示**：显示"重试第 2 次"
- **质量评分**：评审未通过时显示质量分数

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
| **任务调度** | APScheduler |

---

## 项目结构

```
shop-ai-service/
├── app/
│   ├── chat/                    # 聊天模块
│   │   ├── router.py            # 聊天路由
│   │   └── stream_handler.py    # SSE 流式处理
│   ├── multi_agent/             # 多 Agent 模块
│   │   ├── router.py            # 智能路由（Skills + LLM）
│   │   ├── supervisor.py        # Supervisor 调度器
│   │   ├── rag_agent.py         # RAG 知识问答
│   │   ├── nl2sql_agent.py      # NL2SQL 数据查询
│   │   ├── tool_agent.py        # 工具调用
│   │   ├── llm_agent.py         # LLM 总结分析
│   │   └── vision_agent.py      # 图像识别
│   ├── skills/                  # 预设 Skills
│   │   ├── models.py            # 数据模型
│   │   └── manager.py           # Skills 管理器
│   ├── experience/              # 经验池系统
│   │   ├── models.py            # 数据模型
│   │   ├── pool.py              # 经验池管理
│   │   └── cleanup.py           # 定期清理
│   ├── rag/                     # RAG 模块
│   │   ├── agentic_rag.py       # 智能 RAG
│   │   ├── crag.py              # CRAG 文档分级
│   │   ├── self_rag.py          # Self-RAG 自检
│   │   └── session.py           # 会话管理
│   ├── nl2sql/                  # NL2SQL 模块
│   │   ├── schema_linker.py     # Schema 链接（含同义词映射）
│   │   ├── safety.py            # SQL 安全校验
│   │   ├── executor.py          # SQL 执行器
│   │   ├── fewshot_vector.py    # Few-shot 向量检索
│   │   └── mysql_rules.py       # MySQL 规则库
│   ├── search/                  # 搜索模块
│   │   └── tavily_client.py     # Tavily 搜索客户端
│   ├── utils/                   # 工具模块
│   │   └── json_parser.py       # JSON 安全解析
│   └── config.py                # 配置文件
├── data/                        # 数据目录
│   └── knowledge/               # 知识库文档
├── monitoring/                  # 监控模块
│   └── langfuse_config.py       # LangFuse 配置
└── .env                         # 环境变量
```

---

## 核心架构

### 1. 智能路由流程

```
用户问题
    ↓
【1. Skill 匹配】→ 匹配成功 → 直接执行预定义步骤
    ↓ 匹配失败
【2. LLM 路由】→ 分析问题类型
    ↓
    ├── 知识性问题 → RAG Agent
    ├── 数据查询 → NL2SQL Agent
    ├── 工具调用 → Tool Agent
    ├── 总结分析 → LLM Agent
    └── 复杂任务 → Supervisor（多 Agent 协作）
```

### 2. 历史上下文注入

```
用户问题 + 历史对话
    ↓
Router 分析（注入历史上下文）
    ↓
理解"重试上面的问题"等上下文相关指令
    ↓
正确路由到对应的 Agent
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
# Python 3.10+
python --version

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填写以下配置：

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

# LangFuse（可选）
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=your-public-key
LANGFUSE_SECRET_KEY=your-secret-key
```

### 3. 启动服务

```bash
python -m app.main
```

服务启动后访问：http://localhost:8000/docs

---

## API 接口

### 1. 聊天接口（SSE 流式）

```
GET /api/chat/stream?message={message}&session_id={session_id}&token={token}&shop_id={shop_id}
```

**SSE 输出格式**：

```json
// 理解问题
{"type": "thinking", "content": "用户想要查询本月的销售数据", "step": "理解问题", "done": false}

// 执行计划
{"type": "plan", "content": "1. 查询本月营收数据\n2. 查询本月顾客数据\n3. 汇总分析", "step": "执行计划", "done": false}

// 执行步骤
{"type": "processing", "content": "正在执行: 查询本月营收数据", "step": "步骤 1/3", "done": false}
{"type": "success", "content": "✓ 完成: 查询本月营收数据", "step": "步骤 1/3", "done": false}

// 最终答案
{"type": "answer", "content": "本月经营情况分析...", "step": "最终答案", "done": false}

// 完成
{"type": "done", "content": "", "step": "完成", "done": true}
```

### 2. 其他接口

```bash
# 健康检查
GET /health

# 功能列表
GET /api/features

# API 文档
GET /docs
```

---

## Skills 预设任务

### 匹配逻辑

```python
# 1. 关键词匹配
keywords = ["本月", "经营", "分析"]

# 2. 正则模式匹配
patterns = [r"(本月|这个月).*?(经营|情况|分析)"]

# 3. 优先级排序
priority = 10  # 越高越优先
```

### 添加新 Skill

```python
# 在 app/skills/manager.py 中添加
self.register(Skill(
    id="new_skill",
    name="新技能",
    description="技能描述",
    keywords=["关键词1", "关键词2"],
    patterns=[r"正则表达式"],
    steps=[
        SkillStep(
            step=1,
            agent="nl2sql",
            task="任务描述",
            query="SELECT ... FROM ... WHERE shop_id = :shop_id",
        ),
    ],
    priority=5,
))
```

---

## 经验池系统

### 记录成功案例

```python
await experience_pool.record_success(
    agent_type="nl2sql",
    question="今天营业额多少",
    solution="SELECT SUM(paid_amount) FROM purchases WHERE ...",
    result_summary="今日营业额 ¥2,580",
    solving_process=[
        {"step": 1, "description": "Schema Linking", "detail": "识别相关表"},
        {"step": 2, "description": "SQL 生成", "detail": "生成查询语句"},
    ],
)
```

### 检索经验

```python
similar_exps = await experience_pool.retrieve_similar(
    agent_type="nl2sql",
    question="今天销售额多少",
    k=3,
)
```

---

## 配置说明

### LLM 配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `LLM_API_KEY` | API Key | - |
| `LLM_BASE_URL` | API 地址 | `https://token-plan-cn.xiaomimimo.com/v1` |
| `LLM_MODEL` | 模型名称 | `mimo-v2.5` |
| `LLM_TEMPERATURE` | 温度参数 | `0.7` |
| `LLM_MAX_TOKENS` | 最大 Token | `2000` |

### 缓存配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `REDIS_HOST` | Redis 地址 | `localhost` |
| `REDIS_PORT` | Redis 端口 | `6379` |
| `REDIS_DB` | Redis 数据库 | `0` |

---

## 常见问题

### 1. Chroma 遥测错误

```
Failed to send telemetry event...
```

**解决**：已在代码中禁用遥测，如仍出现，设置环境变量：
```bash
ANONYMIZED_TELEMETRY=False
```

### 2. JSON 解析错误

```
Expecting property name enclosed in double quotes
```

**解决**：已使用 `safe_parse_json` 函数自动修复，如仍出现，检查 LLM 返回格式。

### 3. SQL 执行失败

```
Column 'shop_id' in where clause is ambiguous
```

**解决**：已优化 `add_shop_filter` 函数，自动检测子查询并使用正确的表别名。

---

## 更新日志

### v2.0 (2026-06-12)
- ✨ 新增 Skills 预设任务机制
- ✨ 新增经验池系统
- ✨ 新增 LLM Agent
- ✨ 新增历史上下文支持
- 🔧 优化 NL2SQL（CoT 推理、多候选、错误修复）
- 🔧 优化搜索（关键词优化、中文搜索、内容评审）
- 🔧 优化 JSON 解析（双层保障）
- 🔧 优化进度输出（步骤展示、重试提示）
- 🐛 修复 Chroma 遥测错误
- 🐛 修复会话持久化问题
- 🐛 修复历史上下文注入问题

### v1.0 (2026-06-01)
- 🎉 初始版本
- ✨ 多 Agent 协作架构
- ✨ RAG + NL2SQL + Tool + Vision
- ✨ SSE 流式输出
- ✨ LangFuse 可观测性

---

## License

MIT
