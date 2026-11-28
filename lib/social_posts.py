"""Social post verdicts: which Instagram posts a logged-out visitor can open.

The club publishes no per-event page -- `clubtri.com` is one page and every card
links out -- so for a free show the announcement post is the only per-event
link that exists. That post can still be invisible to the site's audience: the
access is decided by the account that published it, not by the visitor's
session, and Instagram answers "Post isn't available" to anyone without one.

An HTTP client cannot tell a live post from a restricted one: both answer the
same login wall (`<title>Instagram</title>`, 537 KB, measured 2026-11-28), and
`/api/v1/media/<id>/info/` answers `401 require_login` for both. The rendered
page does differ, so `verify/social.py` opens each post in a browser with no
session and records a verdict here; the build refuses only the URLs a verdict
marks unavailable, which keeps the posts that do open.
"""

from __future__ import annotations

import unicodedata
from urllib.parse import urlparse

SCHEMA = "cartelera-mdp.social-post-checks/v1"
VERDICT_AVAILABLE = "available"
VERDICT_UNAVAILABLE = "unavailable"
VERDICT_UNKNOWN = "unknown"
VERDICTS = (VERDICT_AVAILABLE, VERDICT_UNAVAILABLE, VERDICT_UNKNOWN)

# Instagram serves the same hosts for a post and its app deep link.
POST_HOSTS = ("instagram.com",)
# Post permalinks. `/stories/` is here too: a story expires in 24 hours, so it
# is never a durable source, whatever the verdict says.
POST_SECTIONS = ("p", "reel", "tv")
# Section roots that look like an account page but are not one.
RESERVED_SECTIONS = ("p", "reel", "reels", "stories", "tv", "explore", "accounts", "direct")
STORY_SECTION = "stories"

# What the rendered page says when the post is not there for this visitor, in
# the two languages Instagram served us: <title>Post isn't available</title>
# (default locale) and <title>Post no está disponible</title> (es-AR). Compared
# accent-folded, so every spelling of the same sentence matches.
UNAVAILABLE_NEEDLES = (
    "post isn't available",
    "post isn’t available",
    "post no esta disponible",
    "publicacion no esta disponible",
    "page isn't available",
    "pagina no esta disponible",
)


def _fold(text: str) -> str:
    """Lowercase, accent-free, single-spaced: one spelling per sentence."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(plain.casefold().split())


def _parse(url):
    """Parsed URL when it points at a social host, else None."""
    if not isinstance(url, str):
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return None
    host = parsed.netloc.lower().removeprefix("www.")
    if not any(host == own or host.endswith("." + own) for own in POST_HOSTS):
        return None
    return parsed


def _section(url):
    """First path segment of a social URL, or None when it is not one."""
    if not isinstance(url, str):
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return None
    host = parsed.netloc.lower().removeprefix("www.")
    if not any(host == own or host.endswith("." + own) for own in POST_HOSTS):
        return None
    return parsed.path.strip("/").split("/", 1)[0].lower() or None


def is_social_host(url) -> bool:
    """True for any URL on a social host, whatever its path."""
    return _parse(url) is not None


def is_social_account(url) -> bool:
    """True for an account page (/club.tri/), the one social URL always alive.

    A reserved section root -- /reels/, /p/, /explore/ -- is a single segment
    too, and exempting it from the verdict would publish it unchecked.
    """
    parsed = _parse(url)
    if parsed is None:
        return False
    parts = [part for part in parsed.path.split("/") if part]
    return len(parts) == 1 and parts[0].lower() not in RESERVED_SECTIONS


def verdict_key(url):
    """Key without query or fragment: `?img_index=1` is the same post."""
    parsed = _parse(url)
    return None if parsed is None else f"{parsed.scheme}://{parsed.netloc.lower()}{parsed.path}"


def publishable_social(url, verdicts: dict) -> bool:
    """A post is published only when a check opened it; unknown is not fine."""
    return verdicts.get(verdict_key(url)) == VERDICT_AVAILABLE


def is_social_post(url) -> bool:
    """True for a social post permalink (/p/..., /reel/..., /stories/...)."""
    return _section(url) in POST_SECTIONS


def is_social_story(url) -> bool:
    """True for a story permalink: it expires, so it is never a source."""
    return _section(url) == STORY_SECTION


def verdict_from_page(title, og_title="", has_post_markup=False) -> str:
    """Verdict from the page: title, og:title and post markup.

    A bare "Instagram" title is the login wall, not evidence: a live post keeps
    its metadata behind it (`og:title` "<owner> en Instagram: ...", <time> and
    media nodes) and the error page has none (measured 2026-11-28: 14 and 26
    against 0 and 0).
    """
    verdict = verdict_from_title(title)
    if verdict != VERDICT_UNKNOWN:
        return verdict
    folded = _fold(og_title or "")
    if " en instagram" in folded or " on instagram" in folded or has_post_markup:
        return VERDICT_AVAILABLE
    return VERDICT_UNKNOWN


def verdict_from_title(title) -> str:
    """Verdict for one rendered page, read from its document title.

    Only the two signals the page actually gives are read: the "not available"
    title means the post is gone for this visitor, and any other rendered title
    means the page opened. Nothing else is inferred -- a blank or missing title
    is unknown, and an unknown verdict never removes a link.
    """
    if not isinstance(title, str) or not title.strip():
        return VERDICT_UNKNOWN
    folded = _fold(title)
    if any(needle in folded for needle in UNAVAILABLE_NEEDLES):
        return VERDICT_UNAVAILABLE
    # "Club TRI on Instagram: ..." names the post; "Instagram" is the wall.
    if " on instagram" in folded or " en instagram" in folded:
        return VERDICT_AVAILABLE
    return VERDICT_UNKNOWN


def verdict_map(payload) -> dict:
    """Recorded verdicts keyed by `verdict_key`; a broken file decides nothing."""
    verdicts = payload.get("verdicts") if isinstance(payload, dict) else None
    if not isinstance(verdicts, dict):
        return {}
    return {verdict_key(u) or u: v for u, v in verdicts.items() if isinstance(u, str) and v in VERDICTS}


def post_urls(events) -> list[str]:
    """Every social post permalink the snapshot carries, one per URL."""
    found = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        for field in ("raw_url", "ticket_url"):
            if is_social_post(event.get(field)):
                found.add(event[field])
    return sorted(found)


def merge_verdicts(previous, fresh: dict, checked_at: str | None = None) -> dict:
    """Record fresh verdicts, keeping an older one when a run could not decide.

    A flaky or blocked run answers `unknown`, and that must not resurrect a post
    an earlier run saw unavailable: the verdict is kept until a run actually
    opens the page. A fresh `available` always replaces `unavailable`.
    """
    kept = {}
    if isinstance(previous, dict) and isinstance(previous.get("verdicts"), dict):
        kept = {
            url: verdict
            for url, verdict in previous["verdicts"].items()
            if verdict in VERDICTS
        }
    for url, verdict in fresh.items():
        if verdict == VERDICT_UNKNOWN and kept.get(url) in (VERDICT_AVAILABLE, VERDICT_UNAVAILABLE):
            continue
        kept[url] = verdict
    payload = {"schema": SCHEMA, "verdicts": dict(sorted(kept.items()))}
    if checked_at:
        payload["checked_at"] = checked_at
    return payload
