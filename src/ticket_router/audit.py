"""
Audit trail.

Every routing decision is streamed to BigQuery so you can measure accuracy,
tune the confidence threshold from real data, and answer "why did this ticket
go there" months later. For a government help desk that audit trail matters.

Writes are best-effort: if BigQuery is unavailable we log the failure and let
the request succeed, because failing to route a ticket is worse than failing to
record that we routed it. The schema lives in sql/audit_table.sql.
"""

from datetime import UTC, datetime

from ticket_router.config import Settings
from ticket_router.logging_config import get_logger
from ticket_router.routing import RouteDecision
from ticket_router.schemas import TicketAnalysis

logger = get_logger(__name__)


class AuditLogger:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = None
        self._table_ref = settings.bigquery_table_ref
        if settings.audit_enabled:
            try:
                from google.cloud import bigquery

                self._client = bigquery.Client(project=settings.google_cloud_project)
            except Exception as exc:  # pragma: no cover - depends on env
                logger.warning(
                    "audit disabled, could not init BigQuery client",
                    extra={"fields": {"error": str(exc)}},
                )

    def record(
        self,
        request_id: str,
        text: str,
        analysis: TicketAnalysis | None,
        decision: RouteDecision,
        servicenow_sys_id: str | None,
        servicenow_number: str | None,
    ) -> None:
        if self._client is None:
            return
        row = {
            "request_id": request_id,
            "occurred_at": datetime.now(UTC).isoformat(),
            "ticket_excerpt": text[:500],
            "category": analysis.category.value if analysis else None,
            "confidence": analysis.confidence if analysis else None,
            "priority": analysis.priority.value if analysis else None,
            "eta": analysis.eta.value if analysis else None,
            "tags": list(analysis.tags) if analysis else [],
            "assignment_group": decision.assignment_group,
            "auto_routed": decision.auto_routed,
            "reason": decision.reason,
            "servicenow_sys_id": servicenow_sys_id,
            "servicenow_number": servicenow_number,
        }
        try:
            errors = self._client.insert_rows_json(self._table_ref, [row])
            if errors:
                logger.error(
                    "audit row insert returned errors",
                    extra={"fields": {"errors": errors}},
                )
        except Exception as exc:  # pragma: no cover - depends on env
            logger.error(
                "audit row insert failed",
                extra={"fields": {"error": str(exc)}},
            )
