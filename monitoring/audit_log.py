"""
审计日志模块
记录 Agent 执行过程，生成结构化审计日志
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict


@dataclass
class ToolCallLog:
    """工具调用日志"""
    tool_name: str
    args: Dict[str, Any]
    result: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
    duration_ms: float = 0


@dataclass
class AuditLog:
    """审计日志"""
    trace_id: str
    question: str
    shop_id: int
    user_id: int
    role: str
    start_time: str
    end_time: Optional[str] = None
    total_duration_ms: float = 0
    iterations: int = 0
    tool_calls: List[ToolCallLog] = field(default_factory=list)
    answer: Optional[str] = None
    is_reliable: bool = False
    model_used: str = ""
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class AuditLogger:
    """
    审计日志记录器
    
    功能：
    1. 记录 Agent 执行过程
    2. 记录工具调用详情
    3. 生成结构化审计日志
    4. 支持日志持久化
    """
    
    def __init__(self, log_dir: str = "data/audit_logs"):
        """
        初始化审计日志记录器
        
        Args:
            log_dir: 日志存储目录
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_log: Optional[AuditLog] = None
    
    def start_trace(
        self,
        trace_id: str,
        question: str,
        shop_id: int,
        user_id: int = 0,
        role: str = "guest",
        metadata: Dict[str, Any] = None,
    ) -> AuditLog:
        """
        开始新的追踪
        
        Args:
            trace_id: 追踪ID
            question: 用户问题
            shop_id: 店铺ID
            user_id: 用户ID
            role: 用户角色
            metadata: 额外元数据
        
        Returns:
            AuditLog 实例
        """
        self._current_log = AuditLog(
            trace_id=trace_id,
            question=question,
            shop_id=shop_id,
            user_id=user_id,
            role=role,
            start_time=datetime.now().isoformat(),
            metadata=metadata or {},
        )
        
        print(f"[审计日志] 开始追踪: {trace_id}")
        return self._current_log
    
    def log_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None,
        duration_ms: float = 0,
    ):
        """
        记录工具调用
        
        Args:
            tool_name: 工具名称
            args: 工具参数
            result: 调用结果
            success: 是否成功
            error: 错误信息
            duration_ms: 执行耗时（毫秒）
        """
        if self._current_log is None:
            return
        
        tool_log = ToolCallLog(
            tool_name=tool_name,
            args=args,
            result=result[:500] if result else None,  # 截断过长结果
            success=success,
            error=error,
            duration_ms=duration_ms,
        )
        
        self._current_log.tool_calls.append(tool_log)
        self._current_log.iterations += 1
        
        status = "✓" if success else "✗"
        print(f"[审计日志] 工具调用: {status} {tool_name} ({duration_ms:.0f}ms)")
    
    def end_trace(
        self,
        answer: str = None,
        is_reliable: bool = False,
        model_used: str = "",
        error: str = None,
    ) -> AuditLog:
        """
        结束追踪
        
        Args:
            answer: 最终回答
            is_reliable: 回答是否可靠
            model_used: 使用的模型
            error: 错误信息
        
        Returns:
            完成的 AuditLog
        """
        if self._current_log is None:
            return None
        
        self._current_log.end_time = datetime.now().isoformat()
        self._current_log.answer = answer
        self._current_log.is_reliable = is_reliable
        self._current_log.model_used = model_used
        self._current_log.error = error
        
        # 计算总耗时
        start = datetime.fromisoformat(self._current_log.start_time)
        end = datetime.fromisoformat(self._current_log.end_time)
        self._current_log.total_duration_ms = (end - start).total_seconds() * 1000
        
        print(f"[审计日志] 追踪完成: {self._current_log.trace_id} ({self._current_log.total_duration_ms:.0f}ms)")
        
        # 持久化日志
        self._save_log(self._current_log)
        
        log = self._current_log
        self._current_log = None
        return log
    
    def _save_log(self, log: AuditLog):
        """
        保存日志到文件
        
        Args:
            log: 审计日志
        """
        try:
            # 按日期分目录
            date_str = datetime.now().strftime("%Y%m%d")
            date_dir = self.log_dir / date_str
            date_dir.mkdir(parents=True, exist_ok=True)
            
            # 文件名：{trace_id}.json
            file_path = date_dir / f"{log.trace_id}.json"
            file_path.write_text(log.to_json(), encoding="utf-8")
            
            print(f"[审计日志] 已保存: {file_path}")
        except Exception as e:
            print(f"[审计日志] 保存失败: {str(e)}")
    
    def get_current_log(self) -> Optional[AuditLog]:
        """获取当前追踪日志"""
        return self._current_log


# 全局实例
_audit_logger = None


def get_audit_logger() -> AuditLogger:
    """获取审计日志记录器单例"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
