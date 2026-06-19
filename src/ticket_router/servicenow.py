"""
ServiceNow client. Async, with a shared connection pool and retries on
transient failures (network errors, timeouts, and 5xx responses). 4xx errors
are not retried because they will not succeed on a second attempt. The retry
count comes from settings (servicenow_max_retries).

Auth is HTTP basic auth read from settings, the simplest thing that works. For
production move to OAuth; only the client construction changes. Keep the
password in Secret Manager, never a plain env var in the deployed service.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from ticket_router.config import Settings
from ticket_router.logging_config import get_logger
from ticket_router.routing import RouteDecision
from ticket_router.schemas import TicketAnalysis

logger = get_logger(__name__)

T = TypeVar("T")


def _is_transient(exc: BaseException) -> bool:
    """Retry on network/timeout errors and on 5xx responses only."""
    if isinstance(exc, httpx.TransportError | httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class ServiceNowClient:
    """Reusable async client. One per process; share via app state."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(
            auth=(settings.servicenow_user, settings.servicenow_password),
            timeout=settings.servicenow_timeout_seconds,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _send(self, factory: Callable[[], Awaitable[T]]) -> T:
        """Run an HTTP coroutine with transient-failure retries."""
        async for attempt in AsyncRetrying(
            retry=retry_if_exception(_is_transient),
            stop=stop_after_attempt(self._settings.servicenow_max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
            reraise=True,
        ):
            with attempt:
                return await factory()
        raise AssertionError("unreachable")  # AsyncRetrying always returns or raises

    def _build_fields(
        self,
        analysis: TicketAnalysis | None,
        decision: RouteDecision,
        mode: str,
        short_description: str | None,
        caller_id: str | None,
    ) -> dict:
        if analysis is not None:
            route_note = "auto-routed" if decision.auto_routed else "sent to triage for review"
            work_note = (
                f"[AI triage] category={analysis.category.value} "
                f"confidence={analysis.confidence:.2f} priority={analysis.priority.value} "
                f"eta={analysis.eta.value} ({route_note}, mode={mode})\n"
                f"tags: {', '.join(analysis.tags)}\n"
                f"suggested reply: {analysis.draft_response}"
            )
        else:
            # Classification failed. Leave a clear note so a human picks it up.
            work_note = (
                "[AI triage] automatic classification failed, routed to triage "
                f"for manual handling. reason: {decision.reason}"
            )

        # In suggest mode we only attach the recommendation note and never change
        # the assignment or priority. The desk keeps full control until you
        # switch to enforce.
        fields: dict[str, str] = {"work_notes": work_note}

        if mode == "enforce" or analysis is None:
            # On a classification failure we always assign to triage even in
            # suggest mode, because the alternative is an unrouted ticket.
            fields["assignment_group"] = decision.assignment_group
            fields["impact"] = decision.impact
            fields["urgency"] = decision.urgency
            if analysis is not None:
                fields["category"] = analysis.category.value

        if short_description:
            fields["short_description"] = short_description
        if caller_id:
            fields["caller_id"] = caller_id
        return fields

    async def get_incident(self, sys_id: str) -> dict:
        """Fetch the fields needed to decide whether to route this ticket."""

        async def _do() -> dict:
            url = f"{self._settings.servicenow_base_url}/{sys_id}"
            resp = await self._client.get(
                url, params={"sysparm_fields": "sys_id,number,assignment_group,state"}
            )
            resp.raise_for_status()
            record = resp.json()["result"]
            ag = record.get("assignment_group")
            # Reference fields come back as {"link","value"} when set, "" when empty.
            assigned = bool(ag.get("value")) if isinstance(ag, dict) else bool(ag)
            return {
                "sys_id": record.get("sys_id"),
                "number": record.get("number"),
                "already_assigned": assigned,
            }

        return await self._send(_do)

    async def create_incident(
        self,
        analysis: TicketAnalysis | None,
        decision: RouteDecision,
        description: str,
        mode: str = "enforce",
        short_description: str | None = None,
        caller_id: str | None = None,
    ) -> dict:
        fields = self._build_fields(analysis, decision, mode, short_description, caller_id)
        fields["description"] = description
        fields.setdefault("short_description", description[:160])

        async def _do() -> dict:
            resp = await self._client.post(self._settings.servicenow_base_url, json=fields)
            resp.raise_for_status()
            record = resp.json()["result"]
            return {"sys_id": record.get("sys_id"), "number": record.get("number")}

        return await self._send(_do)

    async def update_incident(
        self,
        sys_id: str,
        analysis: TicketAnalysis | None,
        decision: RouteDecision,
        mode: str = "enforce",
        short_description: str | None = None,
        caller_id: str | None = None,
    ) -> dict:
        fields = self._build_fields(analysis, decision, mode, short_description, caller_id)
        url = f"{self._settings.servicenow_base_url}/{sys_id}"

        async def _do() -> dict:
            resp = await self._client.patch(url, json=fields)
            resp.raise_for_status()
            record = resp.json()["result"]
            return {"sys_id": record.get("sys_id"), "number": record.get("number")}

        return await self._send(_do)
