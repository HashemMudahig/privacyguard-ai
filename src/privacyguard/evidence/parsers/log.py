"""Log evidence parser.

Supports the log shapes observed in the dataset:

- logfmt: ``timestamp level=... service=... key="value"``
- pipe: ``timestamp | LEVEL | service | trace | event | key="value"``
- bracket: ``timestamp [LEVEL] [service] [trace] event: key="value"``
- JSON-lines with a leading timestamp: ``timestamp {"severity": ...}``
- syslog-style with a leading priority and key/value tail
- nested ``message="..."`` payloads

Lines without any resource or identifier are skipped as non-evidence noise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..errors import EvidenceParseError
from ..identifiers import (
    derive_state,
    excerpt,
    extract_identifiers,
    scalar_attributes,
)
from ..models import (
    EvidenceFormat,
    EvidenceLocation,
    EvidenceManifestEntry,
    EvidenceObservation,
    ObservedState,
)
from .base import ObservationBuilder, ParseOutcome

_TIMESTAMP_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s*"
)
_PAIR_RE = re.compile(
    r'(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)=(?P<value>"(?:[^"\\]|\\.)*"|\'[^\']*\'|[^\s]+)'
)
_BRACKET_RE = re.compile(
    r"^\[(?P<level>[^\]]+)\]\s+\[(?P<service>[^\]]+)\]\s+"
    r"\[(?P<trace>[^\]]+)\]\s+(?P<event>[^\s:]+):\s*(?P<rest>.*)$"
)
_SYSLOG_RE = re.compile(
    r"^<\d+>\d+\s+\S+\s+(?P<service>\S+)\s+(?P<trace>\S+)\s+-\s+-\s+(?P<rest>.*)$"
)
_LEVEL_TOKENS = {"DEBUG", "INFO", "WARN", "WARNING", "ERROR", "TRACE", "FATAL", "CRITICAL"}


class LogEvidenceParser:
    format = EvidenceFormat.LOG

    def parse(self, entry: EvidenceManifestEntry, dataset_dir: Path) -> ParseOutcome:
        try:
            text = entry.resolved_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise EvidenceParseError(f"Cannot read log file {entry.file_path}: {exc}") from exc

        builder = ObservationBuilder(entry, EvidenceFormat.LOG)
        observations: list[EvidenceObservation] = []
        warnings: list[str] = []
        skipped = 0
        timestamped_lines = 0

        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            parsed = _parse_line(line)
            if parsed is None:
                warnings.append(f"Line {line_number}: missing or invalid timestamp")
                continue
            timestamped_lines += 1
            timestamp, fields, bare, style = parsed
            if bare:
                if str(bare[0]).upper() in _LEVEL_TOKENS:
                    fields.setdefault("level", bare[0])
                elif "event" not in fields:
                    fields["event"] = bare[-1]
            if "service" not in fields and style == "pipe" and len(bare) >= 2:
                fields["service"] = bare[1]

            if "message" in fields and isinstance(fields["message"], str):
                inner_pairs, _inner_bare = _parse_pairs(fields["message"])
                for key, value in inner_pairs.items():
                    fields.setdefault(key, value)
                fields["_message_raw"] = fields["message"]
                del fields["message"]

            service = _text(fields.get("service")) or _text(fields.get("function")) or _text(
                fields.get("logger")
            )
            system_id = (
                _text(fields.get("system"))
                or _text(fields.get("data_store"))
                or _text(fields.get("target_system"))
                or service
            )
            resource_id = _text(fields.get("resource_id")) or _text(
                fields.get("target_resource")
            )
            category = (
                _text(fields.get("record_type"))
                or _text(fields.get("data_category"))
                or _text(fields.get("collection"))
                or _text(fields.get("category"))
            )
            buckets = extract_identifiers(fields)
            if not resource_id and not (
                buckets.user_ids
                or buckets.emails
                or buckets.phones
                or buckets.email_hashes
                or buckets.related_resource_ids
            ):
                skipped += 1
                continue

            event = _text(fields.get("event"))
            state, state_field = derive_state(fields, event=event)
            attributes = scalar_attributes(fields)
            attributes["_style"] = style
            attributes["_line"] = line_number

            observations.append(
                builder.build(
                    system_id=system_id,
                    resource_id=resource_id,
                    data_category=category,
                    observed_state=state,
                    state_field=state_field,
                    identifiers=buckets,
                    record=fields,
                    attributes=attributes,
                    location=EvidenceLocation(
                        line_number=line_number,
                        raw_excerpt=excerpt(line),
                    ),
                    observed_at=timestamp,
                    confidence=_confidence_for(style),
                    warnings=(),
                )
            )

        metadata = {
            "skipped_lines": str(skipped),
            "timestamped_lines": str(timestamped_lines),
        }
        if not observations:
            warnings.append("No evidence-relevant log lines were found")

        return ParseOutcome(
            observations=tuple(observations),
            warnings=tuple(warnings),
            recognized=timestamped_lines > 0,
            metadata=metadata,
        )


def _parse_line(
    line: str,
) -> tuple[str, dict[str, Any], list[str], str] | None:
    match = _TIMESTAMP_RE.match(line)
    if not match:
        return None
    timestamp = match.group("timestamp")
    rest = line[match.end() :].strip()
    if not rest:
        return timestamp, {}, [], "logfmt"

    if rest.startswith("{"):
        try:
            payload = json.loads(rest)
        except json.JSONDecodeError:
            return timestamp, {}, [], "jsonl"
        if not isinstance(payload, dict):
            return timestamp, {}, [], "jsonl"
        return timestamp, {str(key): value for key, value in payload.items()}, [], "jsonl"

    if " | " in rest:
        parts = [part.strip() for part in rest.split(" | ")]
        fields: dict[str, Any] = {}
        bare: list[str] = []
        for part in parts:
            if "=" in part:
                pairs, extra = _parse_pairs(part)
                fields.update(pairs)
                bare.extend(extra)
            else:
                bare.append(part)
        if len(bare) >= 4:
            fields.setdefault("level", bare[0])
            fields.setdefault("service", bare[1])
            fields.setdefault("trace_id", bare[2])
            fields.setdefault("event", bare[3])
        return timestamp, fields, bare, "pipe"

    bracket = _BRACKET_RE.match(rest)
    if bracket:
        fields, bare = _parse_pairs(bracket.group("rest"))
        fields.setdefault("level", bracket.group("level"))
        fields.setdefault("service", bracket.group("service"))
        fields.setdefault("trace_id", bracket.group("trace"))
        fields.setdefault("event", bracket.group("event"))
        return timestamp, fields, bare, "bracket"

    syslog = _SYSLOG_RE.match(rest)
    if syslog:
        fields, bare = _parse_pairs(syslog.group("rest"))
        fields.setdefault("service", syslog.group("service"))
        fields.setdefault("trace_id", syslog.group("trace"))
        return timestamp, fields, bare, "syslog"

    fields, bare = _parse_pairs(rest)
    return timestamp, fields, bare, "logfmt"


def _parse_pairs(text: str) -> tuple[dict[str, Any], list[str]]:
    fields: dict[str, Any] = {}
    spans: list[tuple[int, int]] = []
    for match in _PAIR_RE.finditer(text):
        key = match.group("key")
        fields[key] = _unquote(match.group("value"))
        spans.append(match.span())
    if not spans:
        return fields, text.split() if text.strip() else []

    remainder_parts: list[str] = []
    cursor = 0
    for start, end in spans:
        remainder_parts.append(text[cursor:start])
        cursor = end
    remainder_parts.append(text[cursor:])
    remainder = " ".join(remainder_parts).split()
    return fields, remainder


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        if text[0] == '"':
            try:
                decoded = json.loads(text)
                if isinstance(decoded, str):
                    return decoded
            except json.JSONDecodeError:
                pass
        return text[1:-1].replace('\\"', '"')
    return text


def _confidence_for(style: str) -> float:
    return {
        "jsonl": 0.95,
        "bracket": 0.9,
        "pipe": 0.9,
        "logfmt": 0.9,
        "syslog": 0.8,
    }.get(style, 0.8)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
