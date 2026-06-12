# ShopCopilot 店铺助手使用文档

## 目录

1. [概述](#概述)
2. [快速开始](#快速开始)
3. [统一聊天接口](#统一聊天接口)
4. [功能模块](#功能模块)
   - [智能问答（RAG）](#智能问答rag)
   - [数据查询（NL2SQL）](#数据查询nl2sql)
   - [工具调用（Tool Calling）](#工具调用tool-calling)
   - [多 Agent 协作](#多-agent-协作)
   - [图像识别（Vision）](#图像识别vision)
5. [工具列表](#工具列表)
6. [角色权限](#角色权限)
7. [使用示例](#使用示例)
8. [常见问题](#常见问题)

---

## 概述

ShopCopilot 店铺助手是一款基于 AI Agent 的智能助手，帮助店铺管理者和员工高效完成日常工作。它支持自然语言交互，可以：

- 回答顾客关于套餐、价格、营业时间的咨询
- 用自然语言查询店铺经营数据
- 查询顾客信息、库存状态、排班考勤等
- 分析经营状况并提供决策建议
- 识别图像中的文字信息

### 核心优势

| 优势 | 说明 |
|------|------|
| 🗣️ 自然语言交互 | 无需学习复杂操作，用日常语言提问即可 |
| 🔐 安全认证 | 通过后台管理系统 Token 验证，确保数据安全 |
| 👥 角色权限 | 不同角色（店长/导玩员/仓管/财务）有不同的访问权限 |
| 🏪 店铺隔离 | A 店铺只能查询 A 店铺的数据，互不干扰 |
| 🤖 智能路由 | 自动识别问题类型，路由到合适的处理模块 |
| 📡 流式输出 | SSE 实时返回思考步骤、处理步骤和最终答案 |

---

## 快速开始

### 1. 获取 Token

首先需要登录后台管理系统获取 Token：

```
POST /api/auth/login
{
    "username": "your_username",
    "password": "your_password",
    "captchaId": "...",
    "captchaValue": "..."
}
```

响应中会返回 `token` 和 `refreshToken`。

### 2. 构建请求头

根据是否选择店铺，使用不同的 Token 格式：

```
# 已选择店铺（推荐）
Authorization: Bearer-{shopId}-{token}

# 未选择店铺（超管）
Authorization: Bearer {token}
```

**示例**：
```
Authorization: Bearer-1-abc123def456ghi789
```

### 3. 调用统一聊天接口

```bash
# 统一聊天接口（流式输出）
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123def456" \
  -d '{"message": "本月营收是多少？"}'
```

---

## 统一聊天接口

### 接口说明

所有用户提问都通过统一接口处理，由 LLM 自动判断并路由到合适的模块。

**接口地址**：`POST /api/chat/stream`

**请求格式**：
```json
{
    "message": "本月营收是多少？",
    "session_id": "user_123",  // 可选
    "image_url": "https://..."  // 可选，图像识别时使用
}
```

### SSE 输出格式

```json
// 思考步骤
data: {"type": "thinking", "content": "正在分析您的问题...", "step": "意图分析", "done": false}

// 处理步骤
data: {"type": "processing", "content": "正在检索知识库...", "step": "知识检索", "done": false}

// 工具结果
data: {"type": "tool_result", "content": "本月营收: ¥15,000", "step": "工具结果", "done": false}

// 最终答案
data: {"type": "answer", "content": "根据查询结果，本月营收为 ¥15,000...", "step": "最终答案", "done": false}

// 完成
data: {"type": "done", "content": "", "step": "完成", "done": true}

// 错误
data: {"type": "error", "content": "处理失败: ...", "step": "错误", "done": true}
```

### 自动路由逻辑

| 用户问题 | 路由结果 | 调用模块 |
|----------|----------|----------|
| "你们有什么套餐？" | 单任务 → RAG | 知识问答 |
| "本月营收多少？" | 单任务 → NL2SQL | 数据查询 |
| "查一下张三的信息" | 单任务 → Tool | 工具调用 |
| "分析本月经营情况" | 多任务 → Supervisor | 多 Agent 协作 |
| "识别这张图片" | 单任务 → Vision | 图像识别 |

### 输出类型说明

| 类型 | 说明 |
|------|------|
| `thinking` | 思考步骤（意图分析、任务路由） |
| `processing` | 处理步骤（知识检索、SQL 生成、工具调用） |
| `tool_result` | 工具执行结果 |
| `answer` | 最终答案 |
| `done` | 完成标志 |
| `error` | 错误信息 |

---

## 功能模块

### 智能问答（RAG）

回答顾客关于套餐、价格、营业时间等常见问题。

#### 适用场景

- 顾客咨询："你们这里有周卡吗？"
- 顾客询问："多少钱？"
- 顾客问："营业到几点？"

#### 使用方式

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123" \
  -d '{"message": "你们这里有周卡吗？"}'
```

#### 输出示例

```
data: {"type": "thinking", "content": "正在分析您的问题...", "step": "意图分析", "done": false}
data: {"type": "thinking", "content": "判断为单任务，使用知识问答处理", "step": "任务路由", "done": false}
data: {"type": "processing", "content": "正在检索知识库...", "step": "知识检索", "done": false}
data: {"type": "answer", "content": "我们提供周卡服务，价格为298元...", "step": "回答生成", "done": false}
data: {"type": "done", "content": "", "step": "完成", "done": true}
```

---

### 数据查询（NL2SQL）

用自然语言查询店铺经营数据，无需编写 SQL。

#### 适用场景

- 店长查询："本月营业额是多少？"
- 数据分析："哪个套餐卖得最好？"
- 经营对比："本周和上周比怎么样？"

#### 支持的查询类型

| 类型 | 示例问题 |
|------|----------|
| 营业额统计 | "今天/本周/本月/本年营业额是多少？" |
| 顾客分析 | "本月有多少新顾客？" |
| 套餐销量 | "哪个套餐卖得最好？" |
| 库存查询 | "库存不足的物料有哪些？" |
| 员工绩效 | "本月核销最多的员工是谁？" |
| 收支统计 | "本月收入和支出分别是多少？" |

#### 使用方式

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123" \
  -d '{"message": "本月营业额是多少？"}'
```

#### 输出示例

```
data: {"type": "thinking", "content": "正在分析您的问题...", "step": "意图分析", "done": false}
data: {"type": "thinking", "content": "判断为单任务，使用数据查询处理", "step": "任务路由", "done": false}
data: {"type": "processing", "content": "正在生成 SQL 查询...", "step": "SQL 生成", "done": false}
data: {"type": "processing", "content": "正在执行 SQL 查询...", "step": "SQL 执行", "done": false}
data: {"type": "answer", "content": "本月营收: ¥15,000", "step": "查询结果", "done": false}
data: {"type": "done", "content": "", "step": "完成", "done": true}
```

---

### 工具调用（Tool Calling）

查询店铺各类数据，包括营收、顾客、库存、排班等。

#### 适用场景

- 查询顾客："帮我查一下张三的信息"
- 库存管理："库存不足的物料有哪些？"
- 排班查询："今天的排班表是什么？"

#### 使用方式

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123" \
  -d '{"message": "查询库存不足的物料"}'
```

#### 输出示例

```
data: {"type": "thinking", "content": "正在分析您的问题...", "step": "意图分析", "done": false}
data: {"type": "thinking", "content": "判断为单任务，使用工具调用处理", "step": "任务路由", "done": false}
data: {"type": "processing", "content": "正在调用工具...", "step": "工具调用", "done": false}
data: {"type": "answer", "content": "当前有 3 种物料库存不足...", "step": "工具结果", "done": false}
data: {"type": "done", "content": "", "step": "完成", "done": true}
```

---

### 多 Agent 协作

支持复杂业务分析，自动拆分任务并调用多个工具完成任务。

#### 核心能力

- **任务拆分**：将复杂问题自动拆分成多个子任务
- **依赖关系**：支持子任务之间的依赖关系，自动串行执行
- **并行执行**：无依赖的子任务并行执行，提高效率
- **结果汇总**：自动汇总多个子任务的结果，生成完整回答

#### 适用场景

- 经营分析："帮我分析一下本月的经营情况"
- 综合查询："查一下今天的营收和库存预警"
- 决策建议："我应该重点关注哪些方面？"
- **多步骤任务**："分析一下本月的套餐销售情况给出改进建议"

#### 使用方式

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123" \
  -d '{"message": "帮我分析一下本月的经营情况，包括营收、顾客和库存"}'
```

#### 输出示例（无依赖，并行执行）

```
data: {"type": "thinking", "content": "正在分析您的问题...", "step": "意图分析", "done": false}
data: {"type": "thinking", "content": "判断为多任务协作，使用 Supervisor 处理", "step": "任务路由", "done": false}
data: {"type": "processing", "content": "正在启动多 Agent 协作...", "step": "任务分解", "done": false}
data: {"type": "answer", "content": "本月经营分析：\n1. 营收情况：本月营收15000元...\n2. 顾客分析：新顾客20人...\n3. 库存预警：有3种物料库存不足...", "step": "最终答案", "done": false}
data: {"type": "done", "content": "", "step": "完成", "done": true}
```

#### 输出示例（有依赖，串行执行）

```
data: {"type": "thinking", "content": "正在分析您的问题...", "step": "意图分析", "done": false}
data: {"type": "thinking", "content": "判断为多任务协作，使用 Supervisor 处理", "step": "任务路由", "done": false}
data: {"type": "processing", "content": "正在启动多 Agent 协作...", "step": "任务分解", "done": false}
data: {"type": "processing", "content": "检测到依赖关系，使用串行执行", "step": "执行策略", "done": false}
data: {"type": "answer", "content": "套餐销售分析：\n1. 查询结果：本月套餐销售总额15000元...\n2. 分析：周卡销售最好，月卡次之...\n3. 建议：增加周卡库存，优化月卡价格...", "step": "最终答案", "done": false}
data: {"type": "done", "content": "", "step": "完成", "done": true}
```

#### 任务拆分示例

**用户问题**："分析一下本月的套餐销售情况给出改进建议"

**自动拆分结果**：
```json
[
    {"id": 1, "task": "查询本月套餐销售数据", "agent": "nl2sql", "depends_on": []},
    {"id": 2, "task": "分析套餐销售情况", "agent": "nl2sql", "depends_on": [1]},
    {"id": 3, "task": "给出改进建议", "agent": "rag", "depends_on": [1, 2]}
]
```

**执行流程**：
```
子任务1: 查询本月套餐销售数据
         ↓ (结果传递给子任务2)
子任务2: 分析套餐销售情况
         ↓ (结果传递给子任务3)
子任务3: 给出改进建议
         ↓
    汇总所有结果，输出完整回答
```

---

### 图像识别（Vision）

支持 OCR 文字识别和图像理解。

#### 适用场景

- 识别收据："识别这张收据的内容"
- 识别订单："识别这个订单的信息"
- 识别清单："识别这个库存清单"

#### 使用方式

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123" \
  -d '{"message": "识别这张图片的内容", "image_url": "https://example.com/image.jpg"}'
```

#### 输出示例

```
data: {"type": "thinking", "content": "正在分析您的问题...", "step": "意图分析", "done": false}
data: {"type": "thinking", "content": "判断为单任务，使用图像识别处理", "step": "任务路由", "done": false}
data: {"type": "processing", "content": "正在识别图像...", "step": "图像识别", "done": false}
data: {"type": "answer", "content": "识别结果：\n订单号: 20240101001\n日期: 2024-01-01\n...", "step": "识别结果", "done": false}
data: {"type": "done", "content": "", "step": "完成", "done": true}
```

---

## 工具列表

### 营收相关

| 工具 | 功能 | 示例问题 |
|------|------|----------|
| `query_revenue` | 查询营收数据 | "今天/本周/本月营收是多少？" |
| `query_top_packages` | 查询热销套餐 | "本月热销套餐是什么？" |

### 顾客相关

| 工具 | 功能 | 示例问题 |
|------|------|----------|
| `query_customer` | 搜索顾客信息 | "查一下顾客张三的信息" |
| `query_purchases` | 查询购买记录 | "张三买了什么套餐？" |
| `query_game_sessions` | 查询核销记录 | "张三用了几次？" |
| `query_refunds` | 查询退款记录 | "本月有退款吗？" |

### 套餐相关

| 工具 | 功能 | 示例问题 |
|------|------|----------|
| `query_packages` | 查询套餐列表 | "我们有哪些套餐？" |

### 库存相关

| 工具 | 功能 | 示例问题 |
|------|------|----------|
| `query_inventory` | 查询库存 | "颜料还有多少？" |
| `query_low_stock` | 查询库存预警 | "库存不足的物料有哪些？" |

### 员工相关

| 工具 | 功能 | 示例问题 |
|------|------|----------|
| `query_staff_performance` | 查询员工绩效 | "本月核销最多的员工是谁？" |
| `query_staff_list` | 查询员工列表 | "我们有哪些员工？" |

### 排队管理

| 工具 | 功能 | 示例问题 |
|------|------|----------|
| `query_active_sessions` | 查询当前座位占用 | "现在有多少客人在玩？" |

### 优惠券管理

| 工具 | 功能 | 示例问题 |
|------|------|----------|
| `query_coupons` | 查询优惠券列表 | "我们有哪些优惠券？" |
| `grant_coupon` | 发放优惠券 | "给顾客张三发一张优惠券" |
| `query_coupon_usages` | 查询优惠券使用记录 | "优惠券使用情况怎么样？" |

### 评价反馈

| 工具 | 功能 | 示例问题 |
|------|------|----------|
| `query_feedbacks` | 查询评价列表 | "最近有什么评价？" |
| `reply_feedback` | 回复评价 | "回复这条评价" |

### 排班考勤

| 工具 | 功能 | 示例问题 |
|------|------|----------|
| `query_staff_schedules` | 查询排班表 | "今天的排班是什么？" |
| `query_attendance_records` | 查询考勤记录 | "张三这个月迟到了几次？" |

### 通知消息

| 工具 | 功能 | 示例问题 |
|------|------|----------|
| `query_notifications` | 查询通知列表 | "有什么通知？" |
| `send_notification` | 发送通知 | "给所有员工发一条通知" |

### 财务报表

| 工具 | 功能 | 示例问题 |
|------|------|----------|
| `query_daily_snapshots` | 查询经营快照 | "最近7天的经营数据" |
| `query_revenue_trend` | 查询营收趋势 | "本月营收趋势怎么样？" |

---

## 角色权限

不同角色有不同的工具访问权限：

### 店长

拥有所有工具的访问权限，可以：
- 查询所有数据
- 管理优惠券、排班、通知
- 回复评价
- 查看财务报表

### 导玩员

可以访问与顾客服务相关的工具：
- 查询顾客信息
- 查询购买和核销记录
- 查询当前座位占用
- 查询和回复评价

### 仓管

可以访问库存相关工具：
- 查询库存
- 查询库存预警

### 财务

可以访问财务相关工具：
- 查询营收数据
- 查询热销套餐
- 查询经营快照
- 查询营收趋势

---

## 使用示例

### 示例1：顾客咨询

**场景**：顾客问"你们这里有周卡吗？多少钱？"

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123" \
  -d '{"message": "你们这里有周卡吗？多少钱？", "session_id": "customer_123"}'
```

### 示例2：店长查询经营数据

**场景**：店长想了解本月经营情况

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123" \
  -d '{"message": "帮我分析一下本月的经营情况，包括营收、顾客和库存"}'
```

### 示例3：导玩员查询顾客信息

**场景**：导玩员需要查询顾客张三的信息

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123" \
  -d '{"message": "查询顾客张三的信息"}'
```

### 示例4：查询排班表

**场景**：店长想查看今天的排班

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123" \
  -d '{"message": "今天的排班表是什么？"}'
```

### 示例5：查询库存预警

**场景**：仓管想查看库存不足的物料

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123" \
  -d '{"message": "库存不足的物料有哪些？"}'
```

### 示例6：图像识别

**场景**：识别收据内容

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer-1-abc123" \
  -d '{"message": "识别这张收据的内容", "image_url": "https://example.com/receipt.jpg"}'
```

---

## 常见问题

### Q1：Token 无效或已过期

**原因**：Token 已过期或格式错误

**解决**：
1. 重新登录后台管理系统获取新 Token
2. 检查 Token 格式是否正确：`Bearer-{shopId}-{token}`

### Q2：无权访问该店铺

**原因**：当前用户没有访问指定店铺的权限

**解决**：
1. 确认 Token 中的 shopId 是否正确
2. 联系管理员确认店铺权限

### Q3：查询结果不准确

**原因**：问题描述不够清晰或知识库未更新

**解决**：
1. 尝试更清晰地描述问题
2. 联系管理员更新知识库

### Q4：工具调用失败

**原因**：可能是权限不足或系统异常

**解决**：
1. 检查当前角色是否有该工具的访问权限
2. 查看错误信息，联系技术支持

### Q5：响应速度慢

**原因**：LLM 调用需要一定时间

**解决**：
1. 简化问题描述
2. 检查网络连接
3. 联系管理员检查 LLM 服务状态

### Q6：流式输出中断

**原因**：网络连接不稳定或服务异常

**解决**：
1. 检查网络连接
2. 查看服务日志
3. 联系技术支持

---

## 技术支持

如有问题，请联系技术支持：
- 邮箱：support@example.com
- 文档：http://localhost:8000/docs
