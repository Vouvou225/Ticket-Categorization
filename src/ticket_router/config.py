"""
Application configuration.

All settings come from environment variables (or a local .env during
development) and are validated at startup. If a required value is missing or
malformed, the process fails fast with a clear error rather than blowing up on
the first request.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime ---
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    max_ticket_chars: int = 20_000

    # --- Routing behavior ---
    # suggest: write the AI recommendation as a work note only, never change the
    #          assignment. Safe to run live while you measure accuracy.
    # enforce: actually set assignment_group and priority.
    # Start in suggest. Move to enforce only after the audit data says the
    # classifier is good enough.
    routing_mode: Literal["suggest", "enforce"] = "suggest"
    # Skip tickets that already have an assignment group, so the router never
    # reprocesses a ticket or overwrites a human's manual assignment.
    skip_if_assigned: bool = True

    # --- PII ---
    redact_pii: bool = False  # redact text sent to Vertex
    redact_in_audit: bool = True  # redact text stored in the BigQuery excerpt

    # --- Vertex AI ---
    google_cloud_project: str = Field(..., description="GCP project id")
    google_cloud_location: str = "us-central1"
    # flash-lite is cheaper and tuned for classification/routing. Switch to
    # gemini-2.5-flash if you want a bit more accuracy at higher cost.
    gemini_model: str = "gemini-2.5-flash-lite"
    vertex_timeout_seconds: float = 30.0
    vertex_max_retries: int = 3

    # --- ServiceNow (optional: only needed for the live webhook/API mode) ---
    servicenow_instance: str = ""
    servicenow_user: str = ""
    servicenow_password: str = ""
    servicenow_timeout_seconds: float = 30.0
    servicenow_max_retries: int = 3
    write_to_servicenow: bool = True

    # --- BigQuery batch mode ---
    # Reads incidents from a BigQuery table and writes predictions to another.
    # No ServiceNow involved. The source is read-only; predictions go to a
    # separate table you own.
    incident_source_table: str = "omes-sdp-p.hub_bld_snow.ab_sn_incident"
    predictions_table: str = "omes-datascience-sbx.Ticket_Categorization.ticket_router_predictions"
    batch_size: int = 200
    batch_concurrency: int = 5
    # Hard cap on BigQuery bytes scanned per read. A query that would exceed
    # this fails instead of billing. 5 GB is far above a single pull of the
    # incident table (~0.33 GB) and makes a runaway scan impossible.
    max_bytes_billed: int = 5_000_000_000

    # --- Security ---
    # Shared secret expected in the X-Router-Token header on /route and
    # /sn/webhook. Required in production; optional in development.
    webhook_token: str = ""

    # --- Audit (BigQuery) ---
    audit_enabled: bool = True
    bigquery_dataset: str = "help_desk"
    bigquery_table: str = "routing_decisions"

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level: {v}")
        return v

    @property
    def servicenow_base_url(self) -> str:
        return f"https://{self.servicenow_instance}.service-now.com/api/now/table/incident"

    @property
    def bigquery_table_ref(self) -> str:
        return f"{self.google_cloud_project}.{self.bigquery_dataset}.{self.bigquery_table}"

    def assert_production_ready(self) -> None:
        """Fail startup if production is missing things production must have."""
        if self.environment == "production":
            missing = []
            if not self.webhook_token:
                missing.append("WEBHOOK_TOKEN")
            if self.write_to_servicenow and not self.servicenow_password:
                missing.append("SERVICENOW_PASSWORD")
            if missing:
                raise RuntimeError(
                    f"production start blocked, missing required settings: {', '.join(missing)}"
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
