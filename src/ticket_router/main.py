"""
HTTP layer.

Wires the app together with a lifespan that builds the clients once, request-id
middleware, a global exception handler, and the endpoints. The endpoints are
thin: they unpack the request, call RoutingService, and shape the response.

Endpoints:
  GET  /healthz       liveness, always 200 if the process is up
  GET  /readyz        readiness, 200 when config and clients are present
  POST /route         classify and route a ticket (create or update)
  POST /sn/webhook    handle a ServiceNow Business Rule / Flow payload
"""

import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from ticket_router.audit import AuditLogger
from ticket_router.classifier import TicketClassifier
from ticket_router.config import get_settings
from ticket_router.logging_config import configure_logging, get_logger, request_id_var
from ticket_router.schemas import HealthResponse, RouteRequest, RouteResult
from ticket_router.security import verify_token
from ticket_router.service import RoutingService
from ticket_router.servicenow import ServiceNowClient

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.assert_production_ready()

    classifier = TicketClassifier(settings)
    servicenow = ServiceNowClient(settings) if settings.write_to_servicenow else None
    audit = AuditLogger(settings)

    app.state.settings = settings
    app.state.service = RoutingService(settings, classifier, servicenow, audit)
    logger.info("service started", extra={"fields": {"environment": settings.environment}})

    try:
        yield
    finally:
        if servicenow is not None:
            await servicenow.aclose()
        logger.info("service stopped")


app = FastAPI(title="Help Desk Ticket Router", version="1.0.0", lifespan=lifespan)


def get_service(request: Request) -> RoutingService:
    return request.app.state.service


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    request.state.request_id = request_id
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-Id"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Read the id from request.state, not the context var: by the time this
    # handler runs the middleware's finally block has already reset the var.
    request_id = getattr(request.state, "request_id", "-")
    logger.error("unhandled error", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "internal error", "request_id": request_id},
        headers={"X-Request-Id": request_id},
    )


@app.get("/healthz", response_model=HealthResponse)
def healthz(request: Request):
    settings = request.app.state.settings
    return HealthResponse(status="ok", environment=settings.environment)


@app.get("/readyz", response_model=HealthResponse)
def readyz(request: Request):
    settings = request.app.state.settings
    if not getattr(request.app.state, "service", None):
        raise HTTPException(status_code=503, detail="service not ready")
    return HealthResponse(status="ready", environment=settings.environment)


@app.post("/route", response_model=RouteResult, dependencies=[Depends(verify_token)])
async def route(req: RouteRequest, service: RoutingService = Depends(get_service)):
    outcome = await service.process(
        request_id=request_id_var.get(),
        text=req.text,
        sys_id=req.sys_id,
        short_description=req.short_description,
        caller_id=req.caller_id,
    )
    return RouteResult(
        request_id=request_id_var.get(),
        mode=outcome.mode,
        skipped=outcome.skipped,
        fallback=outcome.fallback,
        analysis=outcome.analysis,
        assignment_group=outcome.decision.assignment_group if outcome.decision else None,
        auto_routed=outcome.decision.auto_routed if outcome.decision else False,
        reason=outcome.decision.reason if outcome.decision else "skipped, already assigned",
        servicenow_sys_id=outcome.servicenow_sys_id,
        servicenow_number=outcome.servicenow_number,
    )


@app.post("/sn/webhook", dependencies=[Depends(verify_token)])
async def servicenow_webhook(request: Request, service: RoutingService = Depends(get_service)):
    body = await request.json()
    sys_id = body.get("sys_id")
    text = (body.get("description") or body.get("short_description") or "").strip()
    short_description = body.get("short_description")

    if not sys_id:
        raise HTTPException(status_code=400, detail="payload missing sys_id")
    if not text:
        raise HTTPException(status_code=400, detail="payload has no ticket text")

    outcome = await service.process(
        request_id=request_id_var.get(),
        text=text,
        sys_id=sys_id,
        short_description=short_description,
    )
    return {
        "request_id": request_id_var.get(),
        "sys_id": outcome.servicenow_sys_id,
        "number": outcome.servicenow_number,
        "mode": outcome.mode,
        "skipped": outcome.skipped,
        "fallback": outcome.fallback,
        "assignment_group": outcome.decision.assignment_group if outcome.decision else None,
        "auto_routed": outcome.decision.auto_routed if outcome.decision else False,
        "category": outcome.analysis.category.value if outcome.analysis else None,
        "confidence": outcome.analysis.confidence if outcome.analysis else None,
    }
