from __future__ import annotations

import logging
import re
from typing import Any

# Patterns to mask in logs:
# 1. Authorization headers (bearer tokens or generic authorization values)
# 2. ok_live_ platform keys
# 3. sk- OpenAI-compatible API keys
# 4. AIza Google/Gemini API keys
_AUTHORIZATION_HEADER_PATTERN = re.compile(
    r"(?i)(authorization[\s\"':=]+(?:bearer\s+)?)([^\s,;'\"\}]+)"
)
_OK_LIVE_PATTERN = re.compile(r"ok_live_[a-zA-Z0-9_\-]+")
_SK_PATTERN = re.compile(r"sk-[a-zA-Z0-9_\-]+")
_AIZA_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]+")


def redact_text(text: str) -> str:
    """Mask secrets and authorization headers in a text string."""
    if not isinstance(text, str):
        return text

    # Redact Authorization header values
    text = _AUTHORIZATION_HEADER_PATTERN.sub(r"\1[REDACTED]", text)
    # Redact ok_live_ platform keys
    text = _OK_LIVE_PATTERN.sub(r"ok_live_[REDACTED]", text)
    # Redact sk- provider keys
    text = _SK_PATTERN.sub(r"sk-[REDACTED]", text)
    # Redact AIza Gemini keys
    text = _AIZA_PATTERN.sub(r"AIza[REDACTED]", text)

    return text


def redact_value(val: Any) -> Any:
    """Recursively redact secrets in strings, mappings, and sequences."""
    if isinstance(val, str):
        return redact_text(val)
    if isinstance(val, dict):
        return {k: redact_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return type(val)(redact_value(item) for item in val)
    return val


class RedactionFilter(logging.Filter):
    """Logging filter that masks ok_live_, sk-, AIza keys and Authorization headers."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.args:
                # Merge args into message before redaction to avoid %-formatting specifier mismatch
                formatted_msg = record.getMessage()
                record.msg = redact_text(formatted_msg)
                record.args = ()
            elif isinstance(record.msg, str):
                record.msg = redact_text(record.msg)
            elif record.msg:
                record.msg = redact_value(record.msg)
        except (TypeError, ValueError, AttributeError, KeyError):
            if isinstance(record.msg, str):
                record.msg = redact_text(record.msg)
            elif record.msg:
                record.msg = redact_value(record.msg)
            if record.args:
                record.args = redact_value(record.args)

        return True


def install_redaction_filter(logger: logging.Logger | None = None) -> RedactionFilter:
    """Install RedactionFilter on the specified logger (or root logger if None) and its handlers."""
    target_logger = logger if logger is not None else logging.getLogger()
    filt = RedactionFilter()
    target_logger.addFilter(filt)
    for handler in target_logger.handlers:
        handler.addFilter(filt)
    return filt
