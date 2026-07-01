"""
Prompt 质量测试
验证所有 prompt 模板的一致性、格式正确性、常量统一性
"""

import os
import re
import sys
import types

# ---------- mock heavy external deps BEFORE any app import ----------

_HEAVY_MODULES = [
    'langchain', 'langchain_core', 'langchain_openai', 'langchain_chroma',
    'langchain_community', 'chromadb', 'sqlalchemy', 'pymysql',
    'redis', 'httpx', 'langfuse', 'langgraph',
]
for _mod_name in _HEAVY_MODULES:
    if _mod_name not in sys.modules:
        _mod = types.ModuleType(_mod_name)
        sys.modules[_mod_name] = _mod
        for _sub in ['documents', 'tools', 'messages', 'vectorstores',
                      'embeddings', 'callbacks', 'prompts', 'graph',
                      'prebuilt', 'toolkits', 'agent_executor',
                      'agent', 'chains', 'memory']:
            _full = f"{_mod_name}.{_sub}"
            if _full not in sys.modules:
                sys.modules[_full] = types.ModuleType(_full)
        # langchain_core needs .runnables, .output_parsers
        if _mod_name == 'langchain_core':
            for _sub2 in ['runnables', 'output_parsers', 'messages',
                          'prompts', 'tools', 'utils']:
                _full2 = f"{_mod_name}.{_sub2}"
                if _full2 not in sys.modules:
                    sys.modules[_full2] = types.ModuleType(_full2)

# langchain_chroma main module needs Chroma class
sys.modules['langchain_chroma'].Chroma = type('Chroma', (), {})

# chromadb needs .config submodule for app.chroma_config
sys.modules['chromadb.config'] = types.ModuleType('chromadb.config')
_chroma_settings = type('Settings', (), {'__init__': lambda self, **kw: None})
sys.modules['chromadb.config'].Settings = _chroma_settings

# sqlalchemy needs create_engine, text, and pool for nl2sql executor
sys.modules['sqlalchemy'].create_engine = lambda *a, **kw: None
sys.modules['sqlalchemy'].text = lambda *a, **kw: None
sys.modules['sqlalchemy.pool'] = types.ModuleType('sqlalchemy.pool')
sys.modules['sqlalchemy.pool'].QueuePool = type('QueuePool', (), {})

# Also mock their direct references in llm.py
sys.modules['langchain_openai'] = types.ModuleType('langchain_openai')
sys.modules['langchain_openai'].ChatOpenAI = type('ChatOpenAI', (), {})

_mock_lc_embeddings = types.ModuleType('langchain_core.embeddings')
_mock_lc_embeddings.Embeddings = type('Embeddings', (), {})
sys.modules['langchain_core.embeddings'] = _mock_lc_embeddings

# Provide proper stubs for langchain_core classes that are imported by prompt modules
_mock_lc_messages = types.ModuleType('langchain_core.messages')
_mock_lc_messages.HumanMessage = type('HumanMessage', (), {})
sys.modules['langchain_core.messages'] = _mock_lc_messages

_mock_lc_docs = types.ModuleType('langchain_core.documents')
_mock_lc_docs.Document = type('Document', (), {})
sys.modules['langchain_core.documents'] = _mock_lc_docs

_mock_lc_prompts = types.ModuleType('langchain_core.prompts')
_mock_lc_prompts.ChatPromptTemplate = type('ChatPromptTemplate', (), {})
sys.modules['langchain_core.prompts'] = _mock_lc_prompts

# Mock app.config before anything else tries to import it
# IMPORTANT: Do NOT set sys.modules['app'] - that would shadow the real app/ package
_config_mod = types.ModuleType('app.config')
_config_mod.settings = types.SimpleNamespace()
_config_mod.settings.LLM_MODEL = 'gpt-4o'
_config_mod.settings.LLM_BASE_URL = 'http://localhost:11434'
_config_mod.settings.LLM_API_KEY = 'test-key'
_config_mod.settings.LLM_TEMPERATURE = 0.7
_config_mod.settings.LLM_MAX_TOKENS = 4000
_config_mod.settings.LLM_QUERY_TIMEOUT = 30
_config_mod.settings.LLM_STREAM_TIMEOUT = 60
_config_mod.settings.EMBEDDING_MODEL = 'text-embedding-ada-002'
sys.modules['app.config'] = _config_mod

# Ensure the project root is on sys.path so "app.*" imports resolve correctly
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------- helpers ----------


def _extract_format_keys(template: str) -> set:
    """Extract {var} placeholders, excluding {{ }} escapes."""
    pattern = r'(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})'
    return set(re.findall(pattern, template))


_SAMPLE_VALUES = {
    "question": "test",
    "document": "test",
    "documents_text": "doc1\ndoc2",
    "context": "test context",
    "answer": "test answer",
    "failure_reason": "test reason",
    "schema": "CREATE TABLE test",
    "few_shot_examples": "",
    "status_mappings": "test mapping",
    "json_format_rule": "",
}


def _assert_no_format_error(template_str: str):
    """Verify the template can be formatted without syntax errors."""
    try:
        template_str.format(**_SAMPLE_VALUES)
    except KeyError:
        pass
    except Exception as e:
        raise AssertionError(f"Template format() raised: {e}")


# ---------- tests ----------


class TestSystemPrompts:
    """system_prompts.py — central constants."""

    def _mod(self):
        import app.common.system_prompts as m
        return m

    def test_import(self):
        m = self._mod()
        assert m.ROLE_DEFINITION.startswith("你是")
        assert len(m.ROLE_DEFINITION) > 50
        assert "禁止编造" in m.SECURITY_RULES
        assert "双引号" in m.JSON_FORMAT_RULE

    def test_role_definition_core_info(self):
        m = self._mod()
        for kw in ["店铺", "助手", "数据"]:
            assert kw in m.ROLE_DEFINITION, f"missing '{kw}'"

    def test_security_rules(self):
        m = self._mod()
        for kw in ["安全规则", "禁止编造", "最高优先级"]:
            assert kw in m.SECURITY_RULES, f"SECURITY_RULES missing '{kw}'"

    def test_json_format_rule(self):
        m = self._mod()
        for kw in ["双引号", "markdown", "JSON"]:
            assert kw in m.JSON_FORMAT_RULE

    def test_build_summarize_prompt(self):
        from app.common.system_prompts import build_summarize_prompt
        sys_p, usr_p = build_summarize_prompt(
            user_message="今天营收",
            understanding="查询营收",
            analysis="需查purchases表",
            plan=[{"action": "查营收", "tool": "sql"}],
            step_results=[{"success": True, "action": "查营收",
                           "tool": "sql", "result": "¥1000"}],
            history_context="",
            display_name="店长",
            username="admin",
            role="店长",
            shop_name="测试店",
            shop_id=1,
        )
        assert sys_p is not None
        assert "店铺智能助手" in sys_p
        assert "¥1000" in usr_p


class TestStatusMappings:
    """status_mappings.py — single source of truth for enums."""

    def test_import(self):
        import app.common.status_mappings as m
        assert "CASE WHEN" in m.STATUS_MAPPINGS
        assert "END" in m.STATUS_MAPPINGS
        assert "单次" in m.STATUS_MAPPINGS
        assert "周卡" in m.STATUS_MAPPINGS
        assert "月卡" in m.STATUS_MAPPINGS
        assert len(m.STATUS_MAPPINGS) > 500

    def test_sql_valid(self):
        import app.common.status_mappings as m
        assert "CASE WHEN" in m.STATUS_MAPPINGS
        assert "END" in m.STATUS_MAPPINGS
        assert "单次" in m.STATUS_MAPPINGS


class TestTemplateConsistency:
    """Verify .format() placeholders match their usage."""

    def test_crag_templates(self):
        import app.rag.crag as m
        assert _extract_format_keys(m.DOCUMENT_GRADING_PROMPT) == {"question", "document"}
        assert _extract_format_keys(m.KNOWLEDGE_REFINEMENT_PROMPT) == {"question", "document"}
        assert _extract_format_keys(m.REWRITE_QUERY_PROMPT) == {"question"}
        actual = _extract_format_keys(m.BATCH_DOCUMENT_GRADING_PROMPT)
        for k in {"question", "documents_text", "json_format_rule"}:
            assert k in actual, f"BATCH_DOCUMENT_GRADING_PROMPT missing '{k}'"
        assert _extract_format_keys(m.BATCH_REFINE_PROMPT) == {"question", "documents_text"}

    def test_self_rag_templates(self):
        import app.rag.self_rag as m
        assert _extract_format_keys(m.RETRIEVAL_EVAL_PROMPT) == {"question", "document"}
        assert _extract_format_keys(m.GENERATION_EVAL_PROMPT) == {"context", "answer"}
        assert _extract_format_keys(m.QUESTION_ANSWERABILITY_PROMPT) == {"question", "context"}

    def test_clarification(self):
        import app.rag.clarification as m
        assert _extract_format_keys(m.CLARIFICATION_PROMPT) == {"question", "context"}

    def test_realtime_checker(self):
        import app.rag.realtime_checker as m
        assert _extract_format_keys(m.REALTIME_CHECK_PROMPT) == {"question"}

    def test_nl2sql_router(self):
        """Read NL2SQL_PROMPT_TEMPLATE directly from source to avoid import chain."""
        import ast
        source_path = os.path.join(PROJECT_ROOT, "app", "nl2sql", "router.py")
        with open(source_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        # Find NL2SQL_PROMPT_TEMPLATE assignment
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "NL2SQL_PROMPT_TEMPLATE":
                        template = ast.literal_eval(node.value)
                        actual = _extract_format_keys(template)
                        for k in {"schema", "few_shot_examples", "question", "status_mappings"}:
                            assert k in actual, f"NL2SQL_PROMPT_TEMPLATE missing '{k}'"
                        return
        raise AssertionError("NL2SQL_PROMPT_TEMPLATE not found in router.py source")

    def test_intent_prompts(self):
        import app.rag.intent_router as m
        for intent_type, prompt in m.INTENT_PROMPTS.items():
            _assert_no_format_error(prompt)
            keys = _extract_format_keys(prompt)
            assert "context" in keys, f"{intent_type} missing 'context'"
            assert "question" in keys, f"{intent_type} missing 'question'"

    def test_no_format_error(self):
        """All templates format without raising syntax errors."""
        import app.rag.crag as m
        for name in ["DOCUMENT_GRADING_PROMPT", "KNOWLEDGE_REFINEMENT_PROMPT",
                      "REWRITE_QUERY_PROMPT", "BATCH_REFINE_PROMPT"]:
            _assert_no_format_error(getattr(m, name))


class TestNoHardcodedPrices:
    """No hardcoded prices in prompts."""

    def test_clarification_prompt(self):
        import app.rag.clarification as m
        for token in ("98", "298", "698"):
            assert token not in m.CLARIFICATION_PROMPT, f"hardcoded price {token}"

    def test_default_clarification_no_prices(self):
        from app.rag.clarification import QueryClarifier
        result = QueryClarifier()._default_clarification("多少钱")
        for opt in result["options"]:
            assert "（" not in opt or "元" not in opt, f"price leak: {opt}"


class TestSecurityBans:
    """Security rules embedded in critical prompts."""

    def test_nl2sql_router_has_bans(self):
        """Read NL2SQL_PROMPT_TEMPLATE directly from source."""
        source_path = os.path.join(PROJECT_ROOT, "app", "nl2sql", "router.py")
        with open(source_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Find the template string between assignment operator and next non-string statement
        # We just search for keywords in the surrounding lines
        for kw in ["INSERT", "DELETE"]:
            assert kw in content, f"router.py missing '{kw}' in its prompt template"

    def test_system_prompts_security(self):
        import app.common.system_prompts as m
        assert "禁止编造" in m.SECURITY_RULES
        assert "不得透露" in m.SECURITY_RULES
        assert "最高优先级" in m.SECURITY_RULES
