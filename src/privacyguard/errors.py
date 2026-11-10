"""Domain exceptions for PrivacyGuard AI."""


class PrivacyGuardError(Exception):
    """Base class for all expected PrivacyGuard errors."""


class ConfigError(PrivacyGuardError):
    """Raised when configuration is missing or invalid."""


class DatasetError(PrivacyGuardError):
    """Raised when a dataset file is missing, malformed, or inconsistent."""


class UnsafePathError(PrivacyGuardError):
    """Raised when a write is attempted outside the allowed project root."""
