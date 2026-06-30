# 数据库表结构说明

## 核心业务表

### 1. purchases - 顾客购买/充值记录

**业务含义**：记录顾客的购买和充值行为，是营收统计的核心表。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| customer_id | bigint | 顾客ID |
| package_id | bigint | 套餐ID |
| purchase_type | varchar | 购买类型：purchase-购买套餐, recharge-充值 |
| channel | varchar | 渠道：store-门店, meituan-美团, douyin-抖音, miniapp-小程序, other-其他 |
| third_party_coupon_code | varchar | 第三方优惠券码 |
| coupon_usage_id | bigint | 使用的优惠券记录ID |
| start_date | date | 开始日期 |
| total_amount | decimal | 总金额 |
| paid_amount | decimal | 实付金额 |
| coupon_discount | decimal | 优惠券抵扣金额 |
| payment_method | varchar | 支付方式：wechat-微信, alipay-支付宝, bank-银行转账, cash-现金, other-其他, wallet-储值钱包 |
| status | tinyint | 状态：1-有效, 2-已退款, 3-已过期 |
| operator_staff_id | bigint | 操作员工ID |
| remark | varchar | 备注 |
| is_deleted | tinyint | 删除标记：0-正常, 1-已删除 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |
| deleted_time | datetime | 删除时间 |

**统计逻辑**：
- 今日营收：`SUM(paid_amount) WHERE DATE(created_at) = CURDATE() AND is_deleted = 0`
- 本月营收：`SUM(paid_amount) WHERE DATE_FORMAT(created_at, '%Y-%m') = DATE_FORMAT(CURDATE(), '%Y-%m') AND status = 1 AND is_deleted = 0`
- 今日订单：`COUNT(*) WHERE DATE(created_at) = CURDATE() AND is_deleted = 0`

---

### 2. revenue_records - 收入确认记录

**业务含义**：记录实际核销确认的收入，是实际收入统计的核心表。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| game_session_id | bigint | 游戏场次ID |
| purchase_id | bigint | 购买记录ID |
| amount | decimal | 收入金额 |
| confirmed_at | datetime | 确认时间 |
| confirmed_by | bigint | 确认员工ID（staff.id） |
| payment_method | varchar | 支付方式 |
| customer_id | bigint | 顾客ID |
| is_deleted | tinyint | 删除标记：0-正常, 1-已删除 |
| created_at | datetime | 创建时间 |
| deleted_time | datetime | 删除时间 |

**统计逻辑**：
- 今日收入：`SUM(amount) WHERE DATE(confirmed_at) = CURDATE()`
- 本月收入：`SUM(amount) WHERE DATE_FORMAT(confirmed_at, '%Y-%m') = DATE_FORMAT(CURDATE(), '%Y-%m')`

---

### 3. expenses - 费用支出

**业务含义**：记录店铺的运营成本。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| category_id | bigint | 支出分类ID |
| amount | decimal | 支出金额 |
| payment_method | varchar | 支付方式 |
| remark | varchar | 备注 |
| expense_date | date | 支出日期 |
| source_type | varchar | 来源类型（如：refund-退款） |
| source_id | bigint | 来源ID |
| operator_staff_id | bigint | 操作员工ID |
| is_deleted | tinyint | 删除标记：0-正常, 1-已删除 |
| created_at | datetime | 创建时间 |
| deleted_time | datetime | 删除时间 |

**统计逻辑**：
- 今日支出：`SUM(amount) WHERE expense_date = CURDATE()`
- 本月支出：`SUM(amount) WHERE DATE_FORMAT(expense_date, '%Y-%m') = DATE_FORMAT(CURDATE(), '%Y-%m')`

---

### 4. customers - 顾客信息

**业务含义**：记录顾客基本信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| nickname | varchar | 昵称 |
| avatar_url | varchar | 头像URL |
| phone | varchar | 手机号 |
| gender | tinyint | 性别：0-未知, 1-男, 2-女 |
| birthday | date | 生日 |
| wechat_openid | varchar | 微信OpenID |
| wechat_unionid | varchar | 微信UnionID |
| source | varchar | 来源：store-门店, meituan-美团, douyin-抖音, miniapp-小程序, other-其他 |
| tags | varchar | 标签（逗号分隔）：vip, regular, family, new, big, complaint, star, xin |
| remark | varchar | 备注 |
| is_deleted | tinyint | 删除标记：0-正常, 1-已删除 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |
| deleted_time | datetime | 删除时间 |

**统计逻辑**：
- 新顾客数：`COUNT(*) WHERE DATE(created_at) = CURDATE()`
- 总顾客数：`COUNT(*) WHERE is_deleted = 0`

---

### 5. game_sessions - 游戏场次

**业务含义**：记录顾客的游玩/核销记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| customer_id | bigint | 顾客ID |
| customer_session_id | bigint | 顾客场次ID |
| staff_id | bigint | 员工ID |
| start_time | datetime | 开始时间 |
| end_time | datetime | 结束时间 |
| status | tinyint | 状态：1-进行中, 2-已完成, 3-已取消 |
| remark | varchar | 备注 |
| created_at | datetime | 创建时间 |
| is_deleted | tinyint | 删除标记：0-正常, 1-已删除 |
| deleted_time | datetime | 删除时间 |

**统计逻辑**：
- 今日核销：`COUNT(*) WHERE DATE(created_at) = CURDATE()`
- 本月核销：`COUNT(*) WHERE DATE_FORMAT(created_at, '%Y-%m') = DATE_FORMAT(CURDATE(), '%Y-%m')`

---

### 6. refund_records - 退款记录

**业务含义**：记录退款申请和处理。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| purchase_id | bigint | 购买记录ID |
| refund_amount | decimal | 退款金额 |
| reason | varchar | 退款原因 |
| status | tinyint | 状态：1-处理中, 2-已完成, 3-已拒绝 |
| created_at | datetime | 创建时间 |

**统计逻辑**：
- 待处理退款：`COUNT(*) WHERE status = 1`
- 本月退款金额：`SUM(refund_amount) WHERE status = 2 AND DATE_FORMAT(created_at, '%Y-%m') = DATE_FORMAT(CURDATE(), '%Y-%m')`

---

### 7. packages - 套餐

**业务含义**：定义店铺提供的服务套餐。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| name | varchar | 套餐名称 |
| type | tinyint | 类型：1-单次, 2-周卡, 3-月卡 |
| price | decimal | 价格 |
| duration_minutes | int | 时长（分钟） |
| max_people_per_session | int | 每场最大人数 |
| is_active | tinyint | 是否启用 |

---

### 8. materials - 物料

**业务含义**：记录店铺的物料/商品信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| name | varchar | 物料名称 |
| type | tinyint | 类型：1-消耗品, 2-工具 |
| unit | varchar | 单位 |
| min_stock | int | 最低库存预警 |
| category | varchar | 分类 |

---

### 9. inventory - 库存

**业务含义**：记录物料的当前库存。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| material_id | bigint | 物料ID |
| quantity | decimal | 当前数量 |

**统计逻辑**：
- 库存预警：`SELECT * FROM inventory i JOIN materials m ON i.material_id = m.id WHERE i.quantity <= m.min_stock`

---

### 10. staff - 员工

**业务含义**：记录员工信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| name | varchar | 姓名 |
| phone | varchar | 手机号 |
| employment_type | tinyint | 用工类型：1-全职, 2-兼职 |
| status | tinyint | 状态：1-在职, 0-离职 |
| boss_status | tinyint | 是否商户：0-否, 1-是 |

---

### 11. customer_wallets - 顾客钱包

**业务含义**：记录顾客的储值余额。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| customer_id | bigint | 顾客ID |
| balance | decimal | 当前余额 |
| total_recharged | decimal | 累计充值 |
| total_spent | decimal | 累计消费 |

---

### 12. wallet_transactions - 钱包交易流水

**业务含义**：记录钱包的充值、消费、退款等交易。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| wallet_id | bigint | 钱包ID |
| customer_id | bigint | 顾客ID |
| type | tinyint | 类型：1-充值, 2-消费, 3-退款, 4-调整 |
| amount | decimal | 交易金额 |
| balance_after | decimal | 交易后余额 |

---

### 13. coupons - 优惠券

**业务含义**：定义优惠券规则。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| name | varchar | 优惠券名称 |
| type | tinyint | 类型：1-固定金额, 2-百分比, 3-兑换券 |
| value | decimal | 面值/折扣比例 |
| min_order_amount | decimal | 最低订单金额 |
| total_stock | int | 总库存 |
| remain_stock | int | 剩余库存 |
| valid_days | int | 有效天数 |
| is_active | tinyint | 是否启用 |

---

### 14. feedbacks - 评价反馈

**业务含义**：记录顾客的评价和反馈。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| customer_id | bigint | 顾客ID |
| game_session_id | bigint | 游戏场次ID |
| feedback_type | tinyint | 类型：1-满意度, 2-建议, 3-投诉, 4-其他 |
| rating | tinyint | 评分（1-5） |
| content | text | 评价内容 |
| reply_content | text | 回复内容 |
| status | tinyint | 状态：1-待处理, 2-已回复, 3-已关闭 |

---

### 15. attendance_records - 考勤记录

**业务含义**：记录员工的考勤打卡。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| staff_id | bigint | 员工ID |
| date | date | 考勤日期 |
| check_in_time | datetime | 签到时间 |
| check_out_time | datetime | 签退时间 |
| status | tinyint | 状态：1-正常, 2-迟到, 3-早退, 4-加班 |

---

### 16. staff_schedules - 员工排班

**业务含义**：记录员工的排班计划。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| staff_id | bigint | 员工ID |
| schedule_date | date | 排班日期 |
| start_time | time | 开始时间 |
| end_time | time | 结束时间 |
| type | tinyint | 类型：1-上班, 2-休息 |

---

### 17. notifications - 通知

**业务含义**：记录系统通知。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| shop_id | bigint | 店铺ID |
| recipient_id | bigint | 接收人ID |
| recipient_type | tinyint | 接收类型：1-顾客, 2-员工 |
| channel | tinyint | 渠道：1-微信模板消息, 2-短信, 3-站内信 |
| title | varchar | 标题 |
| content | text | 内容 |
| status | tinyint | 状态：1-未读, 2-已读, 3-发送失败 |

---

### 18. seat_subscriptions - 席位订阅

**业务含义**：记录商户的席位订阅信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| seat_no | varchar | 席位号 |
| staff_id | bigint | 商户ID |
| start_date | date | 生效日期 |
| end_date | date | 到期日期 |
| status | tinyint | 状态：1-生效中, 2-已到期 |

---

### 19. shops - 店铺

**业务含义**：记录店铺信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 主键 |
| owner_staff_id | bigint | 所属商户ID |
| name | varchar | 店铺名称 |
| address | varchar | 地址 |
| contact_phone | varchar | 联系电话 |
| max_capacity | int | 最大客容量 |
| status | tinyint | 状态：1-营业中, 0-休息 |
| open_time | varchar | 营业开始时间 |
| close_time | varchar | 营业结束时间 |
| business_days | varchar | 营业日（1-7对应周一到周日） |
