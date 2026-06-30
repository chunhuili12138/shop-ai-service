"""
ShopCopilot AI Service 监控指标模块

提供全面的监控指标收集，包括：
- LLM 调用监控
- Agent 运行监控
- Task Router 监控
- NL2SQL 监控
- RAG 检索监控
- 工具执行监控
- 系统监控

使用 Prometheus 客户端进行指标收集和暴露。
"""

from typing import Optional, Dict, Any
from prometheus_client import Counter, Histogram, Gauge, Info, start_http_server
import time
import logging

logger = logging.getLogger(__name__)


class MetricsCollector:
    """监控指标收集器"""
    
    def __init__(self):
        self._initialized = False
        self._start_time = time.time()
        
    def initialize(self):
        """初始化所有监控指标"""
        if self._initialized:
            return
            
        # LLM 监控指标
        self.llm_calls_total = Counter(
            'llm_calls_total',
            'LLM 调用总次数',
            ['model']
        )
        
        self.llm_success_total = Counter(
            'llm_success_total',
            'LLM 调用成功次数',
            ['model']
        )
        
        self.llm_errors_total = Counter(
            'llm_errors_total',
            'LLM 调用失败次数',
            ['model', 'error_type']
        )
        
        self.llm_latency_seconds = Histogram(
            'llm_latency_seconds',
            'LLM 调用延迟（秒）',
            ['model'],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
        )
        
        self.llm_tokens_total = Counter(
            'llm_tokens_total',
            'LLM Token 消耗总量',
            ['model', 'token_type']
        )
        
        # Agent 监控指标
        self.agent_runs_total = Counter(
            'agent_runs_total',
            'Agent 执行总次数',
            ['agent_type']
        )
        
        self.agent_success_total = Counter(
            'agent_success_total',
            'Agent 执行成功次数',
            ['agent_type']
        )
        
        self.agent_errors_total = Counter(
            'agent_errors_total',
            'Agent 执行失败次数',
            ['agent_type', 'error_type']
        )
        
        self.agent_latency_seconds = Histogram(
            'agent_latency_seconds',
            'Agent 执行延迟（秒）',
            ['agent_type'],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0]
        )
        
        self.agent_steps_total = Counter(
            'agent_steps_total',
            'Agent 步骤执行总数',
            ['agent_type']
        )
        
        self.agent_retries_total = Counter(
            'agent_retries_total',
            'Agent 重试次数',
            ['agent_type']
        )
        
        # Task Router 监控指标
        self.task_routing_total = Counter(
            'task_routing_total',
            '任务路由总次数',
            ['routing_method']
        )
        
        self.task_routing_time_seconds = Histogram(
            'task_routing_time_seconds',
            '路由耗时（秒）',
            ['routing_method'],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]
        )
        
        self.task_distribution_total = Counter(
            'task_distribution_total',
            '任务分配总数',
            ['task_type']
        )
        
        # NL2SQL 监控指标
        self.nl2sql_queries_total = Counter(
            'nl2sql_queries_total',
            'NL2SQL 查询总次数'
        )
        
        self.nl2sql_success_total = Counter(
            'nl2sql_success_total',
            'SQL 生成成功次数'
        )
        
        self.nl2sql_errors_total = Counter(
            'nl2sql_errors_total',
            'SQL 生成失败次数',
            ['error_type']
        )
        
        self.nl2sql_safety_rejects_total = Counter(
            'nl2sql_safety_rejects_total',
            'SQL 安全拒绝次数'
        )
        
        self.nl2sql_latency_seconds = Histogram(
            'nl2sql_latency_seconds',
            'SQL 生成延迟（秒）',
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
        )
        
        self.nl2sql_correction_retries = Counter(
            'nl2sql_correction_retries',
            'SQL 自动修正重试次数'
        )
        
        # RAG 监控指标
        self.rag_queries_total = Counter(
            'rag_queries_total',
            'RAG 查询总次数'
        )
        
        self.rag_success_total = Counter(
            'rag_success_total',
            'RAG 查询成功次数'
        )
        
        self.rag_clarifications_total = Counter(
            'rag_clarifications_total',
            'RAG 追问次数'
        )
        
        self.rag_confidence_score = Histogram(
            'rag_confidence_score',
            'RAG 置信度评分',
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        )
        
        self.rag_latency_seconds = Histogram(
            'rag_latency_seconds',
            'RAG 查询延迟（秒）',
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
        )
        
        self.rag_retrieval_count = Histogram(
            'rag_retrieval_count',
            '检索文档数量',
            buckets=[0, 1, 2, 3, 5, 10, 20, 50]
        )
        
        # Tool 监控指标
        self.tool_calls_total = Counter(
            'tool_calls_total',
            '工具调用总次数',
            ['tool_name']
        )
        
        self.tool_success_total = Counter(
            'tool_success_total',
            '工具调用成功次数',
            ['tool_name']
        )
        
        self.tool_errors_total = Counter(
            'tool_errors_total',
            '工具调用失败次数',
            ['tool_name', 'error_type']
        )
        
        self.tool_latency_seconds = Histogram(
            'tool_latency_seconds',
            '工具调用延迟（秒）',
            ['tool_name'],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]
        )
        
        # 系统监控指标
        self.http_requests_total = Counter(
            'http_requests_total',
            'HTTP 请求总次数',
            ['method', 'endpoint', 'status']
        )
        
        self.http_request_duration_seconds = Histogram(
            'http_request_duration_seconds',
            'HTTP 请求延迟（秒）',
            ['method', 'endpoint'],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]
        )
        
        self.active_sessions = Gauge(
            'active_sessions',
            '活跃会话数'
        )
        
        self.token_refresh_total = Counter(
            'token_refresh_total',
            'Token 刷新次数'
        )
        
        self.token_expired_total = Counter(
            'token_expired_total',
            'Token 过期次数'
        )
        
        # 应用信息
        self.app_info = Info(
            'shop_ai_service',
            'ShopCopilot AI Service 信息'
        )
        
        self._initialized = True
        logger.info("监控指标初始化完成")
    
    def start_metrics_server(self, port: int = 8000):
        """启动 Prometheus 指标服务器"""
        start_http_server(port)
        logger.info(f"监控指标服务器已启动，端口: {port}")
    
    def record_llm_call(
        self,
        model: str,
        success: bool,
        latency: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        error_type: Optional[str] = None
    ):
        """记录 LLM 调用指标"""
        self.llm_calls_total.labels(model=model).inc()
        
        if success:
            self.llm_success_total.labels(model=model).inc()
        else:
            self.llm_errors_total.labels(model=model, error_type=error_type or "unknown").inc()
        
        self.llm_latency_seconds.labels(model=model).observe(latency)
        
        if prompt_tokens > 0:
            self.llm_tokens_total.labels(model=model, token_type="prompt").inc(prompt_tokens)
        
        if completion_tokens > 0:
            self.llm_tokens_total.labels(model=model, token_type="completion").inc(completion_tokens)
    
    def record_agent_run(
        self,
        agent_type: str,
        success: bool,
        latency: float,
        steps: int = 0,
        retries: int = 0,
        error_type: Optional[str] = None
    ):
        """记录 Agent 执行指标"""
        self.agent_runs_total.labels(agent_type=agent_type).inc()
        
        if success:
            self.agent_success_total.labels(agent_type=agent_type).inc()
        else:
            self.agent_errors_total.labels(agent_type=agent_type, error_type=error_type or "unknown").inc()
        
        self.agent_latency_seconds.labels(agent_type=agent_type).observe(latency)
        
        if steps > 0:
            self.agent_steps_total.labels(agent_type=agent_type).inc(steps)
        
        if retries > 0:
            self.agent_retries_total.labels(agent_type=agent_type).inc(retries)
    
    def record_task_routing(
        self,
        routing_method: str,
        latency: float,
        task_type: Optional[str] = None
    ):
        """记录任务路由指标"""
        self.task_routing_total.labels(routing_method=routing_method).inc()
        self.task_routing_time_seconds.labels(routing_method=routing_method).observe(latency)
        
        if task_type:
            self.task_distribution_total.labels(task_type=task_type).inc()
    
    def record_nl2sql(
        self,
        success: bool,
        latency: float,
        safety_reject: bool = False,
        correction_retries: int = 0,
        error_type: Optional[str] = None
    ):
        """记录 NL2SQL 指标"""
        self.nl2sql_queries_total.inc()
        
        if success:
            self.nl2sql_success_total.inc()
        else:
            self.nl2sql_errors_total.labels(error_type=error_type or "unknown").inc()
        
        if safety_reject:
            self.nl2sql_safety_rejects_total.inc()
        
        if correction_retries > 0:
            self.nl2sql_correction_retries.inc(correction_retries)
        
        self.nl2sql_latency_seconds.observe(latency)
    
    def record_rag(
        self,
        success: bool,
        latency: float,
        confidence: float = 0.0,
        retrieval_count: int = 0,
        clarification: bool = False
    ):
        """记录 RAG 指标"""
        self.rag_queries_total.inc()
        
        if success:
            self.rag_success_total.inc()
        
        if clarification:
            self.rag_clarifications_total.inc()
        
        if confidence > 0:
            self.rag_confidence_score.observe(confidence)
        
        if retrieval_count > 0:
            self.rag_retrieval_count.observe(retrieval_count)
        
        self.rag_latency_seconds.observe(latency)
    
    def record_tool_call(
        self,
        tool_name: str,
        success: bool,
        latency: float,
        error_type: Optional[str] = None
    ):
        """记录工具调用指标"""
        self.tool_calls_total.labels(tool_name=tool_name).inc()
        
        if success:
            self.tool_success_total.labels(tool_name=tool_name).inc()
        else:
            self.tool_errors_total.labels(tool_name=tool_name, error_type=error_type or "unknown").inc()
        
        self.tool_latency_seconds.labels(tool_name=tool_name).observe(latency)
    
    def record_http_request(
        self,
        method: str,
        endpoint: str,
        status: str,
        duration: float
    ):
        """记录 HTTP 请求指标"""
        self.http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status=status
        ).inc()
        
        self.http_request_duration_seconds.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration)
    
    def update_active_sessions(self, count: int):
        """更新活跃会话数"""
        self.active_sessions.set(count)
    
    def record_token_refresh(self):
        """记录 Token 刷新"""
        self.token_refresh_total.inc()
    
    def record_token_expired(self):
        """记录 Token 过期"""
        self.token_expired_total.inc()
    
    def set_app_info(self, version: str, environment: str):
        """设置应用信息"""
        self.app_info.info({
            "version": version,
            "environment": environment
        })


# 全局指标收集器实例
metrics = MetricsCollector()


def get_metrics() -> MetricsCollector:
    """获取指标收集器实例"""
    if not metrics._initialized:
        metrics.initialize()
    return metrics
