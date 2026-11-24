"""The rule that decides whether a value is a venue's own site.

Both ends of the pipeline use it: `collectors/municipal.py` captures the
external anchor of the municipal panel, and `build_site.py` re-validates the
snapshot value before it becomes a "Sala" link. One module owns the rule so a
fix at one end cannot leave the other rejecting the same URLs.

Standard library only: `build_site.py` imports this module and must stay
importable in a bare interpreter, without requests or bs4.
"""

from urllib.parse import urlparse

# Hosts that belong to the municipality itself, with or without subdomain and
# on both spellings of its domain. A panel often links
# www.mardelplata.gob.ar/cultura next to the venue's mailto:; that is the
# municipality, not the venue, so it never becomes a venue site.
MUNICIPAL_HOSTS = (
    "mardelplata.gob.ar",
    "mardelplata.gov.ar",
    "turismomardelplata.gob.ar",
    "turismomardelplata.gov.ar",
)


def venue_site_url(raw):
    """The venue's own site, normalized, or None when the value is not one.

    Only a real site qualifies: http(s), a dotted host, no credentials and no
    spaces in it, and a host outside the municipality. Live panels also carry
    hrefs that are an address (`http://sala@hotmail.com`), a handle
    (`http://IG feriadeartesanos`), a guttered scheme (`http://https:/host/`)
    or the municipality on the .gov.ar spelling, and none of those is a site.
    """
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate or any(char.isspace() for char in candidate):
        return None
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    netloc = parsed.netloc
    if "@" in netloc or "." not in netloc:
        return None
    host = netloc.split(":", 1)[0].lower().removeprefix("www.")
    if any(host == own or host.endswith("." + own) for own in MUNICIPAL_HOSTS):
        return None
    return candidate
