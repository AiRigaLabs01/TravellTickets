"""Redact credentials after formatting, including exception tracebacks.

Install after configuring logging; call again if handlers are replaced. This is
defence in depth for standard Python logging, not a sanitizer for arbitrary print
calls, third-party telemetry, or credentials already written to historical logs.
"""

import logging
import os
import re


_QUERY = re.compile(r"((?:https?://|/)[^\s?\"'<>]*)\?[^\s\"'<>]*", re.IGNORECASE)
_BOT_TOKEN = re.compile(r"(?<![0-9])[0-9]{6,12}(?::|%3a)[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])", re.IGNORECASE)
_SECRET_NAMES = (
    "TELEGRAM_BOT_TOKEN", "TRAVELPAYOUTS_TOKEN", "SESSION_SECRET",
    "ADMIN_PASSWORD_HASH", "DATABASE_URL", "POSTGRES_PASSWORD",
)


def redact(text: str) -> str:
    for name in _SECRET_NAMES:
        value = os.getenv(name, "")
        if value:
            text = text.replace(value, "[REDACTED]")
    text = _BOT_TOKEN.sub("[REDACTED]", text)
    return _QUERY.sub(r"\1?[REDACTED]", text)


class RedactingFormatter(logging.Formatter):
    def __init__(self, delegate: logging.Formatter):
        super().__init__()
        self.delegate = delegate

    def format(self, record: logging.LogRecord) -> str:
        return redact(self.delegate.format(record))


def install_log_redaction() -> None:
    # Uvicorn handlers do not all propagate to root. Cover existing handlers,
    # plus the root handler used by app/HTTPX and later-created child loggers.
    loggers = [logging.getLogger()]
    loggers.extend(item for item in logging.Logger.manager.loggerDict.values() if isinstance(item, logging.Logger))
    for logger in loggers:
        for handler in logger.handlers:
            if not isinstance(handler.formatter, RedactingFormatter):
                handler.setFormatter(RedactingFormatter(handler.formatter or logging.Formatter()))
