"""Shared primitives for the data verifier.

The verifier is read-only: it never mutates `data/` or `site/`. Every check
returns `Finding` objects so the CLI, the tests and a future tool share one
shape.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

VERSION = 1

SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class VerifyInputError(RuntimeError):
    """The snapshot the verifier needs is missing or unreadable."""


@dataclass(frozen=True)
class Finding:
    """One detected problem, with machine-readable evidence."""

    check: str
    severity: str
    message: str
    evidence: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.severity not in SEVERITY_RANK:
            raise ValueError(f"unknown severity: {self.severity!r}")

    def to_dict(self) -> dict:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass
class Report:
    """Accumulated findings plus the metadata printed around them."""

    findings: list[Finding] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def extend(self, findings) -> None:
        self.findings.extend(findings)

    @property
    def errors(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "warning"]

    def exit_code(self, strict: bool = False) -> int:
        if self.errors or (strict and self.warnings):
            return 1
        return 0

    def to_dict(self) -> dict:
        return {
            "version": VERSION,
            "generated_at": self.meta.get("generated_at")
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scope": self.meta.get("scope", ""),
            "summary": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "findings": len(self.findings),
            },
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def render(self) -> str:
        payload = self.to_dict()
        lines = [f"cartelera-mdp verify · {payload['generated_at']}"]
        scope = payload.get("scope")
        if scope:
            lines.append(scope)

        grouped: dict[str, list[Finding]] = defaultdict(list)
        for finding in self.findings:
            grouped[finding.check].append(finding)
        ordered = sorted(
            grouped.items(),
            key=lambda item: (SEVERITY_RANK[item[1][0].severity], item[0]),
        )
        for check, group in ordered:
            lines.append(f"{group[0].severity.upper():7} {check} ({len(group)})")
            for finding in group[:8]:
                lines.append(f"        {finding.message}")
            if len(group) > 8:
                lines.append(f"        … {len(group) - 8} more (use --json for the full report)")

        if not self.findings:
            lines.append("OK - no findings")
        lines.append("")
        lines.append(
            f"{len(self.errors)} error(s), {len(self.warnings)} warning(s), "
            f"{len(self.findings)} finding(s)"
        )
        return "\n".join(lines)


def event_ref(event) -> str:
    """Stable reference for a normalized event or a raw site row."""
    if hasattr(event, "source_event_id"):
        return f"{event.source}:{event.source_event_id}"
    return f"{event.get('source')}:{event.get('source_event_id')}"


def event_dict(event) -> dict:
    """Plain dict for an `Event` dataclass or an already-serialized row."""
    return event.to_dict() if hasattr(event, "to_dict") else dict(event)


def parse_iso_date(value):
    """Return a `date` for a strict YYYY-MM-DD string, else None."""
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def load_json(path: Path):
    """Read a JSON file, raising VerifyInputError with the real reason."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VerifyInputError(f"missing file: {path}") from exc
    except (OSError, ValueError) as exc:
        raise VerifyInputError(f"cannot read {path}: {exc}") from exc
