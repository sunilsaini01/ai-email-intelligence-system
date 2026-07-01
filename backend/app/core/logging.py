"""
Structured logging configuration.

Why structured (JSON) logging instead of print() or default text logs:
    In production, logs are not read by a human scrolling a terminal — they're
    ingested by something like ELK/Loki and queried. "ERROR: something failed
    for user 123" is unsearchable. {"level": "error", "user_id": "123", "msg":
    "something failed"} is filterable, aggregatable, and alertable on.

Common mistake this avoids:
    Logging PII or full email bodies at INFO level "just to debug." Once a
    log line ships, it sits in a log aggregator for 90 days (see PRD retention
    policy) outside your normal data-governance controls. Treat log statements
    with the same PII discipline as any other data sink.
"""

import logging
import sys

from pythonjsonlogger import jsonlogger

from app.core.config import get_settings


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(
        self,
        log_record: dict,
        record: logging.LogRecord,
        message_dict: dict,
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name


def setup_logging() -> None:
    settings = get_settings()
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL)

    # Remove any pre-existing handlers (uvicorn attaches its own by default)
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    formatter: logging.Formatter
    if settings.LOG_JSON:
        formatter = CustomJsonFormatter(
            "%(timestamp)s %(level)s %(name)s %(message)s"
        )
    else:
        # human-readable for local dev
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Quiet down noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
