"""Identity resolution package."""

from .index import IdentityIndex
from .report import summarize_resolutions, write_json_report
from .resolver import IdentityResolver

__all__ = [
    "IdentityIndex",
    "IdentityResolver",
    "summarize_resolutions",
    "write_json_report",
]
