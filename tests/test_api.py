"""
测试用例模板
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


class TestHealthCheck:
    """健康检查测试"""

    def test_root(self):
        """测试根路径"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "ShopCopilot AI Service"
        assert data["status"] == "running"

    def test_health(self):
        """测试健康检查"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestRAG:
    """RAG模块测试"""

    @pytest.mark.skip(reason="需要OpenAI API Key")
    def test_query(self):
        """测试知识库查询"""
        response = client.post(
            "/api/rag/query",
            json={
                "question": "你们这里有周卡吗？",
                "shop_id": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "sources" in data


class TestNL2SQL:
    """NL2SQL模块测试"""

    @pytest.mark.skip(reason="需要数据库连接")
    def test_query(self):
        """测试自然语言查询"""
        response = client.post(
            "/api/nl2sql/query",
            json={
                "question": "本月营业额是多少？",
                "shop_id": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "sql" in data
        assert "results" in data


class TestTools:
    """Tool Calling模块测试"""

    @pytest.mark.skip(reason="需要OpenAI API Key")
    def test_call(self):
        """测试工具调用"""
        response = client.post(
            "/api/tools/call",
            json={
                "question": "查询库存不足的物料",
                "shop_id": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data

    def test_list_tools(self):
        """测试工具列表"""
        response = client.get("/api/tools/list")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert len(data["tools"]) > 0


class TestAgent:
    """Agent模块测试"""

    @pytest.mark.skip(reason="需要OpenAI API Key")
    def test_chat(self):
        """测试Agent对话"""
        response = client.post(
            "/api/agent/chat",
            json={
                "message": "你好",
                "shop_id": 1,
                "user_id": 1,
                "user_role": "guest",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
