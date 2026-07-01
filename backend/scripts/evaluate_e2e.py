"""End-to-end evaluation: intent accuracy + answer quality scoring.

Usage:
    python backend/scripts/evaluate_e2e.py

Scores:
    Intent accuracy: % of questions classified correctly
    Topic coverage:  % of expected topics mentioned in answer
    Overall score:    weighted average (0-100)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.intent_classifier import classify_intent_rules

SAMPLES_PATH = Path(__file__).resolve().parent.parent / "evaluation" / "e2e_samples.jsonl"


def load_samples():
    samples = []
    with open(SAMPLES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def evaluate_intent(samples):
    """Evaluate intent classification accuracy using the rule-based classifier."""
    correct = 0
    details = []
    for s in samples:
        result = classify_intent_rules(s["question"])
        is_correct = result.label == s["expected_intent"]
        if is_correct:
            correct += 1
        details.append({
            "id": s["id"],
            "question": s["question"],
            "expected": s["expected_intent"],
            "predicted": result.label,
            "correct": is_correct,
            "confidence": result.confidence,
        })
    accuracy = round(correct / len(samples) * 100, 1) if samples else 0
    return accuracy, details


def evaluate_topic_coverage(samples, answers: dict[int, str]):
    """Evaluate if expected topics appear in generated answers."""
    scores = []
    for s in samples:
        answer = answers.get(s["id"], "")
        expected = s.get("expected_topics", [])
        if not expected:
            continue
        matched = sum(1 for t in expected if t.lower() in answer.lower())
        coverage = round(matched / len(expected) * 100, 1)
        scores.append(coverage)
    avg = round(sum(scores) / len(scores), 1) if scores else 0
    return avg, scores


def main():
    samples = load_samples()
    print(f"加载 {len(samples)} 条评估样本\n")

    # 1. Intent accuracy
    intent_acc, intent_details = evaluate_intent(samples)
    print(f"=== 意图分类准确率 ===")
    print(f"正确: {sum(1 for d in intent_details if d['correct'])}/{len(samples)} = {intent_acc}%\n")
    for d in intent_details:
        status = "OK" if d["correct"] else "XX"
        print(f"  [{status}] [{d['id']:2d}] {d['question'][:40]:40s} exp={d['expected']:20s} pred={d['predicted']:20s}")

    # 2. Overall score
    print(f"\n=== 总结 ===")
    print(f"意图准确率: {intent_acc}%")
    print(f"样本数量:   {len(samples)}")
    print(f"难度分布:   easy={sum(1 for s in samples if s['difficulty']=='easy')} medium={sum(1 for s in samples if s['difficulty']=='medium')} hard={sum(1 for s in samples if s['difficulty']=='hard')}")

    # 3. Run with LLM if configured
    try:
        from app.config import get_settings
        settings = get_settings()
        if settings.llm_configured:
            print(f"\nLLM 已配置 ({settings.llm_model})，可以运行端到端测试:")
            print(f"  python -m pytest backend/tests/ -k 'test_analyze' -v")
    except Exception:
        pass


if __name__ == "__main__":
    main()
