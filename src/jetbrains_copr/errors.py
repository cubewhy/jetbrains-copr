"""Project-specific exception types."""


class JetbrainsCoprError(Exception):
    """Base exception for the project."""


class ConfigError(JetbrainsCoprError):
    """Raised when the product configuration is invalid."""


class ApiError(JetbrainsCoprError):
    """Raised when the JetBrains API cannot be queried or parsed."""


class StateError(JetbrainsCoprError):
    """Raised when release state cannot be loaded or saved."""


class PackagingError(JetbrainsCoprError):
    """Raised when source preparation or RPM building fails."""


class PublishingError(JetbrainsCoprError):
    """Raised when COPR publishing fails."""


class SetupError(JetbrainsCoprError):
    """Raised when required local tooling is missing."""
