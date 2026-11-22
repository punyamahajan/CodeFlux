import logging
import sys

from pythonjsonlogger.json import JsonFormatter

from codeflux.security.redaction import install_redaction_filter


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    install_redaction_filter(root)
