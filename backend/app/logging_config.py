"""Structured-enough logging: one line per event, request id when available."""
from __future__ import annotations

import contextvars
import logging
import sys

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] [req=%(request_id)s] %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "multipart", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
