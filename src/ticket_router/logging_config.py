"""
Structured logging.

Cloud Run reads stdout and parses JSON lines into Cloud Logging. We emit one
JSON object per log line with a `severity` field (the key Cloud Logging keys
on) and attach a request id when one is available. No print statements anywhere
in the codebase; everything goes through a logger.
"""

import json
import logging
import sys
from contextvars import ContextVar

# Carries the current request id across the call stack without threading it
# through every function signature.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_LEVEL_TO_SEVERITY = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": _LEVEL_TO_SEVERITY.get(record.levelname, "DEFAULT"),
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": request_id_var.get(),
        }
        # Attach any structured extras passed via logger.info(..., extra={"fields": {...}})
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy third-party loggers a notch.
    for noisy in ("httpx", "httpcore", "google", "urllib3"):
        logging.getLogger(noisy).setLevel("WARNING")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
