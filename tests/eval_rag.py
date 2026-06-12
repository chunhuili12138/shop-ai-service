"""
RAGAS评估脚本
用于评估RAG系统的质量

评估指标：
1. Faithfulness（忠实度）：回答是否基于检索内容
2. Answer Relevancy（答案相关性）：回答是否与问题相关
3. Context Precision（上下文精度）：检索文档的精准度
4. Context Recall（上下文召回）：相关信息是否被检索到
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional


# ==================== 评估数据集 ====================

# 测试数据集（question, answer, contexts, ground_truth）
EVAL_DATASET = [
    {
        "question": "周卡多少钱？",
        "answer": "周卡价格是298元，有效期7天，不限次数。",
        "contexts": ["周卡价格为298元，有效期7天，不限次数。"],
        "ground_truth": "298元"
    },
    {
        "question": "月卡包含什么？",
        "answer": "月卡价格698元，有效期30天，不限次数，生日当天免费。",
        "contexts": ["月卡价格为698元，有效期30天，不限次数，生日当天免费。"],
        "ground_truth": "698元，30天，不限次数"
    },
    {
        "question": "可以退款吗？",
        "answer": "购买后7天内未使用可申请全额退款。",
        "contexts": ["购买后7天内未使用可申请全额退款。"],
        "ground_truth": "7天内未使用可全额退款"
    },
    {
        "question": "你们几点开门？",
        "answer": "我们周一至周日营业，时间为9:00-21:00。",
        "contexts": ["营业时间：周一至周日 9:00-21:00"],
        "ground_truth": "9:00-21:00"
    },
    {
        "question": "儿童有年龄限制吗？",
        "answer": "适合3-12岁儿童，需家长陪同。",
        "contexts": ["适合3-12岁儿童，需家长陪同。"],
        "ground_truth": "3-12岁，需家长陪同"
    },
    {
        "question": "有什么套餐？",
        "answer": "我们有单次体验卡、周卡、月卡等套餐。",
        "contexts": ["套餐包括单次体验卡、周卡、月卡。"],
        "ground_truth": "单次体验卡、周卡、月卡"
    },
    {
        "question": "地址在哪里？",
        "answer": "地址是XX市XX区XX路100号。",
        "contexts": ["地址：XX市XX区XX路100号"],
        "ground_truth": "XX市XX区XX路100号"
    },
    {
        "question": "联系电话是多少？",
        "answer": "联系电话是400-123-4567。",
        "contexts": ["联系电话：400-123-4567"],
        "ground_truth": "400-123-4567"
    },
]


# ==================== 评估函数 ====================

def evaluate_faithfulness(answer: str, contexts: list[str]) -> float:
    """
    评估忠实度：回答是否基于检索内容
    
    简化版本：计算回答中的关键词在上下文中出现的比例
    """
    if not contexts or not answer:
        return 0.0
    
    context_text = " ".join(contexts)
    
    # 提取回答中的关键词（简单分词）
    answer_words = set(answer.replace("，", " ").replace("。", " ").split())
    
    # 计算关键词在上下文中出现的比例
    if not answer_words:
        return 0.0
    
    matched = sum(1 for word in answer_words if word in context_text)
    
    return matched / len(answer_words)


def evaluate_answer_relevancy(answer: str, question: str) -> float:
    """
    评估答案相关性：回答是否与问题相关
    
    简化版本：计算问题中的关键词在回答中出现的比例
    """
    if not answer or not question:
        return 0.0
    
    # 提取问题中的关键词
    question_words = set(question.replace("？", " ").replace("吗", " ").split())
    
    if not question_words:
        return 0.0
    
    # 计算关键词在回答中出现的比例
    matched = sum(1 for word in question_words if word in answer)
    
    return matched / len(question_words)


def evaluate_context_precision(contexts: list[str], ground_truth: str) -> float:
    """
    评估上下文精度：检索文档的精准度
    
    简化版本：计算ground_truth在上下文中出现的比例
    """
    if not contexts or not ground_truth:
        return 0.0
    
    context_text = " ".join(contexts)
    
    # 检查ground_truth的关键信息是否在上下文中
    gt_words = set(ground_truth.replace("，", " ").replace("、", " ").split())
    
    if not gt_words:
        return 0.0
    
    matched = sum(1 for word in gt_words if word in context_text)
    
    return matched / len(gt_words)


def evaluate_context_recall(contexts: list[str], ground_truth: str) -> float:
    """
    评估上下文召回：相关信息是否被检索到
    
    简化版本：与context_precision类似
    """
    return evaluate_context_precision(contexts, ground_truth)


# ==================== 评估脚本 ====================

def run_evaluation(dataset: list[dict] = None) -> dict:
    """
    运行RAGAS评估
    
    Args:
        dataset: 评估数据集，默认使用内置数据集
    
    Returns:
        评估结果
    """
    if dataset is None:
        dataset = EVAL_DATASET
    
    results = []
    total_faithfulness = 0
    total_relevancy = 0
    total_precision = 0
    total_recall = 0
    
    for i, item in enumerate(dataset):
        question = item["question"]
        answer = item["answer"]
        contexts = item["contexts"]
        ground_truth = item["ground_truth"]
        
        # 计算各项指标
        faithfulness = evaluate_faithfulness(answer, contexts)
        relevancy = evaluate_answer_relevancy(answer, question)
        precision = evaluate_context_precision(contexts, ground_truth)
        recall = evaluate_context_recall(contexts, ground_truth)
        
        total_faithfulness += faithfulness
        total_relevancy += relevancy
        total_precision += precision
        total_recall += recall
        
        results.append({
            "question": question,
            "answer": answer,
            "metrics": {
                "faithfulness": round(faithfulness, 3),
                "answer_relevancy": round(relevancy, 3),
                "context_precision": round(precision, 3),
                "context_recall": round(recall, 3),
            }
        })
        
        print(f"[RAGAS] 问题{i+1}: {question}")
        print(f"  - 忠实度: {faithfulness:.3f}")
        print(f"  - 相关性: {relevancy:.3f}")
        print(f"  - 精度: {precision:.3f}")
        print(f"  - 召回: {recall:.3f}")
    
    # 计算平均值
    n = len(dataset)
    summary = {
        "total_samples": n,
        "average_metrics": {
            "faithfulness": round(total_faithfulness / n, 3),
            "answer_relevancy": round(total_relevancy / n, 3),
            "context_precision": round(total_precision / n, 3),
            "context_recall": round(total_recall / n, 3),
        },
        "timestamp": datetime.now().isoformat(),
    }
    
    print("\n" + "="*50)
    print("[RAGAS] 评估完成")
    print(f"平均忠实度: {summary['average_metrics']['faithfulness']:.3f}")
    print(f"平均相关性: {summary['average_metrics']['answer_relevancy']:.3f}")
    print(f"平均精度: {summary['average_metrics']['context_precision']:.3f}")
    print(f"平均召回: {summary['average_metrics']['context_recall']:.3f}")
    print("="*50)
    
    return {
        "summary": summary,
        "details": results,
    }


def save_evaluation_report(results: dict, output_dir: str = "data/evaluation"):
    """
    保存评估报告
    
    Args:
        results: 评估结果
        output_dir: 输出目录
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 保存JSON报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = output_path / f"ragas_report_{timestamp}.json"
    
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"[RAGAS] 评估报告已保存: {report_file}")
    
    return str(report_file)


# ==================== 主函数 ====================

if __name__ == "__main__":
    print("开始RAGAS评估...")
    results = run_evaluation()
    report_path = save_evaluation_report(results)
    print(f"评估完成，报告保存在: {report_path}")
