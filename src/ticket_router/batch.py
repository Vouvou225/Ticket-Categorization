"""
Batch runner.

Pulls a batch of incidents from BigQuery, classifies each with the same
classifier and routing logic used by the live service, and writes predictions
to the results table. Classification runs with bounded concurrency so a batch
of a few hundred does not make one slow call at a time, while still respecting
Vertex quota.

Every incident produces a row, including ones whose classification failed
(recorded with a null category and a reason), so the output is a complete
account of the batch.
"""

import asyncio
from datetime import UTC, datetime

from ticket_router.classifier import TicketClassifier
from ticket_router.config import Settings
from ticket_router.logging_config import get_logger
from ticket_router.redaction import redact
from ticket_router.routing import decide_route, triage_fallback

logger = get_logger(__name__)


def build_text(incident: dict) -> str:
    """Combine the title and body into the text the model reads."""
    title = (incident.get("short_description") or "").strip()
    body = (incident.get("description") or "").strip()
    if title and body:
        return f"{title}\n\n{body}"
    return title or body


class BatchRunner:
    def __init__(self, settings: Settings, classifier: TicketClassifier, source, writer):
        self._settings = settings
        self._classifier = classifier
        self._source = source
        self._writer = writer

    async def _process(self, incident: dict) -> dict:
        text = build_text(incident)
        human_category = incident.get("human_category")
        model_input = redact(text) if self._settings.redact_pii else text
        excerpt = (redact(text) if self._settings.redact_in_audit else text)[:500]
        now = datetime.now(UTC).isoformat()

        try:
            analysis = await self._classifier.analyze(model_input)
            decision = decide_route(analysis.category, analysis.priority, analysis.confidence)
            predicted = analysis.category.value
            match = (
                predicted.strip().lower() == str(human_category).strip().lower()
                if human_category
                else None
            )
            return {
                "sys_id": incident.get("sys_id"),
                "number": incident.get("number"),
                "predicted_category": predicted,
                "confidence": analysis.confidence,
                "priority": analysis.priority.value,
                "eta": analysis.eta.value,
                "tags": list(analysis.tags),
                "assignment_group": decision.assignment_group,
                "auto_routed": decision.auto_routed,
                "reason": decision.reason,
                "human_category": human_category,
                "human_assignment_group": incident.get("human_assignment_group"),
                "category_match": match,
                "ticket_excerpt": excerpt,
                "model": self._settings.gemini_model,
                "predicted_at": now,
            }
        except Exception as exc:
            logger.error(
                "classification failed for incident",
                extra={"fields": {"number": incident.get("number"), "error": str(exc)}},
            )
            decision = triage_fallback(f"classification error: {exc}")
            return {
                "sys_id": incident.get("sys_id"),
                "number": incident.get("number"),
                "predicted_category": None,
                "confidence": None,
                "priority": None,
                "eta": None,
                "tags": [],
                "assignment_group": decision.assignment_group,
                "auto_routed": False,
                "reason": decision.reason,
                "human_category": human_category,
                "human_assignment_group": incident.get("human_assignment_group"),
                "category_match": None,
                "ticket_excerpt": excerpt,
                "model": self._settings.gemini_model,
                "predicted_at": now,
            }

    async def run(self, limit: int, write: bool = True) -> dict:
        incidents = self._source.fetch_recent(limit)
        if not incidents:
            logger.info("no incidents to process")
            return {"total": 0, "classified": 0, "failed": 0}

        sem = asyncio.Semaphore(self._settings.batch_concurrency)

        async def bounded(inc: dict) -> dict:
            async with sem:
                return await self._process(inc)

        rows = await asyncio.gather(*[bounded(inc) for inc in incidents])

        if write:
            self._writer.write(rows)

        return self._summarize(rows)

    @staticmethod
    def _summarize(rows: list[dict]) -> dict:
        total = len(rows)
        failed = sum(1 for r in rows if r["predicted_category"] is None)
        classified = total - failed
        auto = sum(1 for r in rows if r["auto_routed"])
        scored = [r for r in rows if r["category_match"] is not None]
        matched = sum(1 for r in scored if r["category_match"])
        summary: dict[str, int | float] = {
            "total": total,
            "classified": classified,
            "failed": failed,
            "auto_routed": auto,
            "scored_against_human": len(scored),
            "category_matches": matched,
        }
        if scored:
            summary["match_rate"] = round(matched / len(scored), 4)
        return summary
