"""Tests for evaluation metrics."""

from ticket_router.evaluation import compute_metrics, top_confusions


def _row(pred, human, conf):
    return {
        "predicted_category": pred,
        "human_category": human,
        "confidence": conf,
        "category_match": (pred == human) if human is not None else None,
    }


def test_accuracy_and_scored_count():
    rows = [
        _row("application", "application", 0.9),
        _row("networking", "networking", 0.8),
        _row("application", "networking", 0.6),
        _row("hardwares", None, 0.7),  # unscored, human label not modeled
    ]
    m = compute_metrics(rows)
    assert m["scored"] == 3
    assert m["matches"] == 2
    assert abs(m["accuracy"] - 2 / 3) < 1e-9


def test_per_category_precision_recall():
    # application: 2 predicted, 1 correct -> precision 0.5; 1 actual app, found -> recall 1.0
    rows = [
        _row("application", "application", 0.9),
        _row("application", "networking", 0.5),
        _row("networking", "networking", 0.8),
    ]
    m = compute_metrics(rows)
    app = next(c for c in m["per_category"] if c["category"] == "application")
    assert app["support"] == 1
    assert abs(app["precision"] - 0.5) < 1e-9
    assert abs(app["recall"] - 1.0) < 1e-9


def test_confusion_and_top_misses():
    rows = [
        _row("application", "networking", 0.6),
        _row("application", "networking", 0.6),
        _row("servers", "networking", 0.6),
        _row("networking", "networking", 0.9),
    ]
    m = compute_metrics(rows)
    tops = top_confusions(m["confusion"])
    net = next(t for t in tops if t["category"] == "networking")
    # networking most often misclassified as application
    assert net["misses"][0]["predicted"] == "application"
    assert net["misses"][0]["n"] == 2


def test_calibration_bands():
    rows = [
        _row("application", "application", 0.95),  # high band, correct
        _row("application", "networking", 0.45),  # low band, wrong
    ]
    m = compute_metrics(rows)
    high = next(b for b in m["calibration"] if b["band"] == "0.90-1.00")
    low = next(b for b in m["calibration"] if b["band"] == "0.00-0.50")
    assert high["n"] == 1 and high["accuracy"] == 1.0
    assert low["n"] == 1 and low["accuracy"] == 0.0


def test_empty_rows():
    m = compute_metrics([])
    assert m["scored"] == 0
    assert m["accuracy"] is None
