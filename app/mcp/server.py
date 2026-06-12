"""
MCP Server实现
将店铺API封装为标准MCP Server
"""

from typing import Any
import json
from app.mcp.tools import get_mcp_tools, get_tool_by_name
from app.mcp.resources import get_mcp_resources, get_resource_content


class MCPServer:
    """
    MCP Server实现
    
    支持：
    - Tools: 工具调用
    - Resources: 资源读取
    """

    def __init__(self):
        self.name = "shop-copilot-mcp"
        self.version = "0.1.0"

    def handle_request(self, request: dict) -> dict:
        """处理MCP请求"""
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")

        if method == "initialize":
            return self._handle_initialize(params, request_id)
        elif method == "tools/list":
            return self._handle_list_tools(request_id)
        elif method == "tools/call":
            return self._handle_call_tool(params, request_id)
        elif method == "resources/list":
            return self._handle_list_resources(request_id)
        elif method == "resources/read":
            return self._handle_read_resource(params, request_id)
        else:
            return self._error_response(request_id, -32601, f"Method not found: {method}")

    def _handle_initialize(self, params: dict, request_id: Any) -> dict:
        """处理初始化请求"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {},
                },
                "serverInfo": {
                    "name": self.name,
                    "version": self.version,
                },
            },
        }

    def _handle_list_tools(self, request_id: Any) -> dict:
        """处理工具列表请求"""
        tools = get_mcp_tools()
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.input_schema,
                    }
                    for t in tools
                ]
            },
        }

    def _handle_call_tool(self, params: dict, request_id: Any) -> dict:
        """处理工具调用请求"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        tool = get_tool_by_name(tool_name)
        if not tool:
            return self._error_response(request_id, -32602, f"Tool not found: {tool_name}")

        try:
            # 动态导入并调用处理函数
            import importlib
            module_path, func_name = tool.handler.rsplit(".", 1)
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
            result = func.invoke(arguments)

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": str(result),
                        }
                    ]
                },
            }
        except Exception as e:
            return self._error_response(request_id, -32603, f"Tool execution failed: {str(e)}")

    def _handle_list_resources(self, request_id: Any) -> dict:
        """处理资源列表请求"""
        resources = get_mcp_resources()
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "resources": [
                    {
                        "uri": r.uri,
                        "name": r.name,
                        "description": r.description,
                        "mimeType": r.mime_type,
                    }
                    for r in resources
                ]
            },
        }

    def _handle_read_resource(self, params: dict, request_id: Any) -> dict:
        """处理资源读取请求"""
        uri = params.get("uri")
        content = get_resource_content(uri)

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": content,
                    }
                ]
            },
        }

    def _error_response(self, request_id: Any, code: int, message: str) -> dict:
        """生成错误响应"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }


# 全局MCP Server实例
mcp_server = MCPServer()
