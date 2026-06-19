"""
Evaluation harness.

Before you switch routing_mode from suggest to enforce, you need to know whether
the classifier is good enough. This runs the model over a labeled CSV and
reports accuracy overall and per category, plus how many tickets clear the
confidence threshold (auto-route coverage) and how accurate those are.

Input CSV needs two columns:
    support_ticket_text   the ticket
    expected_category     the correct category label (must match a Category value)

Usage:
    python scripts/evaluate.py labeled_tickets.csv

Calls Vertex AI; needs GOOGLE_CLOUD_PROJECT set and ADC configured. Does not
touch ServiceNow.
"""

import argparse
import asyncio
import sys
from collections import defaultdict

import pandas as pd

from ticket_router.classifier import TicketClassifier
from ticket_router.config import get_settings
from ticket_router.logging_config import configure_logging
from ticket_router.routing import CONFIDENCE_THRESHOLD


async def evaluate(csv_path: str, text_col: str, label_col: str) -> int:
    configure_logging(get_settings().log_level)
    classifier = TicketClassifier(get_settings())

    df = pd.read_csv(csv_path)
    for col in (text_col, label_col):
        if col not in df.columns:
            print(f"Column '{col}' not found. Columns: {list(df.columns)}")
            return 1

    total = len(df)
    correct = 0
    per_cat_total: dict[str, int] = defaultdict(int)
    per_cat_correct: dict[str, int] = defaultdict(int)
    confusion: dict[tuple[str, str], int] = defaultdict(int)

    auto_count = 0
    auto_correct = 0
    errors = 0

    for _, row in df.iterrows():
        expected = str(row[label_col]).strip()
        per_cat_total[expected] += 1
        try:
            analysis = await classifier.analyze(str(row[text_col]))
        except Exception as exc:
            errors += 1
            print(f"  ERROR: {exc}")
            continue

        predicted = analysis.category.value
        is_correct = predicted == expected
        correct += int(is_correct)
        per_cat_correct[expected] += int(is_correct)
        confusion[(expected, predicted)] += 1

        if analysis.confidence >= CONFIDENCE_THRESHOLD:
            auto_count += 1
            auto_correct += int(is_correct)

    print("\n=== Overall ===")
    scored = total - errors
    if scored:
        print(f"Accuracy: {correct}/{scored} = {correct / scored:.1%}")
    if errors:
        print(f"Errors: {errors}")

    print("\n=== Per category (recall) ===")
    for cat in sorted(per_cat_total):
        t = per_cat_total[cat]
        c = per_cat_correct[cat]
        print(f"  {cat}: {c}/{t} = {c / t:.1%}" if t else f"  {cat}: n/a")

    print(f"\n=== Auto-route at confidence >= {CONFIDENCE_THRESHOLD} ===")
    if scored:
        print(f"Coverage: {auto_count}/{scored} = {auto_count / scored:.1%} of tickets")
    if auto_count:
        print(
            f"Accuracy on auto-routed: {auto_correct}/{auto_count} = "
            f"{auto_correct / auto_count:.1%}"
        )
        print("This last number is the one that matters for enabling enforce mode.")

    print("\n=== Confusion (expected -> predicted, mismatches only) ===")
    for (exp, pred), n in sorted(confusion.items(), key=lambda kv: -kv[1]):
        if exp != pred:
            print(f"  {exp} -> {pred}: {n}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("--text-col", default="support_ticket_text")
    parser.add_argument("--label-col", default="expected_category")
    args = parser.parse_args()
    return asyncio.run(evaluate(args.csv, args.text_col, args.label_col))


if __name__ == "__main__":
    sys.exit(main())
