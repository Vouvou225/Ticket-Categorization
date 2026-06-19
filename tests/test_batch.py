"""Tests for the BigQuery batch runner (no real BigQuery or Vertex)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ticket_router import routing
from ticket_router.batch import BatchRunner, build_text
from ticket_router.config import get_settings


def _incident(num="INC1", short="printer down", desc="the printer jammed", cat="hardwares"):
    return {
        "sys_id": "SYS_" + num,
        "number": num,
        "short_description": short,
        "description": desc,
        "human_category": cat,
        "human_assignment_group": "grpX",
    }


def test_build_text_combines_title_and_body():
    out = build_text({"short_description": "title", "description": "body"})
    assert "title" in out and "body" in out


def test_build_text_handles_missing_body():
    assert build_text({"short_description": "only title", "description": None}) == "only title"


@pytest.mark.asyncio
async def test_run_produces_one_row_per_incident(sample_analysis):
    settings = get_settings()
    source = MagicMock()
    source.fetch_recent.return_value = [_incident("INC1"), _incident("INC2")]
    classifier = MagicMock()
    classifier.analyze = AsyncMock(return_value=sample_analysis)
    writer = MagicMock()

    runner = BatchRunner(settings, classifier, source, writer)
    summary = await runner.run(limit=2)

    assert summary["total"] == 2
    assert summary["classified"] == 2
    assert summary["failed"] == 0
    writer.write.assert_called_once()
    written_rows = writer.write.call_args.args[0]
    assert len(written_rows) == 2
    assert written_rows[0]["predicted_category"] == sample_analysis.category.value


@pytest.mark.asyncio
async def test_failed_classification_becomes_a_fallback_row(sample_analysis):
    settings = get_settings()
    source = MagicMock()
    source.fetch_recent.return_value = [_incident("INC1"), _incident("INC2")]
    classifier = MagicMock()
    classifier.analyze = AsyncMock(side_effect=[sample_analysis, RuntimeError("boom")])
    writer = MagicMock()

    runner = BatchRunner(settings, classifier, source, writer)
    summary = await runner.run(limit=2)

    assert summary["classified"] == 1
    assert summary["failed"] == 1
    rows = writer.write.call_args.args[0]
    failed = [r for r in rows if r["predicted_category"] is None][0]
    assert failed["assignment_group"] == routing.TRIAGE_GROUP_SYS_ID
    assert "classification error" in failed["reason"]


@pytest.mark.asyncio
async def test_category_match_scoring(sample_analysis):
    settings = get_settings()
    source = MagicMock()
    # one incident whose human category matches the model, one that does not
    source.fetch_recent.return_value = [
        _incident("INC1", cat=sample_analysis.category.value),
        _incident("INC2", cat="Something else"),
    ]
    classifier = MagicMock()
    classifier.analyze = AsyncMock(return_value=sample_analysis)
    writer = MagicMock()

    runner = BatchRunner(settings, classifier, source, writer)
    summary = await runner.run(limit=2)

    assert summary["scored_against_human"] == 2
    assert summary["category_matches"] == 1
    assert summary["match_rate"] == 0.5


@pytest.mark.asyncio
async def test_no_write_flag_skips_writer(sample_analysis):
    settings = get_settings()
    source = MagicMock()
    source.fetch_recent.return_value = [_incident("INC1")]
    classifier = MagicMock()
    classifier.analyze = AsyncMock(return_value=sample_analysis)
    writer = MagicMock()

    runner = BatchRunner(settings, classifier, source, writer)
    await runner.run(limit=1, write=False)
    writer.write.assert_not_called()


@pytest.mark.asyncio
async def test_empty_source_returns_zero_summary():
    settings = get_settings()
    source = MagicMock()
    source.fetch_recent.return_value = []
    runner = BatchRunner(settings, MagicMock(), source, MagicMock())
    summary = await runner.run(limit=10)
    assert summary == {"total": 0, "classified": 0, "failed": 0}
