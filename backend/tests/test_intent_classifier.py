import json
from pathlib import Path

from app.services.intent_classifier import classify_intent_rules


def test_rule_intent_classifier_reaches_target_accuracy() -> None:
    sample_path = Path(__file__).resolve().parents[1] / "evaluation" / "intent_samples.jsonl"
    samples = [json.loads(line) for line in sample_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    correct = 0
    for item in samples:
        result = classify_intent_rules(item["question"])
        correct += int(result.label == item["label"])

    assert correct / len(samples) >= 0.9


def test_intent_classifier_returns_confidence() -> None:
    result = classify_intent_rules("为什么华东销售额突然下降")

    assert result.label == "anomaly_attribution"
    assert 0 <= result.confidence <= 1
    assert result.display_name == "异常归因"
