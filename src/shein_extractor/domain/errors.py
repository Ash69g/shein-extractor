class CartExtractionError(RuntimeError):
    """Base error raised when a shared cart cannot be extracted."""


class ExpiredShareLinkError(CartExtractionError):
    """Raised when the SHEIN share link is no longer valid."""


class InvalidProcessingInputError(ValueError):
    """Raised when a processing request has no single valid SHEIN cart URL."""
