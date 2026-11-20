"""Domain errors raised by the GitHub extractor."""

from __future__ import annotations


class MissingTokenError(Exception):
    """Indicate that no GitHub token was supplied."""

    def __init__(self, message: str = "A token is required") -> None:
        """Initialise the error with a safe message."""
        super().__init__(message)


class MissingOrgNameError(Exception):
    """Indicate that no organisation name was supplied."""

    def __init__(self, message: str = "An organisation name is required") -> None:
        """Initialise the error with a safe message."""
        super().__init__(message)


class AuthenticationError(Exception):
    """Indicate that GitHub rejected authentication."""

    def __init__(self, message: str = "Authentication failed") -> None:
        """Initialise the error with a safe message."""
        super().__init__(message)


class RateLimitExceededError(Exception):
    """Indicate that GitHub has rate limited the request."""

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        """Initialise the error with a safe message."""
        super().__init__(message)


class ForbiddenError(Exception):
    """Indicate that GitHub denied access to a resource."""

    def __init__(self, message: str = "Forbidden") -> None:
        """Initialise the error with a safe message."""
        super().__init__(message)


class NotFoundError(Exception):
    """Indicate that a GitHub resource was not found."""

    def __init__(self, message: str = "Not found") -> None:
        """Initialise the error with a safe message."""
        super().__init__(message)


class RequestTimeoutError(Exception):
    """Indicate that a GitHub request timed out."""

    def __init__(self, message: str = "Request timed out") -> None:
        """Initialise the error with a safe message."""
        super().__init__(message)


class RequestError(Exception):
    """Indicate that a GitHub request failed."""

    def __init__(self, message: str = "Request failed") -> None:
        """Initialise the error with a safe message."""
        super().__init__(message)


class ResourceStatusError(RequestError):
    """Indicate a resource status that a resource walk may record."""

    def __init__(self, status: int, message: str) -> None:
        """Initialise the error with its HTTP status and safe message."""
        super().__init__(message)
        self.status = status
