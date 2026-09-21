class IntelligenceError(Exception):
    """Base error for the Intelligence Layer."""


class AuthorizationError(IntelligenceError):
    """Raised when an actor lacks permission for an operation."""


class ArtifactValidationError(IntelligenceError):
    """Raised when an artifact fails schema or governance validation."""


class LifecycleError(IntelligenceError):
    """Raised when a lifecycle transition is not allowed."""


class ArtifactNotFoundError(IntelligenceError):
    """Raised when an artifact cannot be found."""
