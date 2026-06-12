"""
JSON 解析工具
提供安全的 JSON 解析功能，支持修复常见的格式问题
"""

import json
import ast
import re
from typing import Any, Optional


def safe_parse_json(content: str, default: Any = None) -> Any:
    """
    安全解析 JSON，支持修复常见的格式问题
    
    Args:
        content: JSON 字符串
        default: 解析失败时的默认值
    
    Returns:
        解析后的对象，或默认值
    """
    if not content:
        return default
    
    # 1. 提取 JSON（移除 markdown 代码块）
    extracted = extract_json_from_markdown(content)
    
    # 2. 尝试直接解析标准 JSON
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        pass
    
    # 3. 尝试用 ast.literal_eval 解析 Python 字面量（安全处理单引号）
    #    这能正确处理 {'name': 'John's'} 这种情况
    try:
        result = ast.literal_eval(extracted)
        if isinstance(result, (dict, list)):
            return result
    except (ValueError, SyntaxError):
        pass
    
    # 4. 尝试用正则精确替换键名的单引号（不替换值中的单引号）
    try:
        fixed = _fix_json_quotes(extracted)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    # 5. 尝试补全缺失的括号
    try:
        fixed = extracted.rstrip()
        if not fixed.endswith("}") and not fixed.endswith("]"):
            if fixed.startswith("{"):
                fixed += "}"
            elif fixed.startswith("["):
                fixed += "]"
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    # 6. 尝试移除尾部多余内容
    try:
        for i in range(len(extracted) - 1, -1, -1):
            if extracted[i] in ('}', ']'):
                try:
                    return json.loads(extracted[:i + 1])
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    
    # 7. 所有尝试都失败，返回默认值
    return default


def _fix_json_quotes(text: str) -> str:
    """
    精确修复 JSON 中的单引号问题
    只替换键名和简单值的单引号，不破坏值中包含的单引号
    
    策略：
    1. 识别 {'key': 'value'} 模式
    2. 键名的单引号替换为双引号
    3. 值的单引号：如果是简单值（无嵌套引号），替换为双引号
    4. 如果值中包含单引号，保留原样（交给 ast.literal_eval 处理）
    """
    # 匹配 'key': 模式（键名）
    result = re.sub(r"'(\w+)'\s*:", r'"\1":', text)
    
    # 匹配 : 'simple_value' 模式（简单值，不含引号）
    # 使用负向前瞻确保值中不包含单引号
    result = re.sub(r":\s*'([^']*?)'(\s*[,}\]])", r': "\1"\2', result)
    
    return result


def extract_json_from_markdown(content: str) -> str:
    """
    从 Markdown 内容中提取 JSON
    
    Args:
        content: 可能包含 markdown 代码块的内容
    
    Returns:
        提取的 JSON 字符串
    """
    content = content.strip()
    
    # 尝试提取 ```json ... ``` 中的内容
    if "```json" in content:
        start = content.find("```json") + 7
        end = content.find("```", start)
        if end != -1:
            return content[start:end].strip()
    
    # 尝试提取 ``` ... ``` 中的内容
    if "```" in content:
        start = content.find("```") + 3
        end = content.find("```", start)
        if end != -1:
            return content[start:end].strip()
    
    # 尝试提取 { ... } 或 [ ... ]
    start_obj = content.find("{")
    start_arr = content.find("[")
    
    if start_obj == -1 and start_arr == -1:
        return content
    
    if start_obj == -1:
        start = start_arr
    elif start_arr == -1:
        start = start_obj
    else:
        start = min(start_obj, start_arr)
    
    # 找到最后一个 } 或 ]
    end_obj = content.rfind("}")
    end_arr = content.rfind("]")
    end = max(end_obj, end_arr)
    
    if end > start:
        return content[start:end + 1]
    
    return content[start:]
