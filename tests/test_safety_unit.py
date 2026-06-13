"""
nl2sql/safety.py 单元测试
直接加载 safety.py 文件，绕过 nl2sql/__init__.py 的重依赖链
"""

import sys
import os
import types
import importlib.util
import pytest

# 1. Mock 掉所有重依赖（在 import 之前）
_heavy_modules = [
    'langchain', 'langchain_core', 'langchain_openai', 'langchain_chroma',
    'langchain_community', 'chromadb', 'sqlalchemy', 'pymysql',
    'redis', 'httpx', 'langfuse', 'langgraph',
]
for mod_name in _heavy_modules:
    if mod_name not in sys.modules:
        mod = types.ModuleType(mod_name)
        # 为子模块也创建占位
        sys.modules[mod_name] = mod
        for sub in ['documents', 'tools', 'messages', 'vectorstores', 'embeddings', 'callbacks']:
            full = f"{mod_name}.{sub}"
            if full not in sys.modules:
                sys.modules[full] = types.ModuleType(full)

# 2. Mock app.config 和 app.nl2sql 的 __init__，避免级联导入
config_mod = types.ModuleType('app.config')

class _MockSettings:
    NL2SQL_DANGEROUS_KEYWORDS = ["DROP", "DELETE", "TRUNCATE", "ALTER", "UPDATE", "INSERT"]
    NL2SQL_MAX_ROWS = 100

config_mod.settings = _MockSettings()
sys.modules['app.config'] = config_mod

# 3. 直接加载 safety.py 文件
_spec = importlib.util.spec_from_file_location(
    "app.nl2sql.safety",
    os.path.join(os.path.dirname(__file__), '..', 'app', 'nl2sql', 'safety.py'),
)
safety = importlib.util.module_from_spec(_spec)
sys.modules['app.nl2sql.safety'] = safety
_spec.loader.exec_module(safety)

# 4. 从加载的模块中导入函数
validate_sql = safety.validate_sql
sanitize_sql = safety.sanitize_sql
add_limit = safety.add_limit
add_shop_filter = safety.add_shop_filter
_detect_main_alias = safety._detect_main_alias


class TestValidateSql:
    """SQL 安全校验测试"""

    def test_valid_select(self):
        is_safe, msg = validate_sql("SELECT * FROM customers WHERE shop_id = 1")
        assert is_safe is True

    def test_block_dangerous_keywords(self):
        for keyword in ["DROP", "DELETE", "TRUNCATE", "ALTER", "UPDATE", "INSERT"]:
            is_safe, msg = validate_sql(f"{keyword} TABLE customers")
            assert is_safe is False
            assert keyword in msg

    def test_block_non_select(self):
        is_safe, msg = validate_sql("CREATE TABLE test (id INT)")
        assert is_safe is False

    def test_block_into_outfile(self):
        is_safe, msg = validate_sql("SELECT * FROM t INTO OUTFILE '/tmp/test'")
        assert is_safe is False

    def test_block_sleep(self):
        is_safe, msg = validate_sql("SELECT SLEEP(10)")
        assert is_safe is False

    def test_block_benchmark(self):
        is_safe, msg = validate_sql("SELECT BENCHMARK(1000000, SHA1('test'))")
        assert is_safe is False

    def test_block_unbalanced_quotes(self):
        is_safe, msg = validate_sql("SELECT * FROM t WHERE name = 'test")
        assert is_safe is False


class TestSanitizeSql:
    """SQL 清理测试"""

    def test_remove_markdown_sql(self):
        assert sanitize_sql("```sql\nSELECT * FROM t\n```") == "SELECT * FROM t"

    def test_remove_markdown_generic(self):
        assert sanitize_sql("```\nSELECT * FROM t\n```") == "SELECT * FROM t"

    def test_remove_single_line_comment(self):
        result = sanitize_sql("SELECT * FROM t -- this is a comment")
        assert "--" not in result

    def test_remove_multi_line_comment(self):
        result = sanitize_sql("SELECT * /* comment */ FROM t")
        assert "/*" not in result

    def test_remove_trailing_semicolon(self):
        assert not sanitize_sql("SELECT * FROM t;").endswith(";")

    def test_fix_double_percent(self):
        result = sanitize_sql("SELECT DATE_FORMAT(d, '%%Y-%%m')")
        assert "%%" not in result

    def test_collapse_whitespace(self):
        result = sanitize_sql("SELECT  *   FROM     t")
        assert "  " not in result


class TestAddLimit:
    def test_add_limit_when_missing(self):
        assert "LIMIT 50" in add_limit("SELECT * FROM t", max_rows=50)

    def test_preserve_existing_limit(self):
        result = add_limit("SELECT * FROM t LIMIT 10", max_rows=50)
        assert result.count("LIMIT") == 1


class TestAddShopFilter:
    def test_add_where_clause(self):
        result = add_shop_filter("SELECT * FROM customers", 5)
        assert "shop_id = 5" in result

    def test_add_to_existing_where(self):
        result = add_shop_filter("SELECT * FROM customers WHERE name = 'a'", 5)
        assert "shop_id = 5" in result

    def test_skip_if_already_present(self):
        sql = "SELECT * FROM customers WHERE shop_id = 5"
        assert add_shop_filter(sql, 5) == sql

    def test_detect_table_alias(self):
        result = add_shop_filter("SELECT * FROM customers c WHERE c.name = 'a'", 3)
        assert "c.shop_id = 3" in result

    def test_subquery_no_alias(self):
        result = add_shop_filter("SELECT * FROM (SELECT * FROM orders) sub", 5)
        assert "shop_id = 5" in result

    def test_type_coercion(self):
        result = add_shop_filter("SELECT * FROM customers", "5")
        assert "shop_id = 5" in result

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="shop_id 必须是整数"):
            add_shop_filter("SELECT * FROM customers", "abc")


class TestDetectMainAlias:
    def test_simple_alias(self):
        assert _detect_main_alias("SELECT * FROM customers c WHERE c.id = 1") == "c"

    def test_as_alias(self):
        assert _detect_main_alias("SELECT * FROM customers AS c WHERE c.id = 1") == "c"

    def test_no_alias_returns_default(self):
        assert _detect_main_alias("SELECT * FROM customers") == "p"

    def test_keyword_not_alias(self):
        assert _detect_main_alias("SELECT * FROM customers WHERE id = 1") == "p"
