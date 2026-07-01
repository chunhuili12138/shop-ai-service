"""
状态枚举映射 — 唯一权威来源

⚠️ 此文件是 SQL 生成 prompt 中所有状态/类型映射的单一权威来源。
   必须与后端 Java 代码及 sys_dicts 表保持同步。
   更新时机：后端新增/修改枚举时，同步更新此文件。

使用方法：
    from app.common.status_mappings import STATUS_MAPPINGS
    prompt = SQL_GENERATION_PROMPT.format(status_mappings=STATUS_MAPPINGS, ...)
"""

STATUS_MAPPINGS = """
## 状态字段映射（必须遵守）

### 退款状态
- status=1 → 处理中/待审核
- status=2 → 已完成
- status=3 → 已拒绝

  对应 CASE WHEN:
  ```sql
  CASE WHEN rr.status = 1 THEN '处理中' WHEN rr.status = 2 THEN '已完成' WHEN rr.status = 3 THEN '已拒绝' END AS 退款状态
  ```

### 套餐类型
- type=1 → 单次
- type=2 → 周卡
- type=3 → 月卡

  对应 CASE WHEN:
  ```sql
  CASE WHEN p.type = 1 THEN '单次' WHEN p.type = 2 THEN '周卡' WHEN p.type = 3 THEN '月卡' END AS 套餐类型
  ```

### 优惠券类型
- type=1 → 固定金额
- type=2 → 百分比
- type=3 → 兑换券

  对应 CASE WHEN:
  ```sql
  CASE WHEN c.type = 1 THEN '固定金额' WHEN c.type = 2 THEN '百分比' WHEN c.type = 3 THEN '兑换券' END AS 优惠券类型
  ```

### 支付方式
- 'wechat' → 微信
- 'alipay' → 支付宝
- 'cash' → 现金

  对应 CASE WHEN:
  ```sql
  CASE WHEN p.payment_method = 'wechat' THEN '微信' WHEN p.payment_method = 'alipay' THEN '支付宝' WHEN p.payment_method = 'cash' THEN '现金' END AS 支付方式
  ```

### 物料类型
- type=1 → 消耗品
- type=2 → 工具

### 核销状态
- status=1 → 进行中
- status=2 → 已完成

### 考勤状态
- status=1 → 正常
- status=2 → 迟到
- status=3 → 早退
- status=4 → 加班

### 顾客来源
- 'store' → 门店
- 'meituan' → 美团
- 'douyin' → 抖音
- 'miniapp' → 小程序
- 'other' → 其他

### 退款率公式
- `SUM(refund_amount) / SUM(paid_amount)`（近30天）

## 使用规则
1. 所有状态字段必须在 SQL 中用 CASE WHEN 转为中文标签（上面对应的 SQL 片段可直接使用）
2. 如果不确定某个字段的映射，查询 sys_dicts 表：
   `SELECT dict_label, dict_value FROM sys_dicts WHERE dict_code = 'xxx'`
3. **绝对禁止**自行编造状态值与中文标签的对应关系
"""
