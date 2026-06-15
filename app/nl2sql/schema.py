"""
Schema链接模块
将数据库表结构映射到LLM可理解的格式
包含完整的表定义和状态字典映射
"""

from pathlib import Path


# 状态字典速查表（LLM 生成 SQL 时必须使用数字值，不要用中文）
STATUS_DICT = """
## 状态字典速查表（SQL 中必须使用数字值）

| 表 | 字段 | 值 | 含义 |
|---|---|---|---|
| purchases | status | 1 | 有效 |
| purchases | status | 2 | 已退款 |
| purchases | status | 3 | 已过期 |
| refund_records | status | 1 | 处理中（待审核） |
| refund_records | status | 2 | 已完成 |
| refund_records | status | 3 | 已拒绝 |
| game_sessions | status | 1 | 进行中 |
| game_sessions | status | 2 | 已完成 |
| customer_sessions | status | 1 | 可用 |
| customer_sessions | status | 2 | 已核销 |
| customer_sessions | status | 3 | 已过期 |
| customer_sessions | status | 4 | 已退款 |
| packages | type | 1 | 单次 |
| packages | type | 2 | 周卡 |
| packages | type | 3 | 月卡 |
| packages | is_active | 0 | 下架 |
| packages | is_active | 1 | 上架 |
| materials | type | 1 | 消耗品 |
| materials | type | 2 | 工具 |
| inventory_transactions | type | 1 | 入库 |
| inventory_transactions | type | 2 | 出库 |
| customers | gender | 0 | 未知 |
| customers | gender | 1 | 男 |
| customers | gender | 2 | 女 |
| staff | status | 1 | 在职 |
| staff | status | 2 | 离职 |
| shops | status | 1 | 营业中 |
| shops | status | 2 | 已关闭 |
| seat_subscriptions | status | 1 | 生效中 |
| seat_subscriptions | status | 2 | 已到期 |
| seat_subscriptions | status | 3 | 已取消 |
| coupon_usages | status | 1 | 未使用 |
| coupon_usages | status | 2 | 已使用 |
| coupon_usages | status | 3 | 已过期 |
| coupons | type | 1 | 固定金额 |
| coupons | type | 2 | 百分比折扣 |
| coupons | type | 3 | 兑换券 |
| feedbacks | feedback_type | 1 | 满意度 |
| feedbacks | feedback_type | 2 | 建议 |
| feedbacks | feedback_type | 3 | 投诉 |
| feedbacks | feedback_type | 4 | 其他 |
| purchase_orders | type | 1 | 现结 |
| purchase_orders | type | 2 | 赊账 |
| purchase_orders | status | 1 | 待确认 |
| purchase_orders | status | 2 | 已确认 |
| purchase_orders | status | 3 | 已完成 |
| purchase_orders | status | 4 | 已取消 |
| commission_rules | rule_type | 1 | 按次 |
| commission_rules | rule_type | 2 | 按流水比例 |
| commission_rules | rule_type | 3 | 固定金额 |
| commission_settlements | status | 1 | 待结算 |
| commission_settlements | status | 2 | 已发放 |
| attendance_records | status | 1 | 正常 |
| attendance_records | status | 2 | 迟到 |
| attendance_records | status | 3 | 早退 |
| attendance_records | status | 4 | 加班 |

注意：
- "待审核" 对应 refund_records.status = 1（处理中）
- 查询"待审核退款"时使用 WHERE rr.status = 1
- 所有 status 字段都是 tinyint 数字类型，不要用字符串比较
"""


# 店铺管理系统核心表结构
SCHEMA_INFO = """
## 数据库表结构说明

### 顾客相关表
- **customers**: 顾客基本信息
  - id: 主键
  - nickname: 昵称
  - phone: 手机号
  - gender: 性别 (0=未知, 1=男, 2=女)
  - birthday: 生日
  - source: 来源渠道
  - tags: 标签
  - remark: 备注
  - shop_id: 所属店铺ID
  - created_at: 创建时间
  - is_deleted: 是否删除 (0=否, 1=是)

- **customer_wallets**: 顾客储值钱包
  - id: 主键
  - customer_id: 顾客ID (关联customers.id)
  - balance: 当前余额
  - total_recharged: 累计充值
  - total_spent: 累计消费
  - shop_id: 所属店铺ID

- **wallet_transactions**: 钱包交易流水
  - id: 主键
  - wallet_id: 钱包ID (关联customer_wallets.id)
  - type: 类型 (recharge=充值, consume=消费, refund=退款, adjust=调整)
  - amount: 交易金额
  - balance_before: 交易前余额
  - balance_after: 交易后余额
  - reference_type: 关联类型
  - reference_id: 关联ID
  - remark: 备注
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **points_records**: 积分记录
  - id: 主键
  - customer_id: 顾客ID
  - type: 类型 (earn=获取, consume=消耗, expire=过期, adjust=调整)
  - points: 积分值
  - balance_after: 变动后余额
  - reason: 原因
  - shop_id: 所属店铺ID
  - created_at: 创建时间

### 套餐相关表
- **packages**: 套餐定义
  - id: 主键
  - name: 套餐名称
  - type: 类型 (1=单次, 2=周卡, 3=月卡)
  - duration_minutes: 时长(分钟)
  - price: 价格
  - max_people_per_session: 每场上限人数
  - description: 描述
  - is_active: 是否上架 (0=下架, 1=上架)
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **package_bom**: 套餐物料清单
  - id: 主键
  - package_id: 套餐ID (关联packages.id)
  - material_id: 物料ID (关联materials.id)
  - quantity: 用量

### 交易相关表
- **purchases**: 购买/充值记录
  - id: 主键
  - customer_id: 顾客ID (关联customers.id)
  - package_id: 套餐ID (关联packages.id)
  - channel: 购买渠道 (offline=线下, miniapp=小程序, meituan=美团, douyin=抖音)
  - total_amount: 总金额
  - paid_amount: 实付金额
  - payment_method: 支付方式 (wechat=微信, alipay=支付宝, cash=现金, wallet=储值卡)
  - status: 状态 (1=有效, 2=已退款, 3=已过期)
  - third_party_coupon_code: 第三方券码
  - remark: 备注
  - shop_id: 所属店铺ID
  - created_at: 创建时间
  - is_deleted: 是否删除 (0=否, 1=是)

- **customer_sessions**: 按天拆分的次数/天数
  - id: 主键
  - purchase_id: 购买记录ID (关联purchases.id)
  - session_date: 场次日期
  - status: 状态 (1=可用, 2=已核销, 3=已过期, 4=已退款)
  - shop_id: 所属店铺ID

- **game_sessions**: 实际游玩/核销记录
  - id: 主键
  - customer_session_id: 顾客场次ID (关联customer_sessions.id)
  - staff_id: 核销员工ID (关联staff.id)
  - start_time: 开始时间
  - end_time: 结束时间
  - status: 状态 (1=进行中, 2=已完成)
  - shop_id: 所属店铺ID

- **refund_records**: 退款记录
  - id: 主键
  - shop_id: 所属店铺ID
  - purchase_id: 购买记录ID (关联purchases.id)
  - refund_amount: 退款金额
  - reason: 退款原因
  - deducted_amount: 扣除金额
  - refund_prepay_amount: 预收款退款金额
  - refund_wallet_amount: 储值卡退款金额
  - refunded_sessions: 已退场次数
  - status: 状态 (1=处理中/待审核, 2=已完成, 3=已拒绝)
  - operated_by: 操作人ID (关联staff.id)
  - created_at: 申请时间
  - updated_at: 更新时间
  - is_deleted: 是否删除 (0=否, 1=是)

- **prepayments**: 预收款入账记录
  - id: 主键
  - purchase_id: 购买记录ID
  - amount: 金额
  - balance_before: 入账前余额
  - balance_after: 入账后余额
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **revenue_records**: 收入确认记录
  - id: 主键
  - shop_id: 所属店铺ID
  - game_session_id: 游戏场次ID (关联game_sessions.id)
  - purchase_id: 购买记录ID (关联purchases.id)
  - amount: 金额
  - confirmed_at: 确认时间
  - confirmed_by: 确认人ID (关联staff.id)
  - payment_method: 支付方式
  - customer_id: 顾客ID
  - created_at: 创建时间
  - is_deleted: 是否删除 (0=否, 1=是)

### 库存相关表
- **materials**: 物料/货物基础信息
  - id: 主键
  - name: 物料名称
  - sku: SKU编码
  - category: 分类
  - unit: 单位
  - type: 类型 (1=消耗品, 2=工具)
  - min_stock: 最低库存预警
  - remark: 备注
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **inventory**: 当前库存
  - id: 主键
  - material_id: 物料ID (关联materials.id)
  - quantity: 当前数量
  - shop_id: 所属店铺ID

- **inventory_transactions**: 库存出入库流水
  - id: 主键
  - shop_id: 所属店铺ID
  - material_id: 物料ID (关联materials.id)
  - type: 类型 (1=入库, 2=出库)
  - quantity: 数量
  - reference_type: 关联类型 (purchase=采购, manual=手动, bom=套餐消耗)
  - reference_id: 关联ID
  - remark: 备注
  - created_at: 创建时间

### 供应商与采购表
- **suppliers**: 供应商
  - id: 主键
  - name: 供应商名称
  - contact_person: 联系人
  - phone: 电话
  - address: 地址
  - remark: 备注
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **purchase_orders**: 采购单
  - id: 主键
  - supplier_id: 供应商ID (关联suppliers.id)
  - order_date: 下单日期
  - type: 类型 (1=现结, 2=赊账)
  - status: 状态 (1=待确认, 2=已确认, 3=已完成, 4=已取消)
  - remark: 备注
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **purchase_order_items**: 采购明细
  - id: 主键
  - purchase_order_id: 采购单ID (关联purchase_orders.id)
  - material_id: 物料ID (关联materials.id)
  - quantity: 数量
  - unit_price: 单价

- **purchase_payments**: 采购付款记录
  - id: 主键
  - purchase_order_id: 采购单ID (关联purchase_orders.id)
  - amount: 金额
  - payment_method: 支付方式
  - paid_at: 付款时间
  - remark: 备注

### 财务相关表
- **expense_categories**: 费用支出分类
  - id: 主键
  - name: 分类名称
  - shop_id: 所属店铺ID

- **expenses**: 费用支出
  - id: 主键
  - category_id: 分类ID (关联expense_categories.id)
  - amount: 金额
  - payment_method: 支付方式
  - expense_date: 支出日期
  - remark: 备注
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **invoices**: 发票记录
  - id: 主键
  - reference_type: 关联类型
  - reference_id: 关联ID
  - invoice_number: 发票号
  - amount: 金额
  - issued_at: 开票日期
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **commission_rules**: 提成规则
  - id: 主键
  - role_id: 角色ID (关联roles.id)
  - rule_type: 规则类型 (1=按次, 2=按流水比例, 3=固定金额)
  - value: 值
  - description: 描述
  - is_active: 是否启用 (0=禁用, 1=启用)
  - shop_id: 所属店铺ID

- **commission_settlements**: 员工提成结算
  - id: 主键
  - staff_id: 员工ID (关联staff.id)
  - amount: 结算金额
  - settlement_period: 结算周期 (如 2026-06)
  - status: 状态 (1=待结算, 2=已发放)
  - shop_id: 所属店铺ID
  - created_at: 创建时间

### 员工相关表
- **staff**: 员工信息（含租户）
  - id: 主键
  - name: 姓名
  - phone: 手机号
  - status: 状态 (1=在职, 2=离职)
  - employment_type: 雇佣类型
  - boss_status: 是否为租户 (0=否, 1=是)
  - max_seats: 最大席位数
  - used_seats: 已用席位数
  - remark: 备注
  - is_deleted: 是否删除 (0=否, 1=是)
  - created_at: 创建时间

- **staff_accounts**: 员工登录账号
  - id: 主键
  - staff_id: 员工ID (关联staff.id)
  - username: 用户名
  - password_hash: 密码哈希
  - wechat_openid: 微信OpenID

- **staff_shops**: 员工-店铺关联表
  - id: 主键
  - staff_id: 员工ID (关联staff.id)
  - shop_id: 店铺ID (关联shops.id)

- **staff_schedules**: 员工排班
  - id: 主键
  - staff_id: 员工ID (关联staff.id)
  - shop_id: 店铺ID
  - schedule_date: 排班日期
  - start_time: 开始时间
  - end_time: 结束时间
  - type: 类型
  - remark: 备注

- **attendance_records**: 员工打卡记录
  - id: 主键
  - staff_id: 员工ID (关联staff.id)
  - date: 打卡日期
  - check_in_time: 签到时间
  - check_out_time: 签退时间
  - status: 状态 (1=正常, 2=迟到, 3=早退, 4=加班)
  - shop_id: 所属店铺ID

### 店铺与席位表
- **shops**: 店铺信息
  - id: 主键
  - name: 店铺名称
  - address: 地址
  - contact_phone: 联系电话
  - max_capacity: 最大容量
  - description: 描述
  - sign_photo: 招牌照片
  - status: 状态 (1=营业中, 2=已关闭)
  - owner_staff_id: 所属商户ID (关联staff.id)
  - is_deleted: 是否删除 (0=否, 1=是)
  - created_at: 创建时间

- **seat_subscriptions**: 席位订阅订单
  - id: 主键
  - staff_id: 商户ID (关联staff.id)
  - start_date: 开始日期
  - end_date: 结束日期
  - status: 状态 (1=生效中, 2=已到期, 3=已取消)
  - created_at: 创建时间

- **seat_subscriptions_transactions**: 席位订阅流水
  - id: 主键
  - seat_id: 席位ID (关联seat_subscriptions.id)
  - amount: 金额
  - subscription_type: 订阅类型 (1=月付, 2=年付)
  - status: 状态
  - created_at: 创建时间

### 营销相关表
- **coupons**: 优惠券定义
  - id: 主键
  - name: 优惠券名称
  - type: 类型 (1=固定金额, 2=百分比折扣, 3=兑换券)
  - value: 面值/折扣率
  - min_order_amount: 最低订单金额
  - total_stock: 总库存
  - remain_stock: 剩余库存
  - valid_days: 有效天数
  - is_active: 是否启用 (0=禁用, 1=启用)
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **coupon_usages**: 优惠券领取与使用
  - id: 主键
  - coupon_id: 优惠券ID (关联coupons.id)
  - customer_id: 顾客ID (关联customers.id)
  - status: 状态 (1=未使用, 2=已使用, 3=已过期)
  - used_at: 使用时间
  - expires_at: 过期时间
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **coupon_verification_logs**: 第三方券码核销日志
  - id: 主键
  - channel: 渠道
  - coupon_code: 券码
  - operation: 操作类型
  - result: 结果
  - shop_id: 所属店铺ID
  - created_at: 创建时间

### 内容管理表
- **articles**: 文章/内容
  - id: 主键
  - category_id: 分类ID (关联article_categories.id)
  - title: 标题
  - content_type: 内容类型 (1=图文, 2=视频, 3=纯文本)
  - content: 内容
  - cover_image: 封面图
  - is_published: 是否发布 (0=草稿, 1=已发布)
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **article_categories**: 文章分类
  - id: 主键
  - name: 分类名称
  - sort: 排序
  - shop_id: 所属店铺ID

### 运营相关表
- **queue_entries**: 排队等位
  - id: 主键
  - customer_id: 顾客ID (关联customers.id)
  - queue_number: 排队号
  - status: 状态 (waiting=等待中, called=已叫号, seated=已入座, cancelled=已取消)
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **feedbacks**: 顾客反馈
  - id: 主键
  - game_session_id: 游戏场次ID (关联game_sessions.id)
  - customer_id: 顾客ID (关联customers.id)
  - feedback_type: 反馈类型 (1=满意度, 2=建议, 3=投诉, 4=其他)
  - rating: 评分 (1-5)
  - content: 反馈内容
  - reply_content: 回复内容
  - status: 状态 (pending=待处理, replied=已回复)
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **daily_snapshots**: 每日经营快照
  - id: 主键
  - snapshot_date: 快照日期
  - sales_total: 营业额
  - new_customers: 新顾客数
  - check_ins: 核销数
  - average_duration: 平均游玩时长(分钟)
  - inventory_warns: 库存预警数
  - shop_id: 所属店铺ID

### 系统表
- **sys_dicts**: 数据字典
  - id: 主键
  - dict_code: 字典编码
  - dict_key: 字典键
  - dict_label: 字典标签（业务键值，英文）
  - dict_value: 字典值（显示名称，中文）
  - sort: 排序
  - shop_id: 店铺ID (0=全局)
  - is_active: 是否启用

- **operation_logs**: 操作日志
  - id: 主键
  - operator_type: 操作人类型
  - operator_id: 操作人ID
  - action: 操作类型
  - target_type: 目标类型
  - target_id: 目标ID
  - detail: 详情(JSON)
  - ip_address: IP地址
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **notification_logs**: 消息通知日志
  - id: 主键
  - recipient_type: 接收者类型
  - recipient_id: 接收者ID
  - channel: 渠道 (1=站内信, 2=短信, 3=微信)
  - title: 标题
  - content: 内容
  - status: 状态 (1=未读, 2=已读)
  - shop_id: 所属店铺ID
  - created_at: 创建时间
""" + STATUS_DICT


def get_schema_info() -> str:
    """获取数据库Schema信息"""
    return SCHEMA_INFO


def get_table_ddl(table_name: str = None) -> str:
    """
    获取表DDL语句
    可以从 schema/ 目录下的SQL文件读取
    """
    schema_file = Path("schema/database_ddl.sql")
    if schema_file.exists():
        return schema_file.read_text(encoding="utf-8")
    return SCHEMA_INFO
