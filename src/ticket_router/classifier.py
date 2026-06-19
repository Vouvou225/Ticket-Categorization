"""
The classifier. One async Gemini call on Vertex AI with schema-enforced output.

This replaces the four sequential Mistral calls and the brace-finding parser
from the notebook. The response_schema forces valid output, so response.parsed
comes back as a TicketAnalysis directly.

Auth: on Cloud Run this uses the service account automatically (ADC). For local
runs do `gcloud auth application-default login` once. The service account needs
roles/aiplatform.user.
"""

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from ticket_router.config import Settings
from ticket_router.logging_config import get_logger
from ticket_router.schemas import TicketAnalysis

logger = get_logger(__name__)

# The prompt deliberately does not restate the JSON shape or give an example;
# the schema handles structure and duplicating it lowers output quality.
SYSTEM_INSTRUCTION = """You are a triage assistant for an IT help desk.
Read the support ticket and classify it. Choose the single most appropriate
category. Set confidence honestly: a high value only when the ticket clearly
fits one category, and a low value when it is vague, mixed, or could belong to
several. Base priority on the severity of the impact and the sentiment of the
message; do not mark everything high. Keep tags specific to the actual problem.
The draft reply should be warm, brief, and name the ETA.
"""


def _is_retryable_vertex(exc: BaseException) -> bool:
    """Retry on server errors, timeouts, and rate limits only, never on other 4xx."""
    if isinstance(exc, TimeoutError | genai_errors.ServerError):
        return True
    if isinstance(exc, genai_errors.APIError):
        return getattr(exc, "code", None) == 429
    return False


class TicketClassifier:
    """Wraps a Vertex AI client. Construct once and reuse for the process lifetime."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )

    async def analyze(self, text: str) -> TicketAnalysis:
        text = text.strip()
        if not text:
            raise ValueError("ticket text is empty")
        if len(text) > self._settings.max_ticket_chars:
            text = text[: self._settings.max_ticket_chars]
        return await self._call_model(text)

    async def _call_model(self, text: str) -> TicketAnalysis:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception(_is_retryable_vertex),
            stop=stop_after_attempt(self._settings.vertex_max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
            reraise=True,
        ):
            with attempt:
                response = await self._client.aio.models.generate_content(
                    model=self._settings.gemini_model,
                    contents=f"Support ticket:\n{text}",
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=TicketAnalysis,
                        http_options=types.HttpOptions(
                            timeout=int(self._settings.vertex_timeout_seconds * 1000)
                        ),
                    ),
                )
                result = response.parsed
                if not isinstance(result, TicketAnalysis):
                    raise ValueError(f"model returned no parseable analysis: {response.text!r}")
                return result
        raise AssertionError("unreachable")  # AsyncRetrying always returns or raises
