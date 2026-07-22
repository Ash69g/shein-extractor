class CartExtractionError(RuntimeError):
    """Base error raised when a shared cart cannot be extracted."""


class ExpiredShareLinkError(CartExtractionError):
    """Raised when the SHEIN share link is no longer valid."""

