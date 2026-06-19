"""
Batch entry point. Reads incidents from BigQuery, classifies and routes them,
and writes predictions to the results table.

Usage:
    python scripts/run_batch.py                 # most recent 200 incidents
    python scripts/run_batch.py --limit 50      # smaller batch
    python scripts/run_batch.py --no-write      # classify and summarize, write nothing

Needs GOOGLE_CLOUD_PROJECT set and ADC configured (gcloud auth
application-default login). Reads from the source table set in config and writes
to the predictions table. The source is never modified.
"""

import argparse
import asyncio
import json
import sys

from ticket_router.batch import BatchRunner
from ticket_router.bigquery_source import IncidentSource
from ticket_router.classifier import TicketClassifier
from ticket_router.config import get_settings
from ticket_router.logging_config import configure_logging
from ticket_router.results_writer import PredictionsWriter


async def main_async() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="how many incidents to pull")
    parser.add_argument("--no-write", action="store_true", help="do not write to BigQuery")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    limit = args.limit or settings.batch_size

    classifier = TicketClassifier(settings)
    source = IncidentSource(settings)
    writer = None if args.no_write else PredictionsWriter(settings)
    runner = BatchRunner(settings, classifier, source, writer)

    print(f"Reading up to {limit} incidents from {settings.incident_source_table}")
    if args.no_write:
        print("Dry run: predictions will not be written.")
    else:
        print(f"Writing predictions to {settings.predictions_table}")

    summary = await runner.run(limit=limit, write=not args.no_write)
    print("\n=== Summary ===")
    print(json.dumps(summary, indent=2))
    if "match_rate" in summary:
        print(
            f"\nCategory match vs human labels: {summary['match_rate']:.1%} "
            f"on {summary['scored_against_human']} scored incidents."
        )
        print(
            "Note: match rate is only meaningful once the Category enum in "
            "routing.py uses the same category values as ServiceNow."
        )
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
