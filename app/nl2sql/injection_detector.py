"""
SQL 注入检测模块
深度检测各种 SQL 注入攻击模式
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


class InjectionType(Enum):
    """注入类型"""
    UNION = "union_injection"           # UNION 注入
    TIME_BASED = "time_based"           # 时间盲注
    BOOLEAN_BASED = "boolean_based"     # 布尔盲注
    ERROR_BASED = "error_based"         # 报错注入
    STACKED = "stacked_queries"         # 堆叠查询
    BLIND = "blind_injection"           # 盲注
    ENCODING = "encoding_bypass"        # 编码绕过
    COMMENT = "comment_bypass"          # 注释绕过
    LOGIC = "logic_manipulation"        # 逻辑操纵


@dataclass
class InjectionDetection:
    """注入检测结果"""
    injection_type: InjectionType
    pattern: str
    description: str
    severity: str  # high, medium, low
    location: Optional[str] = None  # 在 SQL 中的位置


@dataclass
class InjectionReport:
    """注入检测报告"""
    is_safe: bool
    detections: List[InjectionDetection] = field(default_factory=list)
    risk_score: int = 0  # 0-100 风险分数
    
    @property
    def has_injections(self) -> bool:
        return len(self.detections) > 0
    
    @property
    def high_risk_count(self) -> int:
        return sum(1 for d in self.detections if d.severity == "high")
    
    def to_dict(self) -> Dict:
        return {
            "is_safe": self.is_safe,
            "risk_score": self.risk_score,
            "detection_count": len(self.detections),
            "high_risk_count": self.high_risk_count,
            "detections": [
                {
                    "type": d.injection_type.value,
                    "pattern": d.pattern,
                    "description": d.description,
                    "severity": d.severity
                }
                for d in self.detections
            ]
        }


class InjectionDetector:
    """SQL 注入检测器"""
    
    # UNION 注入模式
    UNION_PATTERNS = [
        (r'UNION\s+(ALL\s+)?SELECT', "UNION SELECT 语句", "high"),
        (r'UNION\s+(ALL\s+)?\d+\s*,', "UNION 数字列注入", "high"),
        (r'UNION\s+(ALL\s+)?SELECT\s+NULL', "UNION NULL 注入", "high"),
        (r'UNION\s+(ALL\s+)?SELECT\s+["\']', "UNION 字符串注入", "high"),
    ]
    
    # 时间盲注模式
    TIME_BASED_PATTERNS = [
        (r'SLEEP\s*\(\s*\d+\s*\)', "SLEEP 时间延迟", "high"),
        (r'BENCHMARK\s*\(\s*\d+', "BENCHMARK 时间延迟", "high"),
        (r'WAITFOR\s+DELAY', "WAITFOR 延迟（SQL Server）", "high"),
        (r'PG_SLEEP\s*\(', "PG_SLEEP 延迟（PostgreSQL）", "high"),
        (r'RAND\s*\(\s*\)\s*\*\s*\d+', "随机数延迟", "medium"),
    ]
    
    # 布尔盲注模式
    BOOLEAN_BASED_PATTERNS = [
        (r'AND\s+\d+\s*=\s*\d+', "布尔条件 AND", "medium"),
        (r'OR\s+\d+\s*=\s*\d+', "布尔条件 OR", "medium"),
        (r'AND\s+["\']?\w+["\']?\s*=\s*["\']?\w+["\']?', "字符串布尔条件", "medium"),
        (r'OR\s+["\']?\w+["\']?\s*=\s*["\']?\w+["\']?', "字符串布尔条件", "medium"),
        (r'IF\s*\(\s*\d+\s*=\s*\d+', "IF 条件判断", "high"),
        (r'CASE\s+WHEN\s+\d+\s*=\s*\d+', "CASE 条件判断", "high"),
    ]
    
    # 报错注入模式
    ERROR_BASED_PATTERNS = [
        (r'EXTRACTVALUE\s*\(', "EXTRACTVALUE 报错注入", "high"),
        (r'UPDATEXML\s*\(', "UPDATEXML 报错注入", "high"),
        (r'FLOOR\s*\(\s*RAND\s*\(\s*\)\s*\)', "FLOOR RAND 报错注入", "high"),
        (r'COUNT\s*\(\s*\*\s*\)\s*,\s*FLOOR', "COUNT FLOOR 报错注入", "high"),
        (r'DUPLICATE\s+KEY\s+UPDATE', "DUPLICATE KEY 报错注入", "high"),
        (r'GTID_SUBSET\s*\(', "GTID_SUBSET 报错注入", "high"),
        (r'GTID_SUBTRACT\s*\(', "GTID_SUBTRACT 报错注入", "high"),
    ]
    
    # 堆叠查询模式
    STACKED_PATTERNS = [
        (r';\s*(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)', "堆叠查询", "high"),
        (r';\s*EXEC\s*\(', "EXEC 堆叠执行", "high"),
        (r';\s*EXECUTE\s+', "EXECUTE 堆叠执行", "high"),
        (r';\s*DECLARE\s+', "DECLARE 堆叠声明", "high"),
    ]
    
    # 编码绕过模式
    ENCODING_PATTERNS = [
        (r'0x[0-9a-fA-F]{10,}', "HEX 编码（长序列）", "medium"),
        (r'CHAR\s*\(\s*\d+(\s*,\s*\d+)+\s*\)', "CHAR 函数编码", "high"),
        (r'CONVERT\s*\(\s*USING\s+', "字符集转换", "medium"),
        (r'CONVERT\s*\(\s*.*\s+USING\s+', "字符集转换", "medium"),
        (r'UNHEX\s*\(', "UNHEX 解码", "high"),
    ]
    
    # 注释绕过模式
    COMMENT_PATTERNS = [
        (r'/\*!.*?\*/', "MySQL 特殊注释", "medium"),
        (r'/\*\s*OR\s+\d+\s*=\s*\d+\s*\*/', "注释内 OR 条件", "high"),
        (r'/\*\s*UNION\s+SELECT\s*\*/', "注释内 UNION", "high"),
        (r'--\s*$', "行注释（可能用于截断）", "low"),
        (r'#\s*$', "行注释（可能用于截断）", "low"),
    ]
    
    # 逻辑操纵模式
    LOGIC_PATTERNS = [
        (r'OR\s+1\s*=\s*1', "恒真条件 OR 1=1", "high"),
        (r'OR\s+["\']?\w+["\']?\s*!=\s*["\']?\w+["\']?', "不等条件", "medium"),
        (r'OR\s+\d+\s*>\s*0', "恒真条件 OR n>0", "high"),
        (r'AND\s+1\s*=\s*1', "恒真条件 AND 1=1", "medium"),
        (r'AND\s+1\s*=\s*2', "恒假条件 AND 1=2", "medium"),
        (r'WHERE\s+\d+\s*=\s*\d+', "恒等条件 WHERE n=n", "medium"),
    ]
    
    def __init__(self):
        # 编译所有模式
        self._patterns = []
        pattern_groups = [
            (self.UNION_PATTERNS, InjectionType.UNION),
            (self.TIME_BASED_PATTERNS, InjectionType.TIME_BASED),
            (self.BOOLEAN_BASED_PATTERNS, InjectionType.BOOLEAN_BASED),
            (self.ERROR_BASED_PATTERNS, InjectionType.ERROR_BASED),
            (self.STACKED_PATTERNS, InjectionType.STACKED),
            (self.ENCODING_PATTERNS, InjectionType.ENCODING),
            (self.COMMENT_PATTERNS, InjectionType.COMMENT),
            (self.LOGIC_PATTERNS, InjectionType.LOGIC),
        ]
        
        for patterns, injection_type in pattern_groups:
            for pattern, description, severity in patterns:
                compiled = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                self._patterns.append((compiled, injection_type, description, severity))
    
    def detect(self, sql: str) -> InjectionReport:
        """
        检测 SQL 注入
        
        Args:
            sql: SQL 语句
        
        Returns:
            检测报告
        """
        report = InjectionReport(is_safe=True)
        
        for pattern, injection_type, description, severity in self._patterns:
            matches = pattern.finditer(sql)
            for match in matches:
                detection = InjectionDetection(
                    injection_type=injection_type,
                    pattern=match.group(),
                    description=description,
                    severity=severity,
                    location=f"位置 {match.start()}-{match.end()}"
                )
                report.detections.append(detection)
        
        # 计算风险分数
        report.risk_score = self._calculate_risk_score(report.detections)
        
        # 判断是否安全
        report.is_safe = report.risk_score < 50 and report.high_risk_count == 0
        
        return report
    
    def _calculate_risk_score(self, detections: List[InjectionDetection]) -> int:
        """
        计算风险分数
        
        Args:
            detections: 检测结果列表
        
        Returns:
            风险分数 0-100
        """
        if not detections:
            return 0
        
        score = 0
        severity_scores = {
            "high": 30,
            "medium": 15,
            "low": 5
        }
        
        for detection in detections:
            score += severity_scores.get(detection.severity, 10)
        
        # 限制在 0-100
        return min(score, 100)
    
    def get_mitigation_advice(self, detections: List[InjectionDetection]) -> List[str]:
        """
        获取缓解建议
        
        Args:
            detections: 检测结果列表
        
        Returns:
            建议列表
        """
        advice = []
        
        injection_types = set(d.injection_type for d in detections)
        
        if InjectionType.UNION in injection_types:
            advice.append("避免使用 UNION 查询，或确保 UNION 两侧的列数和类型匹配")
        
        if InjectionType.TIME_BASED in injection_types:
            advice.append("移除时间延迟函数（SLEEP, BENCHMARK），这些可能被用于时间盲注")
        
        if InjectionType.BOOLEAN_BASED in injection_types:
            advice.append("检查 WHERE 条件中的布尔表达式，避免恒真/恒假条件")
        
        if InjectionType.ERROR_BASED in injection_types:
            advice.append("移除报错注入函数（EXTRACTVALUE, UPDATEXML），这些可用于信息泄露")
        
        if InjectionType.STACKED in injection_types:
            advice.append("禁止堆叠查询，只允许单条 SELECT 语句")
        
        if InjectionType.ENCODING in injection_types:
            advice.append("检查编码函数调用，这些可能用于绕过检测")
        
        if InjectionType.COMMENT in injection_types:
            advice.append("移除 SQL 注释，注释可能被用于截断或绕过")
        
        if InjectionType.LOGIC in injection_types:
            advice.append("检查逻辑条件，避免恒真/恒假条件（如 OR 1=1）")
        
        return advice


# 全局实例
injection_detector = InjectionDetector()


def detect_injection(sql: str) -> Dict:
    """
    检测 SQL 注入（API 接口）
    
    Args:
        sql: SQL 语句
    
    Returns:
        检测报告字典
    """
    report = injection_detector.detect(sql)
    return report.to_dict()


def get_injection_report(sql: str) -> InjectionReport:
    """
    获取注入检测报告
    
    Args:
        sql: SQL 语句
    
    Returns:
        InjectionReport 对象
    """
    return injection_detector.detect(sql)
