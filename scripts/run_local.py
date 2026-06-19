"""
Local test harness. Runs classification and routing against the notebook's CSV
so you can validate accuracy before wiring up ServiceNow.

Usage:
    python scripts/run_local.py support_ticket_data.csv
    python scripts/run_local.py --text "Laptop won't boot, demo in an hour"

It calls Vertex AI (so GOOGLE_CLOUD_PROJECT must be set and ADC configured) but
never touches ServiceNow. Fastest loop for tuning the prompt, taxonomy, and
confidence threshold.
"""

import argparse
import asyncio
import sys

import pandas as pd

from ticket_router.classifier import TicketClassifier
from ticket_router.config import get_settings
from ticket_router.logging_config import configure_logging
from ticket_router.routing import decide_route


async def _analyze_one(classifier: TicketClassifier, text: str):
    analysis = await classifier.analyze(text)
    decision = decide_route(analysis.category, analysis.priority, analysis.confidence)
    return analysis, decision


def _print(analysis, decision) -> None:
    flag = "AUTO" if decision.auto_routed else "TRIAGE"
    print(
        f"  [{flag}] {analysis.category.value} (conf {analysis.confidence:.2f}) "
        f"| {analysis.priority.value} | {analysis.eta.value}"
    )
    print(f"        tags: {', '.join(analysis.tags)}")
    print(f"        group: {decision.assignment_group}")
    print(f"        why: {decision.reason}")
    print(f"        draft: {analysis.draft_response}")


async def main_async() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", nargs="?", help="CSV with a support_ticket_text column")
    parser.add_argument("--text", help="classify a single ticket string")
    parser.add_argument("--column", default="support_ticket_text")
    args = parser.parse_args()

    configure_logging(get_settings().log_level)
    classifier = TicketClassifier(get_settings())

    if args.text:
        print("Ticket:", args.text)
        _print(*await _analyze_one(classifier, args.text))
        return 0

    if not args.csv:
        parser.error("provide a CSV path or --text")

    df = pd.read_csv(args.csv)
    if args.column not in df.columns:
        print(f"Column '{args.column}' not found. Columns: {list(df.columns)}")
        return 1

    auto = 0
    for i, row in df.iterrows():
        text = str(row[args.column])
        print(f"\n#{i}: {text[:90]}")
        try:
            analysis, decision = await _analyze_one(classifier, text)
            auto += int(decision.auto_routed)
            _print(analysis, decision)
        except Exception as exc:
            print(f"  ERROR: {exc}")

    total = len(df)
    print(f"\nAuto-routed {auto}/{total}, triage {total - auto}/{total}.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
