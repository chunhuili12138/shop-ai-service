"""
Schema Linking 模块
智能识别用户问题相关的数据库表和列
基于实际数据库表结构完整定义
"""

import re
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass


@dataclass
class SchemaLink:
    """Schema链接结果"""
    relevant_tables: List[str]
    relevant_columns: Dict[str, List[str]]  # table -> columns
    join_paths: List[Tuple[str, str, str]]  # (table1, table2, join_condition)
    confidence: float
    suggested_calculations: List[str]


class SchemaLinker:
    """Schema链接器 - 智能识别相关表和列"""
    
    # 同义词映射（增强 Schema Linking 准确性）
    SYNONYM_MAP = {
        # 营收相关
        "营收": ["revenue", "收入", "sales", "营业额", "销售额"],
        "收入": ["revenue", "income", "营收", "营业额"],
        "营业额": ["revenue", "sales", "营收", "收入"],
        "销售额": ["revenue", "sales", "营业额"],
        
        # 支出相关
        "支出": ["expense", "成本", "cost", "花费", "开销"],
        "成本": ["expense", "cost", "支出"],
        "花费": ["expense", "支出", "开销"],
        
        # 顾客相关
        "顾客": ["customer", "客户", "会员", "消费者"],
        "客户": ["customer", "顾客", "会员"],
        "会员": ["customer", "顾客", "客户"],
        
        # 订单相关
        "订单": ["purchase", "购买", "消费", "交易"],
        "购买": ["purchase", "订单", "消费"],
        "消费": ["purchase", "订单", "购买"],
        
        # 套餐相关
        "套餐": ["package", "服务", "产品", "项目"],
        "服务": ["package", "套餐", "产品"],
        
        # 员工相关
        "员工": ["staff", "服务员", "导玩", "工作人员"],
        "服务员": ["staff", "员工", "导玩"],
        
        # 库存相关
        "库存": ["inventory", "物料", "货物", "存货"],
        "物料": ["material", "库存", "货物"],
        
        # 财务相关
        "利润": ["profit", "净利润", "净收入"],
        "净利润": ["profit", "利润"],
        "毛利": ["gross_profit", "毛利润"],
        
        # 充值相关（新增）
        "充值": ["total_recharged", "recharge", "预存", "充钱"],
        "余额": ["balance", "剩余", "剩余额度"],
        "钱包": ["wallet", "储值", "充值余额"],
    }
    
    def __init__(self):
        # 完整的表结构定义（基于实际数据库）
        self.table_info = {
            # ==================== 顾客相关 ====================
            "customers": {
                "description": "顾客基本信息表",
                "keywords": ["顾客", "客户", "会员", "用户", "消费者", "客人", "人数", "多少人"],
                "columns": {
                    "id": "顾客ID、顾客编号",
                    "shop_id": "店铺ID",
                    "nickname": "昵称、姓名、名字、称呼",
                    "avatar_url": "头像",
                    "phone": "手机、电话、联系方式",
                    "gender": "性别、男女",
                    "birthday": "生日、出生日期",
                    "wechat_openid": "微信openid",
                    "wechat_unionid": "微信unionid",
                    "source": "来源、渠道、注册来源",
                    "tags": "标签、标记、分类",
                    "remark": "备注",
                    "created_at": "创建时间、注册时间、加入时间",
                    "updated_at": "更新时间"
                }
            },
            "customer_wallets": {
                "description": "顾客储值钱包",
                "keywords": ["钱包", "储值", "余额", "充值"],
                "columns": {
                    "id": "钱包ID",
                    "shop_id": "店铺ID",
                    "customer_id": "顾客ID",
                    "balance": "余额、当前余额",
                    "total_recharged": "总充值金额",
                    "total_spent": "总消费金额",
                    "updated_at": "更新时间"
                }
            },
            "wallet_transactions": {
                "description": "钱包交易流水",
                "keywords": ["钱包交易", "充值记录", "消费记录", "退款记录"],
                "columns": {
                    "id": "交易ID",
                    "wallet_id": "钱包ID",
                    "shop_id": "店铺ID",
                    "customer_id": "顾客ID",
                    "type": "类型（1充值/2消费/3退款/4调整）",
                    "amount": "金额",
                    "balance_after": "交易后余额",
                    "reference_type": "关联类型",
                    "reference_id": "关联ID",
                    "remark": "备注",
                    "created_at": "创建时间、交易时间"
                }
            },
            "points_records": {
                "description": "积分记录",
                "keywords": ["积分", "积分记录", "积分变动"],
                "columns": {
                    "id": "记录ID",
                    "shop_id": "店铺ID",
                    "customer_id": "顾客ID",
                    "type": "类型（1获取/2消耗/3过期/4调整）",
                    "points": "积分值",
                    "balance_after": "变动后积分余额",
                    "source": "来源",
                    "reference_id": "关联ID",
                    "remark": "备注",
                    "created_at": "创建时间"
                }
            },
            
            # ==================== 购买/订单相关 ====================
            "purchases": {
                "description": "购买/消费记录",
                "keywords": ["购买", "消费", "订单", "销售", "收入", "营业额", "收款", "交易", "付款", "营收"],
                "columns": {
                    "id": "订单ID、消费ID",
                    "shop_id": "店铺ID",
                    "customer_id": "顾客ID",
                    "package_id": "套餐ID",
                    "purchase_type": "购买类型",
                    "channel": "渠道、购买渠道、支付渠道",
                    "third_party_coupon_code": "第三方优惠券码",
                    "coupon_usage_id": "优惠券使用ID",
                    "start_date": "开始日期",
                    "total_amount": "总金额、总价、消费金额、营业额",
                    "paid_amount": "实付金额、实际支付",
                    "coupon_discount": "优惠券折扣",
                    "payment_method": "支付方式",
                    "status": "状态（1有效/2已退款/3已过期）",
                    "operator_staff_id": "操作员工ID",
                    "remark": "备注",
                    "created_at": "创建时间、购买时间、消费时间、订单时间",
                    "updated_at": "更新时间"
                }
            },
            "prepayments": {
                "description": "预收款入账记录",
                "keywords": ["预收款", "入账", "预收"],
                "columns": {
                    "id": "记录ID",
                    "shop_id": "店铺ID",
                    "purchase_id": "购买记录ID",
                    "amount": "金额",
                    "balance_before": "入账前余额",
                    "balance_after": "入账后余额",
                    "created_at": "创建时间"
                }
            },
            
            # ==================== 套餐相关 ====================
            "packages": {
                "description": "套餐/服务定义",
                "keywords": ["套餐", "服务", "产品", "项目", "卡", "周卡", "月卡", "次卡", "课程"],
                "columns": {
                    "id": "套餐ID",
                    "shop_id": "店铺ID",
                    "name": "套餐名称、服务名称、项目名称",
                    "type": "类型（1单次/2周卡/3月卡）",
                    "duration_minutes": "时长、时间、分钟",
                    "price": "价格、售价、金额、定价",
                    "original_price": "原价",
                    "max_people_per_session": "人数上限、每场人数",
                    "description": "描述",
                    "image": "图片",
                    "is_active": "是否启用、状态",
                    "created_at": "创建时间",
                    "updated_at": "更新时间"
                }
            },
            "package_bom": {
                "description": "套餐物料清单",
                "keywords": ["套餐物料", "BOM", "物料清单"],
                "columns": {
                    "id": "记录ID",
                    "package_id": "套餐ID",
                    "material_id": "物料ID",
                    "quantity": "数量",
                    "created_at": "创建时间"
                }
            },
            
            # ==================== 游戏/核销相关 ====================
            "customer_sessions": {
                "description": "顾客套餐使用记录（按天拆分的次数/天数）",
                "keywords": ["次数", "剩余", "可用", "套餐使用", "场次"],
                "columns": {
                    "id": "记录ID",
                    "shop_id": "店铺ID",
                    "customer_id": "顾客ID",
                    "purchase_id": "购买记录ID",
                    "session_date": "使用日期",
                    "status": "状态（1可用/2已核销/3已过期/4已退款）",
                    "used_at": "使用时间",
                    "game_session_id": "游戏场次ID",
                    "created_at": "创建时间"
                }
            },
            "game_sessions": {
                "description": "游玩/核销记录（实际游玩记录）",
                "keywords": ["核销", "游玩", "场次", "体验", "使用", "消费次数", "入座"],
                "columns": {
                    "id": "场次ID",
                    "shop_id": "店铺ID",
                    "customer_id": "顾客ID",
                    "customer_session_id": "顾客场次ID",
                    "staff_id": "员工ID、服务员ID、导玩员ID",
                    "start_time": "开始时间",
                    "end_time": "结束时间",
                    "status": "状态（1进行中/2已完成）",
                    "remark": "备注",
                    "created_at": "创建时间"
                }
            },
            
            # ==================== 收入/支出相关 ====================
            "revenue_records": {
                "description": "收入确认记录",
                "keywords": ["收入", "营收", "确认收入", "收入记录"],
                "columns": {
                    "id": "记录ID",
                    "shop_id": "店铺ID",
                    "game_session_id": "场次ID",
                    "purchase_id": "购买ID",
                    "amount": "金额、收入金额",
                    "confirmed_at": "确认时间",
                    "confirmed_by": "确认人、员工ID",
                    "created_at": "创建时间、记录时间",
                    "payment_method": "支付方式",
                    "customer_id": "顾客ID"
                }
            },
            "refund_records": {
                "description": "退款记录",
                "keywords": ["退款", "退费", "退货"],
                "columns": {
                    "id": "退款ID",
                    "shop_id": "店铺ID",
                    "purchase_id": "购买ID",
                    "refund_amount": "退款金额",
                    "reason": "退款原因",
                    "deducted_amount": "扣除金额",
                    "refund_prepay_amount": "预收款退款金额",
                    "refund_wallet_amount": "钱包退款金额",
                    "refunded_sessions": "退款场次数",
                    "status": "状态",
                    "operated_by": "操作人",
                    "created_at": "创建时间",
                    "updated_at": "更新时间",
                    "revenue_id": "关联收入记录ID"
                }
            },
            "expenses": {
                "description": "费用支出表",
                "keywords": ["支出", "花费", "费用", "开销", "成本"],
                "columns": {
                    "id": "支出ID",
                    "shop_id": "店铺ID",
                    "category_id": "分类ID",
                    "amount": "金额、支出金额",
                    "payment_method": "支付方式",
                    "remark": "备注",
                    "expense_date": "支出日期",
                    "created_at": "创建时间",
                    "source_type": "来源类型",
                    "source_id": "来源记录ID",
                    "operator_staff_id": "操作员工ID"
                }
            },
            "expense_categories": {
                "description": "支出分类",
                "keywords": ["支出分类", "费用类型", "开销类别"],
                "columns": {
                    "id": "分类ID",
                    "shop_id": "店铺ID",
                    "name": "分类名称",
                    "created_at": "创建时间"
                }
            },
            "invoices": {
                "description": "发票记录",
                "keywords": ["发票", "开票"],
                "columns": {
                    "id": "发票ID",
                    "shop_id": "店铺ID",
                    "reference_type": "关联类型",
                    "reference_id": "关联ID",
                    "invoice_number": "发票号",
                    "amount": "金额",
                    "issued_at": "开票日期",
                    "created_at": "创建时间",
                    "image_path": "发票图片路径",
                    "remark": "备注"
                }
            },
            
            # ==================== 库存/物料相关 ====================
            "materials": {
                "description": "物料/商品基础信息",
                "keywords": ["物料", "商品", "货品", "原料", "货物"],
                "columns": {
                    "id": "物料ID",
                    "shop_id": "店铺ID",
                    "name": "物料名称、商品名称",
                    "sku": "SKU、编码",
                    "category": "分类",
                    "unit": "单位",
                    "type": "类型（1消耗品/2工具）",
                    "min_stock": "最低库存、预警值",
                    "image_url": "图片",
                    "remark": "备注",
                    "created_at": "创建时间",
                    "updated_at": "更新时间"
                }
            },
            "inventory": {
                "description": "当前库存",
                "keywords": ["库存", "存货", "库存量"],
                "columns": {
                    "id": "库存ID",
                    "shop_id": "店铺ID",
                    "material_id": "物料ID",
                    "quantity": "数量、库存数量",
                    "updated_at": "更新时间"
                }
            },
            "inventory_transactions": {
                "description": "库存出入库流水",
                "keywords": ["出入库", "入库", "出库", "库存变动"],
                "columns": {
                    "id": "流水ID",
                    "shop_id": "店铺ID",
                    "material_id": "物料ID",
                    "transaction_type": "类型（1入库/2出库）",
                    "quantity": "数量",
                    "balance_after": "变动后库存",
                    "reference_type": "关联类型",
                    "reference_id": "关联ID",
                    "operator_staff_id": "操作员工ID",
                    "remark": "备注",
                    "created_at": "创建时间"
                }
            },
            
            # ==================== 供应商/采购相关 ====================
            "suppliers": {
                "description": "供应商",
                "keywords": ["供应商", "供货商"],
                "columns": {
                    "id": "供应商ID",
                    "shop_id": "店铺ID",
                    "name": "供应商名称",
                    "contact_person": "联系人",
                    "phone": "电话",
                    "address": "地址",
                    "remark": "备注",
                    "created_at": "创建时间"
                }
            },
            "purchase_orders": {
                "description": "采购单",
                "keywords": ["采购", "采购单", "进货"],
                "columns": {
                    "id": "采购单ID",
                    "shop_id": "店铺ID",
                    "supplier_id": "供应商ID",
                    "order_number": "单号",
                    "order_date": "下单日期",
                    "type": "类型（1现结/2赊账）",
                    "total_amount": "总金额",
                    "paid_amount": "已付金额",
                    "status": "状态",
                    "operator_staff_id": "操作员工ID",
                    "remark": "备注",
                    "created_at": "创建时间",
                    "updated_at": "更新时间"
                }
            },
            "purchase_order_items": {
                "description": "采购明细",
                "keywords": ["采购明细", "采购项"],
                "columns": {
                    "id": "明细ID",
                    "purchase_order_id": "采购单ID",
                    "material_id": "物料ID",
                    "quantity": "数量",
                    "unit_price": "单价",
                    "created_at": "创建时间"
                }
            },
            "purchase_payments": {
                "description": "采购付款记录",
                "keywords": ["采购付款", "付款记录"],
                "columns": {
                    "id": "付款ID",
                    "purchase_order_id": "采购单ID",
                    "amount": "金额",
                    "payment_method": "支付方式",
                    "paid_at": "付款时间",
                    "remark": "备注",
                    "created_at": "创建时间",
                    "expense_id": "关联支出记录ID"
                }
            },
            
            # ==================== 员工相关 ====================
            "staff": {
                "description": "员工信息",
                "keywords": ["员工", "服务员", "导玩", "工作人员", "店员", "人员", "商户"],
                "columns": {
                    "id": "员工ID",
                    "boss_status": "是否为商户（0否/1是）",
                    "name": "员工姓名",
                    "phone": "手机号",
                    "contact_email": "邮箱",
                    "avatar": "头像",
                    "employment_type": "雇佣类型",
                    "max_seats": "最大席位数",
                    "used_seats": "已用席位数",
                    "remark": "备注",
                    "status": "状态（1在职/0离职）",
                    "is_ban": "是否封禁",
                    "created_at": "创建时间"
                }
            },
            "staff_accounts": {
                "description": "员工登录账号",
                "keywords": ["账号", "登录"],
                "columns": {
                    "id": "账号ID",
                    "staff_id": "员工ID",
                    "username": "用户名",
                    "password_hash": "密码",
                    "wechat_openid": "微信openid",
                    "last_login_at": "最后登录时间",
                    "created_at": "创建时间"
                }
            },
            "staff_shops": {
                "description": "员工店铺关联",
                "keywords": ["员工店铺"],
                "columns": {
                    "id": "关联ID",
                    "staff_id": "员工ID",
                    "shop_id": "店铺ID",
                    "created_at": "创建时间"
                }
            },
            "staff_schedules": {
                "description": "员工排班",
                "keywords": ["排班", "班次", "排班表"],
                "columns": {
                    "id": "排班ID",
                    "shop_id": "店铺ID",
                    "staff_id": "员工ID",
                    "schedule_date": "排班日期",
                    "start_time": "开始时间",
                    "end_time": "结束时间",
                    "type": "类型（1上班/2休息）",
                    "remark": "备注",
                    "created_at": "创建时间"
                }
            },
            "attendance_records": {
                "description": "员工打卡记录",
                "keywords": ["打卡", "考勤", "签到", "签退"],
                "columns": {
                    "id": "记录ID",
                    "shop_id": "店铺ID",
                    "staff_id": "员工ID",
                    "check_in_time": "签到时间",
                    "check_out_time": "签退时间",
                    "date": "日期",
                    "status": "状态",
                    "created_at": "创建时间"
                }
            },
            
            # ==================== 提成相关 ====================
            "commission_rules": {
                "description": "提成规则",
                "keywords": ["提成规则", "提成"],
                "columns": {
                    "id": "规则ID",
                    "shop_id": "店铺ID",
                    "role_id": "角色ID",
                    "rule_type": "规则类型（1按次/2按流水比例/3固定金额）",
                    "value": "值",
                    "description": "描述",
                    "is_active": "是否启用",
                    "created_at": "创建时间"
                }
            },
            "commission_settlements": {
                "description": "员工提成结算",
                "keywords": ["提成结算", "结算"],
                "columns": {
                    "id": "结算ID",
                    "shop_id": "店铺ID",
                    "staff_id": "员工ID",
                    "settlement_period": "结算周期",
                    "total_sessions": "总场次",
                    "total_revenue": "总营收",
                    "commission_amount": "提成金额",
                    "status": "状态（1待结算/2已发放）",
                    "remark": "备注",
                    "rule_snapshot": "规则快照",
                    "created_at": "创建时间",
                    "expense_id": "关联支出记录ID"
                }
            },
            
            # ==================== 营销相关 ====================
            "coupons": {
                "description": "优惠券定义",
                "keywords": ["优惠券", "券"],
                "columns": {
                    "id": "优惠券ID",
                    "shop_id": "店铺ID",
                    "name": "名称",
                    "description": "描述",
                    "type": "类型（1固定金额/2百分比/3兑换券）",
                    "use_scene": "使用场景",
                    "value": "面值",
                    "min_order_amount": "最低订单金额",
                    "total_stock": "总库存",
                    "per_user_limit": "每人限领",
                    "remain_stock": "剩余库存",
                    "valid_days": "有效天数",
                    "is_active": "是否启用",
                    "auto_grant_on_register": "注册自动发放",
                    "created_at": "创建时间",
                    "updated_at": "更新时间"
                }
            },
            "coupon_usages": {
                "description": "优惠券领取与使用",
                "keywords": ["优惠券使用", "领券"],
                "columns": {
                    "id": "记录ID",
                    "shop_id": "店铺ID",
                    "coupon_id": "优惠券ID",
                    "customer_id": "顾客ID",
                    "status": "状态",
                    "received_at": "领取时间",
                    "used_at": "使用时间",
                    "used_in_purchase_id": "使用的购买ID",
                    "expires_at": "过期时间",
                    "created_at": "创建时间"
                }
            },
            
            # ==================== 内容相关 ====================
            "articles": {
                "description": "文章/内容",
                "keywords": ["文章", "内容", "资讯"],
                "columns": {
                    "id": "文章ID",
                    "shop_id": "店铺ID",
                    "category_id": "分类ID",
                    "title": "标题",
                    "content_type": "内容类型",
                    "content": "内容",
                    "cover_image": "封面图",
                    "is_published": "是否发布",
                    "published_at": "发布时间",
                    "created_at": "创建时间",
                    "updated_at": "更新时间"
                }
            },
            "article_categories": {
                "description": "文章分类",
                "keywords": ["文章分类"],
                "columns": {
                    "id": "分类ID",
                    "shop_id": "店铺ID",
                    "name": "分类名称",
                    "sort": "排序",
                    "created_at": "创建时间"
                }
            },
            
            # ==================== 其他 ====================
            "shops": {
                "description": "店铺信息",
                "keywords": ["店铺", "门店"],
                "columns": {
                    "id": "店铺ID",
                    "owner_staff_id": "店主ID、商户ID",
                    "seat_id": "席位ID",
                    "name": "店铺名称",
                    "address": "地址",
                    "contact_phone": "联系电话",
                    "max_capacity": "最大容量",
                    "status": "状态",
                    "description": "描述",
                    "open_time": "开门时间",
                    "close_time": "关门时间",
                    "business_days": "营业日",
                    "created_at": "创建时间"
                }
            },
            "feedbacks": {
                "description": "顾客反馈/评价",
                "keywords": ["反馈", "评价", "评论", "评分"],
                "columns": {
                    "id": "反馈ID",
                    "shop_id": "店铺ID",
                    "customer_id": "顾客ID",
                    "game_session_id": "场次ID",
                    "feedback_type": "类型（1满意度/2建议/3投诉/4其他）",
                    "rating": "评分",
                    "content": "内容",
                    "images": "图片",
                    "status": "状态",
                    "reply_content": "回复内容",
                    "replied_by": "回复人",
                    "replied_at": "回复时间",
                    "created_at": "创建时间"
                }
            },
            "queue_entries": {
                "description": "排队等位",
                "keywords": ["排队", "等位", "取号"],
                "columns": {
                    "id": "记录ID",
                    "shop_id": "店铺ID",
                    "customer_id": "顾客ID",
                    "queue_number": "排队号",
                    "party_size": "人数",
                    "status": "状态",
                    "requested_at": "取号时间",
                    "seated_at": "入座时间",
                    "notified_at": "通知时间",
                    "remark": "备注",
                    "created_at": "创建时间"
                }
            },
            "daily_snapshots": {
                "description": "每日经营快照",
                "keywords": ["快照", "日报", "经营数据"],
                "columns": {
                    "id": "快照ID",
                    "shop_id": "店铺ID",
                    "snapshot_date": "快照日期",
                    "sales_total": "销售总额",
                    "revenue_confirmed": "确认收入",
                    "new_customers": "新顾客数",
                    "active_sessions": "活跃场次",
                    "average_duration": "平均时长（分钟）",
                    "top_package_id": "热销套餐ID",
                    "inventory_warns": "库存预警",
                    "created_at": "创建时间"
                }
            },
            "notification_logs": {
                "description": "消息通知日志",
                "keywords": ["通知", "消息"],
                "columns": {
                    "id": "日志ID",
                    "shop_id": "店铺ID",
                    "recipient_type": "接收者类型",
                    "recipient_id": "接收者ID",
                    "channel": "渠道",
                    "title": "标题",
                    "content": "内容",
                    "status": "状态",
                    "error_message": "错误信息",
                    "sent_at": "发送时间",
                    "created_at": "创建时间"
                }
            },
            "operation_logs": {
                "description": "操作日志",
                "keywords": ["操作日志", "日志"],
                "columns": {
                    "id": "日志ID",
                    "shop_id": "店铺ID",
                    "operator_type": "操作者类型",
                    "operator_id": "操作者ID",
                    "action": "操作",
                    "target_type": "目标类型",
                    "target_id": "目标ID",
                    "detail": "详情",
                    "ip_address": "IP地址",
                    "created_at": "创建时间"
                }
            }
        }
        
        # 表关联关系
        self.table_relationships = [
            # 购买相关
            ("purchases", "customers", "purchases.customer_id = customers.id"),
            ("purchases", "packages", "purchases.package_id = packages.id"),
            
            # 场次相关
            ("customer_sessions", "purchases", "customer_sessions.purchase_id = purchases.id"),
            ("customer_sessions", "customers", "customer_sessions.customer_id = customers.id"),
            ("game_sessions", "customer_sessions", "game_sessions.customer_session_id = customer_sessions.id"),
            ("game_sessions", "staff", "game_sessions.staff_id = staff.id"),
            ("game_sessions", "customers", "game_sessions.customer_id = customers.id"),
            
            # 收入相关
            ("revenue_records", "game_sessions", "revenue_records.game_session_id = game_sessions.id"),
            ("revenue_records", "purchases", "revenue_records.purchase_id = purchases.id"),
            ("revenue_records", "customers", "revenue_records.customer_id = customers.id"),
            
            # 退款相关
            ("refund_records", "purchases", "refund_records.purchase_id = purchases.id"),
            
            # 钱包相关
            ("wallet_transactions", "customer_wallets", "wallet_transactions.wallet_id = customer_wallets.id"),
            ("wallet_transactions", "customers", "wallet_transactions.customer_id = customers.id"),
            ("customer_wallets", "customers", "customer_wallets.customer_id = customers.id"),
            
            # 积分相关
            ("points_records", "customers", "points_records.customer_id = customers.id"),
            
            # 库存相关
            ("inventory", "materials", "inventory.material_id = materials.id"),
            ("inventory_transactions", "materials", "inventory_transactions.material_id = materials.id"),
            
            # 采购相关
            ("purchase_orders", "suppliers", "purchase_orders.supplier_id = suppliers.id"),
            ("purchase_order_items", "purchase_orders", "purchase_order_items.purchase_order_id = purchase_orders.id"),
            ("purchase_order_items", "materials", "purchase_order_items.material_id = materials.id"),
            ("purchase_payments", "purchase_orders", "purchase_payments.purchase_order_id = purchase_orders.id"),
            
            # 员工相关
            ("staff_shops", "staff", "staff_shops.staff_id = staff.id"),
            ("staff_shops", "shops", "staff_shops.shop_id = shops.id"),
            ("staff_schedules", "staff", "staff_schedules.staff_id = staff.id"),
            ("attendance_records", "staff", "attendance_records.staff_id = staff.id"),
            
            # 提成相关
            ("commission_settlements", "staff", "commission_settlements.staff_id = staff.id"),
            
            # 优惠券相关
            ("coupon_usages", "coupons", "coupon_usages.coupon_id = coupons.id"),
            ("coupon_usages", "customers", "coupon_usages.customer_id = customers.id"),
            
            # 文章相关
            ("articles", "article_categories", "articles.category_id = article_categories.id"),
            
            # 反馈相关
            ("feedbacks", "customers", "feedbacks.customer_id = customers.id"),
            ("feedbacks", "game_sessions", "feedbacks.game_session_id = game_sessions.id"),
            
            # 排队相关
            ("queue_entries", "customers", "queue_entries.customer_id = customers.id"),
            
            # 套餐BOM
            ("package_bom", "packages", "package_bom.package_id = packages.id"),
            ("package_bom", "materials", "package_bom.material_id = materials.id"),
            
            # 支出相关
            ("expenses", "expense_categories", "expenses.category_id = expense_categories.id"),
        ]
        
        # 自然语言到常用计算的映射
        self.calculation_mappings = {
            "营业额": "SUM(p.paid_amount)",
            "总营收": "SUM(rr.amount)",
            "总支出": "SUM(e.amount)",
            "净利润": "SUM(rr.amount) - SUM(e.amount)",
            "顾客数": "COUNT(DISTINCT c.id)",
            "消费人数": "COUNT(DISTINCT p.customer_id)",
            "订单数": "COUNT(p.id)",
            "消费次数": "COUNT(gs.id)",
            "平均消费": "AVG(p.paid_amount)",
            "人均消费": "SUM(p.paid_amount) / COUNT(DISTINCT p.customer_id)",
            "核销率": "COUNT(CASE WHEN cs.status = 2 THEN 1 END) / COUNT(cs.id) * 100",
            "退款金额": "SUM(rr2.refund_amount)",
            "新顾客": "COUNT(DISTINCT CASE WHEN DATE(c.created_at) = CURDATE() THEN c.id END)",
        }
        
        # 时间相关关键词
        self.time_keywords = {
            "今天": "DATE(created_at) = CURDATE()",
            "今日": "DATE(created_at) = CURDATE()",
            "昨天": "DATE(created_at) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)",
            "本周": "YEARWEEK(created_at) = YEARWEEK(CURDATE())",
            "这周": "YEARWEEK(created_at) = YEARWEEK(CURDATE())",
            "上周": "YEARWEEK(created_at) = YEARWEEK(CURDATE()) - 1",
            "本月": "MONTH(created_at) = MONTH(CURDATE()) AND YEAR(created_at) = YEAR(CURDATE())",
            "这个月": "MONTH(created_at) = MONTH(CURDATE()) AND YEAR(created_at) = YEAR(CURDATE())",
            "上月": "MONTH(created_at) = MONTH(DATE_SUB(CURDATE(), INTERVAL 1 MONTH)) AND YEAR(created_at) = YEAR(DATE_SUB(CURDATE(), INTERVAL 1 MONTH))",
            "本年": "YEAR(created_at) = YEAR(CURDATE())",
            "今年": "YEAR(created_at) = YEAR(CURDATE())",
            "去年": "YEAR(created_at) = YEAR(CURDATE()) - 1",
        }
    
    def extract_keywords(self, question: str) -> List[str]:
        """
        从问题中提取关键词（增强版：支持同义词扩展）
        
        Args:
            question: 用户问题
        
        Returns:
            关键词列表（包含同义词）
        """
        # 移除标点符号
        question = re.sub(r'[^\w\s]', ' ', question)
        # 提取中文词组（2-4字）
        chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,4}', question)
        # 提取数字
        numbers = re.findall(r'\d+', question)
        
        words = chinese_words + numbers
        
        # 同义词扩展
        expanded_words = set(words)
        for word in words:
            # 查找同义词
            for key, synonyms in self.SYNONYM_MAP.items():
                if word == key or word in synonyms:
                    # 添加同义词
                    expanded_words.add(key)
                    expanded_words.update(synonyms)
        
        return list(expanded_words)
    
    def match_tables(self, keywords: List[str]) -> Dict[str, float]:
        """匹配相关表并计算置信度"""
        table_scores = {}
        
        for table_name, info in self.table_info.items():
            score = 0
            # 检查表描述关键词
            for keyword in keywords:
                if keyword in info["description"]:
                    score += 2
                # 检查表关键词
                for table_keyword in info["keywords"]:
                    if keyword in table_keyword or table_keyword in keyword:
                        score += 3
                        break
            
            if score > 0:
                table_scores[table_name] = score
        
        return table_scores
    
    def match_columns(self, table_name: str, keywords: List[str]) -> List[str]:
        """匹配相关列（增强版）"""
        if table_name not in self.table_info:
            return []
        
        matched_columns = set()
        columns_info = self.table_info[table_name]["columns"]
        
        for column_name, column_desc in columns_info.items():
            for keyword in keywords:
                if keyword in column_desc:
                    matched_columns.add(column_name)
                    break
        
        # 如果没有匹配到特定列，返回常用列
        if not matched_columns:
            # 返回 id、shop_id 和常用列
            all_columns = list(columns_info.keys())
            matched_columns = set(all_columns[:6])
        
        return list(matched_columns)
    
    def find_join_paths(self, tables: List[str]) -> List[Tuple[str, str, str]]:
        """查找表关联路径"""
        join_paths = []
        
        for table1, table2, condition in self.table_relationships:
            if table1 in tables and table2 in tables:
                join_paths.append((table1, table2, condition))
        
        return join_paths
    
    def infer_additional_tables(self, matched_tables: Set[str]) -> Set[str]:
        """推断可能需要的关联表"""
        additional_tables = set()
        
        # 购买相关
        if "purchases" in matched_tables:
            additional_tables.add("customers")
            additional_tables.add("packages")
        
        # 场次相关
        if "game_sessions" in matched_tables:
            additional_tables.add("staff")
            additional_tables.add("customer_sessions")
            additional_tables.add("customers")
        
        if "customer_sessions" in matched_tables:
            additional_tables.add("purchases")
            additional_tables.add("customers")
        
        # 收入相关
        if "revenue_records" in matched_tables:
            additional_tables.add("game_sessions")
            additional_tables.add("purchases")
        
        # 库存相关
        if "inventory" in matched_tables:
            additional_tables.add("materials")
        
        if "inventory_transactions" in matched_tables:
            additional_tables.add("materials")
        
        # 采购相关
        if "purchase_orders" in matched_tables:
            additional_tables.add("suppliers")
        
        if "purchase_order_items" in matched_tables:
            additional_tables.add("purchase_orders")
            additional_tables.add("materials")
        
        # 支出相关
        if "expenses" in matched_tables:
            additional_tables.add("expense_categories")
        
        # 优惠券相关
        if "coupon_usages" in matched_tables:
            additional_tables.add("coupons")
            additional_tables.add("customers")
        
        # 文章相关
        if "articles" in matched_tables:
            additional_tables.add("article_categories")
        
        # 反馈相关
        if "feedbacks" in matched_tables:
            additional_tables.add("customers")
            additional_tables.add("game_sessions")
        
        return additional_tables - matched_tables
    
    def suggest_calculations(self, question: str) -> List[str]:
        """根据问题建议计算方式"""
        suggestions = []
        
        for keyword, calculation in self.calculation_mappings.items():
            if keyword in question:
                suggestions.append(f"{keyword}: {calculation}")
        
        return suggestions
    
    def get_time_filter(self, question: str, table_alias: str = "p") -> str:
        """根据问题提取时间过滤条件"""
        for keyword, condition in self.time_keywords.items():
            if keyword in question:
                # 替换表别名
                return condition.replace("created_at", f"{table_alias}.created_at")
        return ""
    
    def link(self, question: str) -> SchemaLink:
        """
        执行 Schema Linking
        
        Args:
            question: 用户自然语言问题
        
        Returns:
            SchemaLink 结果
        """
        # 1. 提取关键词
        keywords = self.extract_keywords(question)
        
        # 2. 匹配相关表
        table_scores = self.match_tables(keywords)
        
        # 3. 推断关联表
        matched_tables = set(table_scores.keys())
        additional_tables = self.infer_additional_tables(matched_tables)
        
        # 为推断的表添加较低的分数
        for table in additional_tables:
            if table not in table_scores:
                table_scores[table] = 1
        
        # 4. 匹配相关列
        relevant_columns = {}
        for table_name in table_scores:
            columns = self.match_columns(table_name, keywords)
            relevant_columns[table_name] = columns
        
        # 5. 查找关联路径
        all_tables = list(table_scores.keys())
        join_paths = self.find_join_paths(all_tables)
        
        # 6. 建议计算方式
        suggested_calculations = self.suggest_calculations(question)
        
        # 7. 计算总体置信度
        if not table_scores:
            confidence = 0.0
        else:
            max_score = max(table_scores.values())
            confidence = min(max_score / 10.0, 1.0)
        
        return SchemaLink(
            relevant_tables=all_tables,
            relevant_columns=relevant_columns,
            join_paths=join_paths,
            confidence=confidence,
            suggested_calculations=suggested_calculations
        )
    
    def format_for_prompt(self, link_result: SchemaLink) -> str:
        """将 Schema Link 结果格式化为 Prompt（增强版）"""
        if not link_result.relevant_tables:
            return "未找到相关的数据库表"
        
        lines = ["## 相关数据库表结构\n"]
        
        for table_name in link_result.relevant_tables:
            if table_name in self.table_info:
                info = self.table_info[table_name]
                lines.append(f"### {table_name} - {info['description']}")
                
                # 显示相关列
                columns = link_result.relevant_columns.get(table_name, [])
                for col in columns:
                    if col in info["columns"]:
                        lines.append(f"  - {col}: {info['columns'][col]}")
                lines.append("")
        
        # 添加关联信息
        if link_result.join_paths:
            lines.append("### 表关联关系（JOIN 条件）")
            for table1, table2, condition in link_result.join_paths:
                lines.append(f"  - {table1} JOIN {table2} ON {condition}")
            lines.append("")
        
        # 添加建议的计算方式
        if link_result.suggested_calculations:
            lines.append("### 建议的计算方式")
            for calc in link_result.suggested_calculations:
                lines.append(f"  - {calc}")
            lines.append("")
        
        return "\n".join(lines)


# 全局实例
schema_linker = SchemaLinker()


def get_schema_link(question: str) -> SchemaLink:
    """获取 Schema Link 结果"""
    return schema_linker.link(question)


def get_relevant_schema(question: str) -> str:
    """获取相关 Schema 信息（格式化后）"""
    link_result = schema_linker.link(question)
    return schema_linker.format_for_prompt(link_result)
