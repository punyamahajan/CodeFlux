class CodeFluxError(Exception):
    """Base gateway error."""


class ProviderError(CodeFluxError):
    def __init__(self, message: str, *, status_code: int = 502, retryable: bool = True):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class NoProviderAvailable(CodeFluxError):
    pass


class CircuitOpen(CodeFluxError):
    pass

