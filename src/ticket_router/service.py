"""
Orchestration.

The RoutingService ties the pieces together: optionally skip tickets a human
already owns, classify the ticket (failing safe to triage), write to ServiceNow
in suggest or enforce mode, and record the decision for audit. The HTTP layer
stays thin and this is where the business flow and its tests live.
"""

from dataclasses import dataclass

from ticket_router.audit import AuditLogger
from ticket_router.classifier import TicketClassifier
from ticket_router.config import Settings
from ticket_router.logging_config import get_logger
from ticket_router.redaction import redact
from ticket_router.routing import RouteDecision, decide_route, triage_fallback
from ticket_router.schemas import TicketAnalysis
from ticket_router.servicenow import ServiceNowClient

logger = get_logger(__name__)


@dataclass
class RoutingOutcome:
    analysis: TicketAnalysis | None
    decision: RouteDecision | None
    servicenow_sys_id: str | None
    servicenow_number: str | None
    mode: str
    skipped: bool = False  # human already owned it, we did nothing
    fallback: bool = False  # classification failed, sent to triage


class RoutingService:
    def __init__(
        self,
        settings: Settings,
        classifier: TicketClassifier,
        servicenow: ServiceNowClient | None,
        audit: AuditLogger,
    ):
        self._settings = settings
        self._classifier = classifier
        self._servicenow = servicenow
        self._audit = audit

    async def process(
        self,
        request_id: str,
        text: str,
        sys_id: str | None = None,
        short_description: str | None = None,
        caller_id: str | None = None,
    ) -> RoutingOutcome:
        mode = self._settings.routing_mode

        # 1. Idempotency / human-override guard. Only meaningful for an existing
        #    incident. If a human or a prior run already assigned it, do nothing.
        if sys_id and self._settings.skip_if_assigned and self._servicenow is not None:
            existing = await self._servicenow.get_incident(sys_id)
            if existing.get("already_assigned"):
                logger.info(
                    "skipping, incident already assigned",
                    extra={"fields": {"sys_id": sys_id, "number": existing.get("number")}},
                )
                return RoutingOutcome(
                    analysis=None,
                    decision=None,
                    servicenow_sys_id=existing.get("sys_id"),
                    servicenow_number=existing.get("number"),
                    mode=mode,
                    skipped=True,
                )

        # 2. Classify, failing safe. A model or quota failure must not drop the
        #    ticket; it goes to triage with a note instead.
        model_input = redact(text) if self._settings.redact_pii else text
        fallback = False
        analysis: TicketAnalysis | None
        try:
            analysis = await self._classifier.analyze(model_input)
            decision = decide_route(analysis.category, analysis.priority, analysis.confidence)
        except Exception as exc:
            logger.error("classification failed, routing to triage", exc_info=exc)
            analysis = None
            decision = triage_fallback(f"classification error: {exc}")
            fallback = True

        if analysis is not None:
            logger.info(
                "ticket classified",
                extra={
                    "fields": {
                        "category": analysis.category.value,
                        "confidence": analysis.confidence,
                        "auto_routed": decision.auto_routed,
                        "assignment_group": decision.assignment_group,
                        "mode": mode,
                    }
                },
            )

        # 3. Write to ServiceNow. On a fallback we always assign (enforce-like)
        #    so the ticket reaches a human even in suggest mode.
        write_mode = "enforce" if fallback else mode
        sn_sys_id: str | None = None
        sn_number: str | None = None
        if self._settings.write_to_servicenow and self._servicenow is not None:
            if sys_id:
                sn = await self._servicenow.update_incident(
                    sys_id,
                    analysis,
                    decision,
                    mode=write_mode,
                    short_description=short_description,
                    caller_id=caller_id,
                )
            else:
                sn = await self._servicenow.create_incident(
                    analysis,
                    decision,
                    description=text,
                    mode=write_mode,
                    short_description=short_description,
                    caller_id=caller_id,
                )
            sn_sys_id, sn_number = sn["sys_id"], sn["number"]

        # 4. Audit every classification attempt, including fallbacks, so failures
        #    are visible. Redact the stored excerpt unless told otherwise.
        audit_text = redact(text) if self._settings.redact_in_audit else text
        self._audit.record(
            request_id=request_id,
            text=audit_text,
            analysis=analysis,
            decision=decision,
            servicenow_sys_id=sn_sys_id,
            servicenow_number=sn_number,
        )

        return RoutingOutcome(
            analysis=analysis,
            decision=decision,
            servicenow_sys_id=sn_sys_id,
            servicenow_number=sn_number,
            mode=mode,
            fallback=fallback,
        )
