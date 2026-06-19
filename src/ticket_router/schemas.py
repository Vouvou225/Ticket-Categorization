"""
Pydantic schemas.

TicketAnalysis is handed to Gemini as the response_schema, so the model is
forced to return exactly these fields with exactly these allowed values.
The rest are the request and response shapes for the HTTP API.
"""

from pydantic import BaseModel, Field

from ticket_router.routing import ETA, Category, Priority


class TicketAnalysis(BaseModel):
    """Model output contract. Used as the Vertex response_schema."""

    category: Category = Field(description="The single best category for this ticket.")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the category from 0.0 to 1.0.",
    )
    tags: list[str] = Field(description="3 to 6 short keywords describing the specific issue.")
    priority: Priority = Field(description="Resolution priority based on impact and sentiment.")
    eta: ETA = Field(description="Target resolution window.")
    draft_response: str = Field(
        description="A short, empathetic customer reply under 60 words that names the ETA.",
    )


class RouteRequest(BaseModel):
    text: str = Field(min_length=1, description="The body of the support ticket.")
    sys_id: str | None = Field(
        default=None,
        description="If set, update this existing ServiceNow incident instead of creating one.",
    )
    short_description: str | None = None
    caller_id: str | None = None


class RouteResult(BaseModel):
    request_id: str
    mode: str
    skipped: bool = False
    fallback: bool = False
    analysis: TicketAnalysis | None = None
    assignment_group: str | None = None
    auto_routed: bool = False
    reason: str | None = None
    servicenow_sys_id: str | None = None
    servicenow_number: str | None = None


class HealthResponse(BaseModel):
    status: str
    environment: str
