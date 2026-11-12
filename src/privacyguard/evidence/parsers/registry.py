"""Select the parser for an evidence format."""

from __future__ import annotations

from .base import EvidenceParser
from .json_parser import JsonEvidenceParser
from .log import LogEvidenceParser
from .sql import SqlEvidenceParser
from .txt import TxtEvidenceParser
from ..models import EvidenceFormat

_PARSERS: dict[EvidenceFormat, EvidenceParser] = {
    EvidenceFormat.SQL: SqlEvidenceParser(),
    EvidenceFormat.JSON: JsonEvidenceParser(),
    EvidenceFormat.LOG: LogEvidenceParser(),
    EvidenceFormat.TXT: TxtEvidenceParser(),
}


def parser_for(evidence_format: EvidenceFormat) -> EvidenceParser | None:
    return _PARSERS.get(evidence_format)
