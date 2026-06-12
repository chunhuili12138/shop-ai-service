"""
MySQL SQL 编写规则库
包含常见易错点、最佳实践、正确/错误示例
"""

# MySQL GROUP BY 规则
GROUP_BY_RULES = """
### GROUP BY 规则（重要！）

1. **禁止在 GROUP BY 中使用列别名**（MySQL 不支持）
   - ❌ 错误：SELECT CASE WHEN ... END AS level ... GROUP BY level
   - ✅ 正确：GROUP BY CASE WHEN ... END（重复完整表达式）
   - ✅ 正确：使用子查询包装

2. **GROUP BY 中的非聚合列**
   - ❌ 错误：SELECT name, COUNT(*) FROM table（name 不在 GROUP BY 中）
   - ✅ 正确：SELECT name, COUNT(*) FROM table GROUP BY name

3. **GROUP BY 1 的兼容性**
   - ⚠️ GROUP BY 1（列位置）在某些 MySQL 版本中不支持
   - ✅ 建议：使用完整的表达式
"""

# MySQL JOIN 规则
JOIN_RULES = """
### JOIN 规则

1. **明确指定 JOIN 类型**
   - INNER JOIN：只返回两表都匹配的行
   - LEFT JOIN：返回左表所有行，右表匹配的行（可能为 NULL）

2. **JOIN 条件必须明确**
   - ❌ 错误：SELECT * FROM orders, customers（隐式连接）
   - ✅ 正确：SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id

3. **多表 JOIN 时列名必须带别名**
   - ❌ 错误：SELECT id, name FROM orders JOIN customers ...
   - ✅ 正确：SELECT o.id, c.name FROM orders o JOIN customers c ...
"""

# MySQL 日期函数规则
DATE_RULES = """
### 日期函数规则

1. **获取当前日期**
   - CURDATE()：返回日期（如 2024-01-15）
   - NOW()：返回日期时间（如 2024-01-15 10:30:00）

2. **日期比较**
   - ❌ 错误：WHERE created_at = '2024-01-15'（可能丢失时间部分）
   - ✅ 正确：WHERE DATE(created_at) = '2024-01-15'

3. **日期计算**
   - 7天前：DATE_SUB(CURDATE(), INTERVAL 7 DAY)
   - 30天前：DATE_SUB(CURDATE(), INTERVAL 30 DAY)
   - 本月：MONTH(date) = MONTH(CURDATE()) AND YEAR(date) = YEAR(CURDATE())
   - 本年：YEAR(date) = YEAR(CURDATE())

4. **日期格式化**
   - DATE_FORMAT(date, '%Y-%m')：格式化为年-月
   - YEAR(date)：提取年份
   - MONTH(date)：提取月份
"""

# MySQL 聚合函数规则
AGGREGATE_RULES = """
### 聚合函数规则

1. **COUNT 规则**
   - COUNT(*)：计算所有行（包括 NULL）
   - COUNT(column)：计算非 NULL 的行
   - COUNT(DISTINCT column)：计算不重复的非 NULL 行

2. **SUM/AVG 规则**
   - SUM(column)：求和（忽略 NULL）
   - AVG(column)：平均值（忽略 NULL）
   - ❌ 错误：SELECT SUM(amount) / COUNT(*)（如果 amount 有 NULL，结果不准确）
   - ✅ 正确：SELECT AVG(amount) 或 SELECT SUM(amount) / COUNT(amount)

3. **NULL 处理**
   - COALESCE(value, default)：如果 value 为 NULL，返回 default
   - ❌ 错误：SELECT SUM(amount)（如果所有 amount 都是 NULL，返回 NULL）
   - ✅ 正确：SELECT COALESCE(SUM(amount), 0)
"""

# MySQL CASE WHEN 规则
CASE_WHEN_RULES = """
### CASE WHEN 规则

1. **CASE WHEN 作为分组依据**
   - ❌ 错误：SELECT CASE WHEN ... END AS level ... GROUP BY level
   - ✅ 正确：GROUP BY CASE WHEN ... END（重复完整表达式）
   - ✅ 正确：使用子查询

2. **子查询包装示例**
   ```sql
   SELECT level, COUNT(*) FROM (
       SELECT id, CASE WHEN ... END AS level FROM ...
   ) t GROUP BY level
   ```

3. **CASE WHEN 与 NULL**
   - CASE WHEN column IS NULL THEN '未知' ELSE '有值' END
"""

# MySQL 子查询规则
SUBQUERY_RULES = """
### 子查询规则

1. **子查询作为派生表**
   - 必须有别名
   - ❌ 错误：SELECT * FROM (SELECT ...) 
   - ✅ 正确：SELECT * FROM (SELECT ...) AS t

2. **子查询与 GROUP BY**
   - 当需要对 GROUP BY 结果再聚合时，使用子查询

3. **EXISTS vs IN**
   - EXISTS：适合子查询结果集大的情况
   - IN：适合子查询结果集小的情况
"""

# MySQL LIMIT 规则
LIMIT_RULES = """
### LIMIT 规则

1. **LIMIT 必须与 ORDER BY 一起使用**
   - ❌ 错误：SELECT * FROM table LIMIT 10（结果不确定）
   - ✅ 正确：SELECT * FROM table ORDER BY id LIMIT 10

2. **LIMIT 语法**
   - LIMIT n：返回前 n 行
   - LIMIT offset, count：从第 offset 行开始，返回 count 行
   - LIMIT count OFFSET offset：同上，但语法更清晰
"""

# MySQL 常见错误模式
COMMON_ERROR_PATTERNS = """
### 常见错误模式

1. **ambiguous column（列名歧义）**
   - 原因：多表 JOIN 时，列名在多个表中存在
   - 解决：为所有列添加表别名

2. **Unknown column（未知列）**
   - 原因：列名拼写错误或不存在
   - 解决：检查数据库结构

3. **Table doesn't exist（表不存在）**
   - 原因：表名拼写错误
   - 解决：检查数据库结构

4. **You have an error in your SQL syntax（语法错误）**
   - 原因：括号、引号、关键字拼写错误
   - 解决：仔细检查 SQL 语法

5. **isn't in GROUP BY（GROUP BY 错误）**
   - 原因：SELECT 中的非聚合列不在 GROUP BY 中
   - 解决：将非聚合列添加到 GROUP BY

6. **FUNCTION does not exist（函数不存在）**
   - 原因：函数名拼写错误或 MySQL 版本不支持
   - 解决：检查函数名和 MySQL 版本
"""

# 合并所有规则
ALL_MYSQL_RULES = f"""
## MySQL 编写规则（必须严格遵守）

{GROUP_BY_RULES}

{JOIN_RULES}

{DATE_RULES}

{AGGREGATE_RULES}

{CASE_WHEN_RULES}

{SUBQUERY_RULES}

{LIMIT_RULES}

{COMMON_ERROR_PATTERNS}
"""
