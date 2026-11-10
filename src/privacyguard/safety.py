"""Path-safety helpers.

PrivacyGuard AI must never write outside its own project directory. The
original challenge repository and its dataset are strictly read-only.
"""

from __future__ import annotations

from pathlib import Path

from .errors import UnsafePathError


def ensure_within(root: Path, target: Path) -> Path:
    """Return a resolved target path if it is inside ``root``."""
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if not resolved_target.is_relative_to(resolved_root):
        raise UnsafePathError(
            f"Refusing to write outside {resolved_root}: {resolved_target}"
        )
    return resolved_target


def ensure_writable_report(project_root: Path, target: Path) -> Path:
    """Validate that a report path lives inside the project root."""
    return ensure_within(project_root, target)
