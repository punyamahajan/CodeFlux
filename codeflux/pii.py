from __future__ import annotations

import re

from codeflux.schemas import Message, NormalizedRequest


class PIIRedactor:
    """Uses Presidio when installed; otherwise masks common deterministic patterns."""

    def __init__(self) -> None:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine

            self.analyzer = AnalyzerEngine()
            self.anonymizer = AnonymizerEngine()
        except ImportError:
            self.analyzer = self.anonymizer = None

    def redact_text(self, text: str) -> str:
        if self.analyzer:
            findings = self.analyzer.analyze(text=text, language="en")
            return self.anonymizer.anonymize(text=text, analyzer_results=findings).text
        text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<EMAIL>", text)
        return re.sub(r"\b(?:\d[ -]*?){13,16}\b", "<CARD_NUMBER>", text)

    def redact(self, request: NormalizedRequest) -> NormalizedRequest:
        copy = request.model_copy(deep=True)
        copy.messages = [
            Message(**{**message.model_dump(), "content": self.redact_text(message.content) if isinstance(message.content, str) else message.content})
            for message in copy.messages
        ]
        if isinstance(copy.prompt, str):
            copy.prompt = self.redact_text(copy.prompt)
        return copy

