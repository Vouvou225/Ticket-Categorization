"""
Evaluate the predictions already written to BigQuery.

Reads the predictions table, compares the model's category to the human's, and
prints accuracy, per-category precision and recall, where the misses go, and
confidence calibration. Cheap: one query over the small predictions table, no
Vertex calls.

    python scripts/evaluate_predictions.py
"""

import sys

from ticket_router.config import get_settings
from ticket_router.evaluation import compute_metrics, top_confusions
from ticket_router.logging_config import configure_logging


def _fmt(x: float | None) -> str:
    return f"{x:.1%}" if x is not None else "n/a"


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)

    from google.cloud import bigquery

    client = bigquery.Client(project=settings.google_cloud_project)
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=settings.max_bytes_billed)
    sql = f"""
        SELECT predicted_category, human_category, confidence, category_match
        FROM `{settings.predictions_table}`
        WHERE predicted_category IS NOT NULL
    """
    rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
    if not rows:
        print("No predictions found. Run a batch first: python scripts/run_batch.py --limit 150")
        return 1

    m = compute_metrics(rows)

    print("\n=== Overall ===")
    print(f"Scored against human labels: {m['scored']}")
    print(f"Accuracy: {_fmt(m['accuracy'])} ({m['matches']}/{m['scored']})")

    print("\n=== Per category ===")
    print(f"{'category':<20} {'support':>8} {'precision':>10} {'recall':>8} {'f1':>7}")
    for c in m["per_category"]:
        print(
            f"{c['category']:<20} {c['support']:>8} "
            f"{_fmt(c['precision']):>10} {_fmt(c['recall']):>8} {_fmt(c['f1']):>7}"
        )

    print("\n=== Where the misses go (human -> model) ===")
    for item in top_confusions(m["confusion"]):
        misses = ", ".join(f"{x['predicted']} {_fmt(x['share'])}" for x in item["misses"])
        print(f"  {item['category']}: {misses}")

    print("\n=== Confidence calibration ===")
    print("Are high-confidence predictions actually more accurate?")
    for b in m["calibration"]:
        print(f"  confidence {b['band']}: {_fmt(b['accuracy'])} accurate on {b['n']} tickets")

    return 0


if __name__ == "__main__":
    sys.exit(main())
