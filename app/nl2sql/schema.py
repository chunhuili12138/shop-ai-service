"""
Schema链接模块
将数据库表结构映射到LLM可理解的格式
"""

from pathlib import Path


# 店铺管理系统核心表结构
SCHEMA_INFO = """
## 数据库表结构说明

### 顾客相关表
- **customers**: 顾客基本信息
  - id: 主键
  - nickname: 昵称
  - phone: 手机号
  - gender: 性别 (1=男, 2=女)
  - birthday: 生日
  - source: 来源渠道
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
  - shop_id: 所属店铺ID

### 交易相关表
- **purchases**: 购买记录
  - id: 主键
  - customer_id: 顾客ID
  - package_id: 套餐ID
  - channel: 购买渠道
  - total_amount: 总金额
  - paid_amount: 实付金额
  - status: 状态 (1=有效, 2=已退款, 3=已过期)
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **game_sessions**: 游玩/核销记录
  - id: 主键
  - customer_session_id: 顾客场次ID
  - staff_id: 核销员工ID
  - start_time: 开始时间
  - end_time: 结束时间
  - status: 状态 (1=进行中, 2=已完成)
  - shop_id: 所属店铺ID

### 库存相关表
- **materials**: 物料信息
  - id: 主键
  - name: 物料名称
  - sku: SKU编码
  - category: 分类
  - unit: 单位
  - type: 类型 (1=消耗品, 2=工具)
  - min_stock: 最低库存预警
  - shop_id: 所属店铺ID

- **inventory**: 库存记录
  - id: 主键
  - material_id: 物料ID
  - quantity: 当前数量
  - shop_id: 所属店铺ID

### 财务相关表
- **revenue_records**: 收入记录
  - id: 主键
  - amount: 金额
  - source_type: 来源类型
  - source_id: 来源ID
  - shop_id: 所属店铺ID
  - created_at: 创建时间

- **expenses**: 支出记录
  - id: 主键
  - category_id: 分类ID
  - amount: 金额
  - expense_date: 支出日期
  - shop_id: 所属店铺ID

### 员工相关表
- **staff**: 员工信息
  - id: 主键
  - name: 姓名
  - phone: 手机号
  - status: 状态 (1=在职, 2=离职)
  - is_deleted: 是否删除 (0=否, 1=是)

- **staff_shops**: 员工-店铺关联表
  - id: 主键
  - staff_id: 员工ID
  - shop_id: 店铺ID

### 店铺相关表
- **shops**: 店铺信息
  - id: 主键
  - name: 店铺名称
  - address: 地址
  - contact_phone: 联系电话
  - max_capacity: 最大容量
  - status: 状态 (1=营业中, 2=已关闭)
"""


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
