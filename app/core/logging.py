"""Uvicorn logging configuration — built from LOG_LEVEL + LOG_FORMATTER env vars."""

from __future__ import annotations

import json as _json
import logging


class _RootFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.name = "root"
        return True


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter with no third-party dependencies.

    Emits one JSON object per line: ``time``, ``level``, ``logger``,
    ``message`` and, when present, ``exception``. Designed to be wired into
    uvicorn's logging dictConfig so application loggers share format with
    uvicorn itself.
    """

    def __init__(self) -> None:
        super().__init__()

    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_text:
            obj["exception"] = record.exc_text.rstrip()
        return _json.dumps(obj, default=str)


def build_uvicorn_log_config() -> dict:
    """Build a Python ``dictConfig`` for uvicorn based on ``LOG_LEVEL`` +
    ``LOG_FORMATTER`` env vars (read via :class:`config.Config`).

    ``LOG_FORMATTER == "json"`` yields structured JSON records; anything else
    falls back to uvicorn's default text format: ``[levelname] name - message``.

    The root logger is configured here so any ``logging.getLogger(...)`` call
    in the application shares the same formatter as uvicorn itself.
    """
    # Late import — avoids a top-level dep on config.Config at module load time,
    # but dotenv has already run (it lives in app/__init__.py) by the time this
    # function is called from main().
    from config import Config

    level = getattr(Config, "LOG_LEVEL", "INFO").upper()
    fmt = getattr(Config, "LOG_FORMATTER", "").lower()

    formatter: dict = (
        {"()": JsonFormatter}
        if fmt == "json"
        else {"format": "[%(levelname)s] %(name)s - %(message)s"}
    )

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"root_filter": {"()": _RootFilter}},
        "formatters": {"default": formatter},
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "filters": ["root_filter"],
                "formatter": "default",
                "stream": "ext://sys.stdout",
            }
        },
        "root": {"level": level, "handlers": ["default"]},
    }
