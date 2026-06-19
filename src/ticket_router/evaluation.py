"""
Evaluation metrics.

Pure functions over prediction rows, so they are easy to test and have no
BigQuery dependency. Each row is a dict with at least:
  predicted_category, human_category, confidence, category_match

Only rows that can be scored (category_match is not None, meaning the human
label is one of the modeled categories) count toward accuracy, precision, and
recall. The confusion view shows where the misses go, and calibration shows
whether high-confidence predictions are actually more accurate.
"""


def _safe_div(a: float, b: float) -> float | None:
    return a / b if b else None


def compute_metrics(rows: list[dict]) -> dict:
    scored = [r for r in rows if r.get("category_match") is not None]
    total = len(scored)
    matches = sum(1 for r in scored if r["category_match"])

    categories = sorted(
        {r["human_category"] for r in scored} | {r["predicted_category"] for r in scored}
    )

    # Per-category precision, recall, F1, and support.
    per_category = []
    for c in categories:
        tp = sum(1 for r in scored if r["predicted_category"] == c and r["human_category"] == c)
        fp = sum(1 for r in scored if r["predicted_category"] == c and r["human_category"] != c)
        fn = sum(1 for r in scored if r["predicted_category"] != c and r["human_category"] == c)
        support = sum(1 for r in scored if r["human_category"] == c)
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = (
            _safe_div(2 * precision * recall, precision + recall)
            if precision is not None and recall is not None and (precision + recall) > 0
            else None
        )
        per_category.append(
            {
                "category": c,
                "support": support,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        )

    # Confusion: for each human category, where the model actually sent it.
    confusion: dict[str, dict[str, int]] = {}
    for r in scored:
        human = r["human_category"]
        pred = r["predicted_category"]
        confusion.setdefault(human, {})
        confusion[human][pred] = confusion[human].get(pred, 0) + 1

    # Calibration: accuracy within confidence bands.
    bands = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]
    calibration = []
    for lo, hi in bands:
        bucket = [
            r for r in scored if r.get("confidence") is not None and lo <= r["confidence"] < hi
        ]
        n = len(bucket)
        acc = _safe_div(sum(1 for r in bucket if r["category_match"]), n)
        label = f"{lo:.2f}-{min(hi, 1.0):.2f}"
        calibration.append({"band": label, "n": n, "accuracy": acc})

    return {
        "scored": total,
        "matches": matches,
        "accuracy": _safe_div(matches, total),
        "per_category": per_category,
        "confusion": confusion,
        "calibration": calibration,
    }


def top_confusions(confusion: dict[str, dict[str, int]], limit: int = 3) -> list[dict]:
    """For each human category, the categories it is most often misclassified as."""
    out = []
    for human, preds in confusion.items():
        total = sum(preds.values())
        misses = sorted(
            ((p, n) for p, n in preds.items() if p != human),
            key=lambda kv: -kv[1],
        )
        if misses:
            out.append(
                {
                    "category": human,
                    "total": total,
                    "misses": [
                        {"predicted": p, "n": n, "share": _safe_div(n, total)}
                        for p, n in misses[:limit]
                    ],
                }
            )
    return sorted(out, key=lambda d: -sum(m["n"] for m in d["misses"]))
