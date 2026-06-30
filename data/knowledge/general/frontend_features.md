# 前端页面功能说明

## 页面结构

```
shop-operate-system-ui/src/views/
├── welcome/              # 首页/仪表盘
├── customer/             # 顾客管理
├── trade/                # 交易管理
│   ├── purchase/         # 购买记录
│   ├── checkin/          # 核销管理
│   └── refund/           # 退款管理
├── package/              # 套餐管理
├── inventory/            # 库存管理
│   ├── material/         # 物料管理
│   ├── supplier/         # 供应商管理
│   └── purchase/         # 采购管理
├── marketing/            # 营销管理
│   ├── coupon/           # 优惠券管理
│   └── article/          # 文章管理
├── feedback/             # 评价管理
├── finance/              # 财务管理
│   ├── revenue/          # 收入管理
│   ├── expense/          # 支出管理
│   ├── cashflow/         # 收支流水
│   ├── invoice/          # 发票管理
│   ├── commission/       # 提成管理
│   ├── attendance/       # 考勤管理
│   ├── schedule/         # 排班管理
│   └── notification/     # 通知管理
├── dashboard/            # 数据报表
│   └── snapshot/         # 经营快照
├── shop/                 # 店铺管理
│   ├── list/             # 店铺列表
│   └── my/               # 我的店铺
├── system/               # 系统管理
│   ├── staff/            # 员工管理
│   ├── role/             # 角色管理
│   ├── permission/       # 权限管理
│   └── dict/             # 字典管理
├── tenant/               # 租户管理
│   └── list/             # 商户列表
└── my/                   # 个人中心
    └── profile/          # 个人资料
```

---

## 核心页面功能

### 1. 首页/仪表盘（welcome）

**功能**：
- 今日收现（今日营收）
- 确认收入（今日实际收入）
- 今日支出
- 今日订单数
- 今日核销数
- 新顾客数
- 本月统计（本月营收、本月收入、本月支出、本月核销）
- 待处理事项（待处理退款、待处理评价）
- 库存预警
- 近7日收支趋势
- 热销套餐TOP5
- 渠道分布

**接口**：`GET /api/dashboard/shop`

---

### 2. 顾客管理（customer）

**功能**：
- 顾客列表（分页、搜索、筛选）
- 新增顾客
- 编辑顾客
- 删除顾客
- 顾客详情
- 顾客消费记录
- 顾客钱包（余额、交易流水）
- 顾客积分记录
- 钱包调整
- 积分调整

**接口**：
- `GET /api/customers/page` - 顾客列表
- `POST /api/customers/add` - 新增顾客
- `PUT /api/customers/update` - 编辑顾客
- `DELETE /api/customers/delete` - 删除顾客
- `GET /api/customers/info` - 顾客详情
- `GET /api/customers/purchases` - 消费记录
- `GET /api/customers/wallet` - 钱包信息
- `POST /api/customers/walletAdjust` - 钱包调整
- `GET /api/customers/points` - 积分记录
- `PUT /api/customers/pointsAdjust` - 积分调整

---

### 3. 交易管理

#### 3.1 购买记录（trade/purchase）

**功能**：
- 购买记录列表（分页、搜索、筛选）
- 新增购买（选择顾客、套餐、支付方式）
- 购买详情

**接口**：
- `GET /api/purchases` - 购买记录列表
- `POST /api/purchasesAdd` - 新增购买

---

#### 3.2 核销管理（trade/checkin）

**功能**：
- 核销入座（选择顾客、可用次数）
- 进行中场次列表
- 结束游玩
- 核销历史记录

**接口**：
- `GET /api/gameSessions?action=available` - 可用场次
- `POST /api/gameSessionsCheckin` - 核销入座
- `PUT /api/gameSessionsFinish` - 结束游玩
- `GET /api/gameSessions?action=list` - 场次列表

---

#### 3.3 退款管理（trade/refund）

**功能**：
- 退款记录列表（分页、搜索、筛选）
- 申请退款（选择购买记录、填写退款金额）
- 确认退款
- 拒绝退款
- 退款详情

**接口**：
- `GET /api/purchasesRefunds` - 退款记录列表
- `POST /api/purchasesRefundsApply` - 申请退款
- `PUT /api/purchasesRefundsApprove` - 确认退款
- `PUT /api/purchasesRefundsReject` - 拒绝退款

---

### 4. 套餐管理（package）

**功能**：
- 套餐列表（分页、搜索、筛选）
- 新增套餐（名称、类型、价格、时长、描述）
- 编辑套餐
- 删除套餐
- 启用/禁用套餐
- 套餐BOM清单管理

**接口**：
- `GET /api/packages/page` - 套餐列表
- `POST /api/packages/add` - 新增套餐
- `PUT /api/packages/update` - 编辑套餐
- `DELETE /api/packages/delete` - 删除套餐
- `PUT /api/packages/status` - 启用/禁用

---

### 5. 库存管理

#### 5.1 物料管理（inventory/material）

**功能**：
- 物料列表（分页、搜索、筛选）
- 新增物料（名称、SKU、分类、单位、类型）
- 编辑物料
- 删除物料

**接口**：
- `GET /api/materials` - 物料列表
- `POST /api/materialsAdd` - 新增物料
- `PUT /api/materialsUpdate` - 编辑物料
- `DELETE /api/materialsDelete` - 删除物料

---

#### 5.2 供应商管理（inventory/supplier）

**功能**：
- 供应商列表（分页、搜索）
- 新增供应商（名称、联系人、电话、地址）
- 编辑供应商
- 删除供应商

**接口**：
- `GET /api/suppliers` - 供应商列表
- `POST /api/suppliersAdd` - 新增供应商
- `PUT /api/suppliersUpdate` - 编辑供应商
- `DELETE /api/suppliersDelete` - 删除供应商

---

#### 5.3 采购管理（inventory/purchase）

**功能**：
- 采购订单列表（分页、搜索、筛选）
- 新增采购订单（选择供应商、物料、数量、单价）
- 采购订单详情
- 更新采购订单状态
- 采购付款

**接口**：
- `GET /api/purchaseOrders` - 采购订单列表
- `POST /api/purchaseOrdersAdd` - 新增采购订单
- `GET /api/purchaseOrdersItems` - 采购订单明细
- `PUT /api/purchaseOrdersStatus` - 更新状态
- `POST /api/purchaseOrdersPay` - 采购付款

---

### 6. 营销管理

#### 6.1 优惠券管理（marketing/coupon）

**功能**：
- 优惠券列表（分页、搜索）
- 新增优惠券（名称、类型、面值、库存、有效期）
- 编辑优惠券
- 删除优惠券
- 启用/禁用优惠券
- 发放优惠券（选择顾客）
- 优惠券使用记录

**接口**：
- `GET /api/coupons` - 优惠券列表
- `POST /api/couponsAdd` - 新增优惠券
- `PUT /api/couponsUpdate` - 编辑优惠券
- `DELETE /api/couponsDelete` - 删除优惠券
- `PUT /api/couponsStatus` - 启用/禁用
- `POST /api/couponUsagesGrant` - 发放优惠券
- `GET /api/couponUsages` - 使用记录

---

#### 6.2 文章管理（marketing/article）

**功能**：
- 文章列表（分页、搜索）
- 新增文章（标题、内容、封面图、分类）
- 编辑文章
- 删除文章
- 发布/下架文章
- 文章分类管理

**接口**：
- `GET /api/articles` - 文章列表
- `POST /api/articlesAdd` - 新增文章
- `PUT /api/articlesUpdate` - 编辑文章
- `DELETE /api/articlesDelete` - 删除文章
- `PUT /api/articlesPublish` - 发布/下架
- `GET /api/articleCategories` - 分类列表
- `POST /api/articleCategoriesAdd` - 新增分类

---

### 7. 评价管理（feedback）

**功能**：
- 评价列表（分页、搜索）
- 评价详情
- 回复评价

**接口**：
- `GET /api/feedbacks/page` - 评价列表
- `GET /api/feedbacks/info` - 评价详情
- `PUT /api/feedbacks/reply` - 回复评价

---

### 8. 财务管理

#### 8.1 收入管理（finance/revenue）

**功能**：
- 收入记录列表（分页、搜索、筛选）
- 收入统计

**接口**：
- `GET /api/revenues` - 收入记录列表

---

#### 8.2 支出管理（finance/expense）

**功能**：
- 支出记录列表（分页、搜索、筛选）
- 新增支出（分类、金额、支付方式、日期）
- 编辑支出
- 删除支出
- 支出分类管理

**接口**：
- `GET /api/expenses` - 支出记录列表
- `POST /api/expensesAdd` - 新增支出
- `PUT /api/expensesUpdate` - 编辑支出
- `DELETE /api/expensesDelete` - 删除支出
- `GET /api/expenseCategories` - 分类列表
- `POST /api/expenseCategoriesAdd` - 新增分类

---

#### 8.3 提成管理（finance/commission）

**功能**：
- 提成规则列表
- 新增提成规则（角色、类型、值）
- 编辑提成规则
- 提成结算记录
- 生成提成结算
- 支付提成结算

**接口**：
- `GET /api/commissionRules` - 规则列表
- `POST /api/commissionRulesAdd` - 新增规则
- `PUT /api/commissionRulesUpdate` - 编辑规则
- `GET /api/commissionSettlements` - 结算记录
- `POST /api/commissionSettlementsGenerate` - 生成结算
- `PUT /api/commissionSettlementsPay` - 支付结算

---

#### 8.4 考勤管理（finance/attendance）

**功能**：
- 考勤记录列表（分页、搜索）
- 打卡签到
- 打卡签退

**接口**：
- `GET /api/attendanceRecords` - 考勤记录
- `POST /api/attendanceRecordsCheckIn` - 签到
- `PUT /api/attendanceRecordsCheckOut` - 签退

---

#### 8.5 排班管理（finance/schedule）

**功能**：
- 排班列表（分页、搜索）
- 新增排班（员工、日期、时间、类型）
- 编辑排班
- 删除排班

**接口**：
- `GET /api/staffSchedules` - 排班列表
- `POST /api/staffSchedulesAdd` - 新增排班
- `PUT /api/staffSchedulesUpdate` - 编辑排班
- `DELETE /api/staffSchedulesDelete` - 删除排班

---

#### 8.6 通知管理（finance/notification）

**功能**：
- 通知列表（分页、搜索）
- 标记已读
- 发送通知

**接口**：
- `GET /api/notifications` - 通知列表
- `PUT /api/notificationsRead` - 标记已读
- `POST /api/notificationsSend` - 发送通知

---

### 9. 数据报表

#### 9.1 经营快照（dashboard/snapshot）

**功能**：
- 每日经营快照列表
- 快照详情（营业额、订单数、新顾客数、核销数等）

**接口**：
- `GET /api/dailySnapshots` - 快照列表
- `GET /api/dailySnapshotsInfo` - 快照详情

---

### 10. 店铺管理

#### 10.1 店铺列表（shop/list）

**功能**：
- 店铺列表（分页、搜索、筛选）
- 新增店铺
- 编辑店铺
- 删除店铺
- 切换营业状态

**接口**：
- `GET /api/shops/page` - 店铺列表
- `POST /api/shops/add` - 新增店铺
- `PUT /api/shops/update` - 编辑店铺
- `DELETE /api/shops/delete` - 删除店铺
- `PUT /api/shops/status` - 切换状态

---

#### 10.2 我的店铺（shop/my）

**功能**：
- 店铺信息展示
- 编辑店铺信息

**接口**：
- `GET /api/shops/info` - 店铺详情
- `PUT /api/shops/update` - 编辑店铺

---

### 11. 系统管理

#### 11.1 员工管理（system/staff）

**功能**：
- 员工列表（分页、搜索、筛选）
- 新增员工（姓名、用户名、密码、手机号、角色）
- 编辑员工
- 删除员工
- 重置密码

**接口**：
- `GET /api/staff/page` - 员工列表
- `POST /api/staff/add` - 新增员工
- `PUT /api/staff/update` - 编辑员工
- `DELETE /api/staff/delete` - 删除员工
- `PUT /api/staff/password` - 重置密码

---

#### 11.2 角色管理（system/role）

**功能**：
- 角色列表
- 设置角色权限

**接口**：
- `GET /api/roles/list` - 角色列表
- `PUT /api/roles/permissions` - 设置权限

---

#### 11.3 字典管理（system/dict）

**功能**：
- 字典列表（分页、搜索）
- 新增字典项
- 编辑字典项
- 删除字典项

**接口**：
- `GET /system/dict/page` - 字典列表
- `POST /system/dict` - 新增字典项
- `PUT /system/dict` - 编辑字典项
- `DELETE /system/dict/{id}` - 删除字典项

---

### 12. 租户管理（tenant/list）

**功能**：
- 商户列表（分页、搜索、筛选）
- 新增商户
- 编辑商户
- 删除商户
- 封禁/解封商户
- 席位管理（新增、续订、删除、流水）

**接口**：
- `GET /api/admin/tenants/page` - 商户列表
- `POST /api/admin/tenants/add` - 新增商户
- `PUT /api/admin/tenants/update` - 编辑商户
- `DELETE /api/admin/tenants/delete` - 删除商户
- `PUT /api/admin/tenants/ban` - 封禁/解封
- `POST /api/admin/tenants/seatAdd` - 新增席位
- `POST /api/admin/tenants/seatRenew` - 续订席位
- `DELETE /api/admin/tenants/seatDelete` - 删除席位

---

### 13. 个人中心（my/profile）

**功能**：
- 个人信息展示
- 修改密码
- 修改个人信息

**接口**：
- `GET /api/auth/info` - 获取用户信息
- `PUT /api/auth/password` - 修改密码
