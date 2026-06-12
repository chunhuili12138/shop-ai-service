"""
数据格式化器
将查询结果格式化为前端可渲染的结构化数据
使用 LLM 判断最合适的显示方式
"""

import json
from typing import Optional, Dict, Any, List
from app.llm import get_chat_llm


# 可用渲染组件描述（传给 LLM）
AVAILABLE_COMPONENTS = """
## 可用的渲染组件

### 图表类（display_type: "chart"）
1. **line** - 折线图：适合趋势分析（营收趋势、客流变化、订单趋势）
2. **bar** - 柱状图：适合对比分析（套餐销量对比、员工绩效对比、时段客流对比）
3. **pie** - 饼图：适合占比分析（顾客来源占比、支付方式占比、套餐类型占比）
4. **gauge** - 仪表盘：适合单一指标（目标完成率、库存充足率、好评率）
5. **funnel** - 漏斗图：适合转化分析（顾客转化率、订单转化率）
6. **radar** - 雷达图：适合多维度对比（店铺综合评分、员工能力评估）

### 数据展示类
7. **table** - 表格：适合列表数据（顾客列表、订单记录、库存明细）
8. **card** - 统计卡片：适合关键指标（今日概况、本月统计、预警统计）
9. **rank** - 排行榜：适合排名数据（热销套餐TOP、员工绩效排名、顾客消费排名）
10. **timeline** - 时间线：适合操作记录、历史数据
11. **kv** - 键值对：适合详情信息（顾客详情、订单详情、套餐详情）

### 内容类
12. **code** - 代码块：适合 SQL 查询展示
13. **markdown** - Markdown：适合富文本说明、解释性内容
"""

# 输出格式要求（传给 LLM）
OUTPUT_FORMAT_PROMPT = """
请根据查询结果，选择最合适的渲染组件，并输出对应格式的 JSON。

## 输出格式
只返回 JSON，不要其他解释。JSON 格式如下：

```json
{
  "display_type": "组件类型",
  "chart_type": "图表类型（仅 display_type=chart 时需要）",
  "title": "标题",
  "data": { ... },
  "summary": "总结文字（一句话概括数据要点）"
}
```

## 各组件数据格式

### 折线图 (line)
```json
{
  "display_type": "chart",
  "chart_type": "line",
  "title": "本月营收趋势",
  "data": {
    "xAxis": ["01-01", "01-02", "01-03"],
    "series": [
      {"name": "营业额", "data": [1500, 2000, 1800], "unit": "元"}
    ]
  },
  "summary": "本月营收整体呈上升趋势"
}
```

### 柱状图 (bar)
```json
{
  "display_type": "chart",
  "chart_type": "bar",
  "title": "本月热销套餐",
  "data": {
    "xAxis": ["周卡", "月卡", "单次"],
    "series": [
      {"name": "销量", "data": [45, 32, 28], "unit": "单"}
    ]
  },
  "summary": "周卡销量最高"
}
```

### 饼图 (pie)
```json
{
  "display_type": "chart",
  "chart_type": "pie",
  "title": "顾客来源渠道",
  "data": {
    "series": [
      {"name": "小程序", "value": 45},
      {"name": "美团", "value": 25}
    ]
  },
  "summary": "小程序渠道占比最高"
}
```

### 仪表盘 (gauge)
```json
{
  "display_type": "chart",
  "chart_type": "gauge",
  "title": "本月目标完成率",
  "data": {
    "value": 78,
    "min": 0,
    "max": 100,
    "unit": "%"
  },
  "summary": "本月目标完成78%"
}
```

### 漏斗图 (funnel)
```json
{
  "display_type": "chart",
  "chart_type": "funnel",
  "title": "顾客转化漏斗",
  "data": {
    "series": [
      {"name": "访问", "value": 1000},
      {"name": "注册", "value": 300},
      {"name": "购买", "value": 100}
    ]
  },
  "summary": "访问到购买转化率10%"
}
```

### 雷达图 (radar)
```json
{
  "display_type": "chart",
  "chart_type": "radar",
  "title": "店铺综合评分",
  "data": {
    "indicators": [
      {"name": "营收", "max": 100},
      {"name": "客流", "max": 100}
    ],
    "series": [
      {"name": "本月", "data": [85, 72]}
    ]
  },
  "summary": "营收表现最好"
}
```

### 表格 (table)
```json
{
  "display_type": "table",
  "title": "顾客列表",
  "data": {
    "columns": ["ID", "昵称", "手机", "消费金额"],
    "rows": [
      [1, "张三", "138****1234", "¥2,580"],
      [2, "李四", "139****5678", "¥1,200"]
    ],
    "total": 2
  },
  "summary": "共2位顾客"
}
```

### 统计卡片 (card)
```json
{
  "display_type": "card",
  "title": "今日概况",
  "data": {
    "cards": [
      {"label": "营业额", "value": "¥2,580", "icon": "revenue", "trend": "+12%"},
      {"label": "订单数", "value": "8", "icon": "order", "trend": "+3"}
    ]
  },
  "summary": "今日经营状况良好"
}
```

### 排行榜 (rank)
```json
{
  "display_type": "rank",
  "title": "本月热销套餐 TOP5",
  "data": {
    "items": [
      {"rank": 1, "name": "周卡", "value": "45单", "amount": "¥13,500"},
      {"rank": 2, "name": "月卡", "value": "32单", "amount": "¥9,600"}
    ]
  },
  "summary": "周卡销量最高"
}
```

### 时间线 (timeline)
```json
{
  "display_type": "timeline",
  "title": "今日操作记录",
  "data": {
    "items": [
      {"time": "14:30", "action": "核销", "detail": "张三 - 周卡", "operator": "李导玩"},
      {"time": "13:15", "action": "入库", "detail": "颜料 x10", "operator": "王仓管"}
    ]
  },
  "summary": "今日共2条操作记录"
}
```

### 键值对 (kv)
```json
{
  "display_type": "kv",
  "title": "顾客详情",
  "data": {
    "items": [
      {"label": "昵称", "value": "张三"},
      {"label": "手机", "value": "138****1234"}
    ]
  },
  "summary": ""
}
```

### 代码块 (code)
```json
{
  "display_type": "code",
  "title": "生成的 SQL",
  "data": {
    "language": "sql",
    "content": "SELECT * FROM purchases WHERE shop_id = 1"
  },
  "summary": ""
}
```

### Markdown (markdown)
```json
{
  "display_type": "markdown",
  "title": "",
  "data": {
    "content": "这里是 Markdown 内容"
  },
  "summary": ""
}
```
"""


class DataFormatter:
    """
    数据格式化器
    
    功能：
    1. 使用 LLM 判断最合适的显示方式
    2. 将查询结果格式化为前端可渲染的结构化数据
    """
    
    def __init__(self):
        self._llm = None
    
    @property
    def llm(self):
        """懒加载 LLM"""
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0)
        return self._llm
    
    async def format_with_llm(self, question: str, raw_data: str) -> Dict[str, Any]:
        """
        使用 LLM 格式化数据
        
        Args:
            question: 用户问题
            raw_data: 原始查询结果（文本格式）
        
        Returns:
            格式化后的数据（包含 display_type）
        """
        try:
            from langchain_core.messages import HumanMessage
            
            prompt = f"""你是一个数据可视化专家。根据用户的问题和查询结果，选择最合适的渲染组件，并输出对应格式的 JSON。

## 用户问题
{question}

## 查询结果
{raw_data}

{AVAILABLE_COMPONENTS}

{OUTPUT_FORMAT_PROMPT}"""

            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            
            # 提取 JSON
            content = response.content.strip()
            
            # 尝试解析 JSON
            # 如果包含 ```json ... ``` 格式，先提取
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()
            
            result = json.loads(content)
            
            # 验证必要字段
            if "display_type" not in result:
                result["display_type"] = "markdown"
            
            if "data" not in result:
                result["data"] = {"content": raw_data}
            
            if "summary" not in result:
                result["summary"] = ""
            
            return result
            
        except json.JSONDecodeError as e:
            print(f"[DataFormatter] JSON 解析失败: {str(e)}")
            # 返回 Markdown 格式
            return {
                "display_type": "markdown",
                "title": "",
                "data": {"content": raw_data},
                "summary": ""
            }
        except Exception as e:
            print(f"[DataFormatter] 格式化失败: {str(e)}")
            # 返回 Markdown 格式
            return {
                "display_type": "markdown",
                "title": "",
                "data": {"content": raw_data},
                "summary": ""
            }
    
    def format_as_table(self, title: str, columns: List[str], rows: List[List[Any]], summary: str = "") -> Dict[str, Any]:
        """
        快速格式化为表格
        
        Args:
            title: 标题
            columns: 列名列表
            rows: 数据行
            summary: 总结
        
        Returns:
            格式化后的数据
        """
        return {
            "display_type": "table",
            "title": title,
            "data": {
                "columns": columns,
                "rows": rows,
                "total": len(rows)
            },
            "summary": summary
        }
    
    def format_as_card(self, title: str, cards: List[Dict[str, str]], summary: str = "") -> Dict[str, Any]:
        """
        快速格式化为统计卡片
        
        Args:
            title: 标题
            cards: 卡片列表 [{"label": "标签", "value": "值", "icon": "图标", "trend": "趋势"}]
            summary: 总结
        
        Returns:
            格式化后的数据
        """
        return {
            "display_type": "card",
            "title": title,
            "data": {"cards": cards},
            "summary": summary
        }
    
    def format_as_chart(self, title: str, chart_type: str, x_axis: List[str], series: List[Dict], summary: str = "") -> Dict[str, Any]:
        """
        快速格式化为图表
        
        Args:
            title: 标题
            chart_type: 图表类型（line/bar/pie）
            x_axis: X 轴标签
            series: 数据系列
            summary: 总结
        
        Returns:
            格式化后的数据
        """
        return {
            "display_type": "chart",
            "chart_type": chart_type,
            "title": title,
            "data": {
                "xAxis": x_axis,
                "series": series
            },
            "summary": summary
        }
    
    def format_as_rank(self, title: str, items: List[Dict[str, Any]], summary: str = "") -> Dict[str, Any]:
        """
        快速格式化为排行榜
        
        Args:
            title: 标题
            items: 排行列表 [{"rank": 1, "name": "名称", "value": "值", "amount": "金额"}]
            summary: 总结
        
        Returns:
            格式化后的数据
        """
        return {
            "display_type": "rank",
            "title": title,
            "data": {"items": items},
            "summary": summary
        }
    
    def format_as_markdown(self, content: str, title: str = "") -> Dict[str, Any]:
        """
        快速格式化为 Markdown
        
        Args:
            content: Markdown 内容
            title: 标题
        
        Returns:
            格式化后的数据
        """
        return {
            "display_type": "markdown",
            "title": title,
            "data": {"content": content},
            "summary": ""
        }


# 全局实例
_data_formatter = None


def get_data_formatter() -> DataFormatter:
    """获取数据格式化器单例"""
    global _data_formatter
    if _data_formatter is None:
        _data_formatter = DataFormatter()
    return _data_formatter
