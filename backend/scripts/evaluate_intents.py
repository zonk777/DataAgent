from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.intent_classifier import classify_intent, classify_intent_rules  # noqa: E402


def load_samples(path: Path) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        samples.append({"question": item["question"], "label": item["label"]})
    return samples


async def evaluate(samples: list[dict[str, str]], use_llm: bool) -> dict[str, Any]:
    rows = []
    correct = 0
    for item in samples:
        if use_llm:
            result = await classify_intent(item["question"])
        else:
            result = classify_intent_rules(item["question"])
        ok = result.label == item["label"]
        correct += int(ok)
        rows.append(
            {
                "question": item["question"],
                "expected": item["label"],
                "predicted": result.label,
                "confidence": result.confidence,
                "method": result.method,
                "ok": ok,
            }
        )
    accuracy = correct / len(samples) if samples else 0
    return {"total": len(samples), "correct": correct, "accuracy": accuracy, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate DataAgent intent classification accuracy.")
    parser.add_argument(
        "--samples",
        default=str(ROOT / "evaluation" / "intent_samples.jsonl"),
        help="JSONL file with question/label records.",
    )
    parser.add_argument("--llm", action="store_true", help="Use configured LLM few-shot classifier instead of local rules.")
    parser.add_argument("--min-accuracy", type=float, default=0.9)
    args = parser.parse_args()

    samples = load_samples(Path(args.samples))
    result = asyncio.run(evaluate(samples, use_llm=args.llm))
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))
    failures = [row for row in result["rows"] if not row["ok"]]
    if failures:
        print("\n失败样例：")
        for row in failures:
            print(f"- {row['question']} expected={row['expected']} predicted={row['predicted']} conf={row['confidence']}")
    if result["accuracy"] < args.min_accuracy:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
