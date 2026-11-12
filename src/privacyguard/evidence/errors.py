"""Evidence-specific exceptions."""

from __future__ import annotations

from ..errors import PrivacyGuardError


class EvidenceError(PrivacyGuardError):
    """Base class for evidence errors."""


class EvidenceManifestError(EvidenceError):
    """Raised when the evidence manifest is invalid."""


class UnsupportedEvidenceError(EvidenceError):
    """Raised when an evidence file format or structure is not recognized."""


class EvidenceParseError(EvidenceError):
    """Raised when a supported evidence file cannot be parsed."""


class UnsupportedSqlConstruct(EvidenceParseError):
    """Raised when a SQL snapshot contains a rejected construct."""
