from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import connect, initialize_database  # noqa: E402
from app.services.analyzer import _build_query, _dataset  # noqa: E402
from app.services.security import validate_readonly_sql  # noqa: E402


def load_samples(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    initialize_database()
    dataset = _dataset(1)
    rows = []
    correct = 0
    for item in samples:
        try:
            plan = _build_query(item["question"], dataset, 500)
            sql = validate_readonly_sql(plan.sql, dataset["table_name"])
            with connect() as conn:
                result = [dict(row) for row in conn.execute(sql, plan.params).fetchall()]
            searchable_text = f"{sql} {' '.join(str(param) for param in plan.params)}".lower()
            contains_ok = all(token.lower() in searchable_text for token in item.get("must_contain", []))
            rows_ok = len(result) >= int(item.get("min_rows", 1))
            ok = contains_ok and rows_ok
        except Exception as exc:
            sql = ""
            result = []
            ok = False
            rows.append({"question": item["question"], "ok": False, "error": str(exc)})
            continue
        correct += int(ok)
        rows.append({"question": item["question"], "ok": ok, "sql": sql, "row_count": len(result)})
    accuracy = correct / len(samples) if samples else 0
    return {"total": len(samples), "correct": correct, "accuracy": accuracy, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate DataAgent SQL generation accuracy.")
    parser.add_argument("--samples", default=str(ROOT / "evaluation" / "sql_samples.jsonl"))
    parser.add_argument("--min-accuracy", type=float, default=0.85)
    args = parser.parse_args()
    result = evaluate(load_samples(Path(args.samples)))
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False, indent=2))
    failures = [row for row in result["rows"] if not row["ok"]]
    if failures:
        print("\n失败样例：")
        for row in failures:
            print(f"- {row['question']} rows={row.get('row_count')} error={row.get('error', '')}")
            if row.get("sql"):
                print(f"  SQL: {row['sql']}")
    if result["accuracy"] < args.min_accuracy:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
