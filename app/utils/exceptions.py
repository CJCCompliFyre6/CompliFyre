class PDFServiceError(Exception):
    """Base exception for PDF service errors."""

    pass


class URLValidationError(PDFServiceError):
    """Raised when URL validation fails."""

    pass


class PDFDownloadError(PDFServiceError):
    """Raised when PDF download fails."""

    pass


class PDFVerificationError(PDFServiceError):
    """Raised when PDF verification fails."""

    pass


class CacheError(PDFServiceError):
    """Raised when cache operations fail."""

    pass
