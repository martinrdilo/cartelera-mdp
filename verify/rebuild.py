"""Re-derive the normalized snapshot from the collector payloads in `data/raw/`.

`data/raw/` is gitignored and only exists after a pipeline run, so this layer
is offline but optional. It answers one question: given the exact same raw
payload, does the committed `events_normalized.json` still come out the same?

That catches hand edits to the snapshot and parser drift in `lib/` (dates,
occurrences, price, seller), not bad data from the source.
"""

from __future__ import annotations

from pathlib import Path

from lib.schema import Event
from run_pipeline import MODULES

from .core import Finding, VerifyInputError, event_dict, event_ref, load_json, parse_iso_date

# One pipeline module can emit several source names.
MODULE_SOURCES = {
    "municipal": {"municipal"},
    "muchticket": {"articket", "cultutickets"},
    "clubtri": {"clubtri"},
    "venti": {"venti"},
    "ticketek": {"ticketek"},
    "bombo": {"bombo"},
    "punto": {"punto"},
    "auditorium": {"auditorium"},
    "colon": {"colon"},
    "tuentrada": {"tuentrada"},
    "cualpinta": {"cualpinta"},
    "elevenflow": {"elevenflow"},
    "passline": {"passline"},
    "quehacemos": {"quehacemos"},
    "fanz": {"chauvin"},
}

KNOWN_SOURCES = frozenset(source for sources in MODULE_SOURCES.values() for source in sources)

AUDITED_FIELDS = tuple(field for field in Event.__dataclass_fields__ if field != "collected_at")

# Articket multi-date events get their occurrences and date_end from a
# detail-page fetch in the pipeline's enrichment pass, which is network-only.
# Offline rebuild cannot reproduce them, so those fields are exempt per event.
_UNREDERIVABLE = ("occurrences", "date_end", "multi_date_incomplete")


def ref(event) -> str:
    return event_ref(event)


def as_dict(event) -> dict:
    return event_dict(event)


def load_raw_modules(data_dir, modules=MODULES):
    """Return (raw_by_module, present_sources, missing_sources)."""
    raw_dir = Path(data_dir) / "raw"
    raw_by_module = {}
    present = set()
    missing = set()
    for name, _module in modules:
        sources = MODULE_SOURCES[name]
        records = []
        found = set()
        for source in sorted(sources):
            path = raw_dir / f"{source}.json"
            if not path.exists():
                continue
            payload = load_json(path)
            if not isinstance(payload, list):
                raise VerifyInputError(f"{path} is not a JSON list")
            records.extend(payload)
            found.add(source)
        if found:
            raw_by_module[name] = records
        missing.update(sources - found)
        present.update(found)
    return raw_by_module, present, missing


def _articket_exemptions(raw_by_module) -> dict[str, set[str]]:
    exempt = {}
    for record in raw_by_module.get("muchticket", []):
        if record.get("source") == "articket" and record.get("unica_fecha") is False:
            exempt[f"articket:{record.get('slug')}"] = set(_UNREDERIVABLE)
    return exempt


def rebuild_events(data_dir, modules=MODULES):
    """Normalize the stored raw payloads. Returns (events, present, missing, exempt)."""
    raw_by_module, present, missing = load_raw_modules(data_dir, modules)
    events = []
    for name, module in modules:
        records = raw_by_module.get(name)
        if not records:
            continue
        events.extend(module.normalize(records))
    return events, present, missing, _articket_exemptions(raw_by_module)


def _year_shift(before, after) -> bool:
    """True when a date value moved exactly one year, same month and day.

    Several sources publish relative dates ("sábado 14 de noviembre") and
    `lib.dates` infers the year against `date.today()`. Re-deriving the same
    raw payload months later legitimately shifts those dates by one year.
    """
    if isinstance(before, str) and isinstance(after, str):
        first = parse_iso_date(before)
        second = parse_iso_date(after)
        if first and second:
            return (
                first.month == second.month
                and first.day == second.day
                and abs(first.year - second.year) == 1
            )
        return False
    if isinstance(before, list) and isinstance(after, list):
        return len(before) == len(after) and all(
            _year_shift(left, right) for left, right in zip(before, after)
        )
    return False


def compare_events(stored, rebuilt, exempt=None, fields=AUDITED_FIELDS):
    """Compare two normalized event collections by source reference."""
    exempt = exempt or {}
    stored_map = {}
    findings = []
    for event in stored:
        key = ref(event)
        if key in stored_map:
            findings.append(
                Finding(
                    "rebuild.duplicate_ref",
                    "error",
                    f"{key} appears more than once in the committed snapshot",
                    {"ref": key},
                )
            )
            continue
        stored_map[key] = as_dict(event)

    rebuilt_map = {}
    for event in rebuilt:
        key = ref(event)
        if key in rebuilt_map:
            findings.append(
                Finding(
                    "rebuild.duplicate_ref",
                    "error",
                    f"{key} appears more than once when rebuilt from raw",
                    {"ref": key},
                )
            )
            continue
        rebuilt_map[key] = as_dict(event)

    for key in sorted(stored_map.keys() - rebuilt_map.keys()):
        findings.append(
            Finding("rebuild.missing", "error", f"{key} is in the snapshot but not in raw", {"ref": key})
        )
    for key in sorted(rebuilt_map.keys() - stored_map.keys()):
        findings.append(
            Finding("rebuild.extra", "error", f"{key} is in raw but not in the snapshot", {"ref": key})
        )

    for key in sorted(stored_map.keys() & rebuilt_map.keys()):
        stored_event = stored_map[key]
        rebuilt_event = rebuilt_map[key]
        skip = exempt.get(key, set())
        changed = {}
        for field in fields:
            if field in skip:
                continue
            before = stored_event.get(field)
            after = rebuilt_event.get(field)
            if before != after:
                changed[field] = {"stored": before, "rebuilt": after}
        if changed:
            date_fields = set(changed) <= {"date_start", "date_end", "occurrences"}
            time_dependent = date_fields and all(
                _year_shift(stored_event.get(field), rebuilt_event.get(field)) for field in changed
            )
            if time_dependent:
                findings.append(
                    Finding(
                        "rebuild.time_dependent",
                        "warning",
                        f"{key} dates moved one year: re-parsed against today",
                        {"ref": key, "fields": sorted(changed), "values": changed},
                    )
                )
            else:
                findings.append(
                    Finding(
                        "rebuild.changed",
                        "error",
                        f"{key} changed fields: {', '.join(sorted(changed))}",
                        {"ref": key, "fields": sorted(changed), "values": changed},
                    )
                )
    return findings


def check_rebuild(data_dir, normalized, modules=MODULES):
    """Run the rebuild layer and return (findings, meta)."""
    rebuilt, present, missing, exempt = rebuild_events(data_dir, modules)
    if not present:
        return (
            [
                Finding(
                    "rebuild.raw_absent",
                    "info",
                    "data/raw/ is absent (gitignored); rebuild layer skipped",
                )
            ],
            {"sources": 0},
        )
    findings = compare_events(normalized, rebuilt, exempt=exempt)
    if missing:
        findings.append(
            Finding(
                "rebuild.source_absent",
                "info",
                f"raw payload missing for {len(missing)} source(s): {', '.join(sorted(missing))}",
                {"sources": sorted(missing)},
            )
        )
    if exempt:
        findings.append(
            Finding(
                "rebuild.network_derived",
                "info",
                f"{len(exempt)} Articket multi-date event(s) keep network-derived occurrences and date_end",
                {"events": sorted(exempt)[:20], "count": len(exempt)},
            )
        )
    return findings, {"sources": len(present), "events": len(rebuilt)}
