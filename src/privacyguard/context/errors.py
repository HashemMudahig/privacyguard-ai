"""Audit context errors."""

from __future__ import annotations

from ..errors import PrivacyGuardError


class AuditContextError(PrivacyGuardError):
    """Raised when a case cannot be loaded or inspected."""
