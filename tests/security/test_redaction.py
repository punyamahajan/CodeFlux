from __future__ import annotations

import io
import logging

from codeflux.security.redaction import RedactionFilter, install_redaction_filter, redact_text


def test_redact_text_masks_all_patterns():
    # ok_live_ key
    text_ok = "Client initialized with ok_live_abc123XYZ_999 successfully"
    redacted_ok = redact_text(text_ok)
    assert "ok_live_abc123XYZ_999" not in redacted_ok
    assert "ok_live_[REDACTED]" in redacted_ok

    # sk- key
    text_sk = "Using upstream provider key sk-proj-1234567890abcdef"
    redacted_sk = redact_text(text_sk)
    assert "sk-proj-1234567890abcdef" not in redacted_sk
    assert "sk-[REDACTED]" in redacted_sk

    # AIza key
    text_aiza = "Gemini key is AIzaSyD1234567890ABCDEF"
    redacted_aiza = redact_text(text_aiza)
    assert "AIzaSyD1234567890ABCDEF" not in redacted_aiza
    assert "AIza[REDACTED]" in redacted_aiza

    # Authorization header
    text_auth = "Request headers: Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.test"
    redacted_auth = redact_text(text_auth)
    assert "eyJhbGciOiJIUzI1NiJ9.test" not in redacted_auth
    assert "Authorization: Bearer [REDACTED]" in redacted_auth


def test_log_redaction_on_root_logger():
    # Create an in-memory stream to capture log output
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))

    test_logger = logging.getLogger("codeflux.test_redact")
    test_logger.setLevel(logging.INFO)
    test_logger.addHandler(handler)

    # Install the redaction filter
    filt = RedactionFilter()
    test_logger.addFilter(filt)
    handler.addFilter(filt)

    secret_key = "ok_live_secret1234567890"
    secret_sk = "sk-live-provider-key-999"
    secret_aiza = "AIzaSySecretGeminiKey"
    secret_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token"

    test_logger.info("Connecting with key %s", secret_key)
    test_logger.info("Using provider key: %s", secret_sk)
    test_logger.info("Gemini credential: %s", secret_aiza)
    test_logger.info("Headers: Authorization: Bearer %s", secret_token)

    output = stream.getvalue()

    # None of the secrets should appear in the logged stream
    assert secret_key not in output
    assert secret_sk not in output
    assert secret_aiza not in output
    assert secret_token not in output

    # Redacted markers should be present
    assert "ok_live_[REDACTED]" in output
    assert "sk-[REDACTED]" in output
    assert "AIza[REDACTED]" in output
    assert "Authorization: Bearer [REDACTED]" in output


def test_install_redaction_filter_attaches_to_logger_and_handlers():
    logger = logging.getLogger("test_install_redact")
    logger.setLevel(logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)

    install_redaction_filter(logger)

    logger.info("My key is ok_live_should_be_masked")
    output = stream.getvalue()
    assert "ok_live_should_be_masked" not in output
    assert "ok_live_[REDACTED]" in output
