"""Normalized event schema shared by every collector."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def _collected_at():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Event:
    """One normalized event, source-agnostic.

    Dates are ISO-8601 strings (YYYY-MM-DD) so they sort and compare as
    plain strings; `time` is HH:MM when the source exposes a start time.
    """

    source: str
    source_event_id: str
    title: str
    venue_name: str = ""
    venue_raw: str = ""
    date_start: str | None = None
    date_end: str | None = None
    time: str | None = None
    is_free: bool | None = None
    price_text: str | None = None
    price_min: float | None = None
    currency: str | None = None
    ticket_url: str | None = None
    seller: str | None = None
    image_url: str | None = None
    city: str = "Mar del Plata"
    raw_url: str | None = None
    collected_at: str = field(default_factory=_collected_at)

    def to_dict(self):
        return asdict(self)
