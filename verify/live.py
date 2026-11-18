"""Network checks: link liveness and live contrast against the current source.

Opt-in by design: the offline suite never reaches the network. `live` re-runs
one collector and compares the result with the committed snapshot, which is
the only faithful way to ask "does the published data still match the source?".
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

import requests

from collectors import muchticket
from run_pipeline import MODULES

from .core import Finding, event_dict, event_ref
from .rebuild import MODULE_SOURCES, compare_events

USER_AGENT = "cartelera-mdp-verifier/1.0"

SOURCE_MODULE = {source: name for name, sources in MODULE_SOURCES.items() for source in sources}


def _urls(events) -> list[str]:
    urls = []
    for event in events:
        row = event_dict(event)
        for field in ("ticket_url", "raw_url"):
            value = row.get(field)
            if isinstance(value, str) and value and value not in urls:
                urls.append(value)
    return urls


def check_links(events, timeout: float = 10.0, delay: float = 0.2, limit: int | None = None, session=None):
    """Fetch every unique ticket/source URL and report dead or moved links."""
    session = session or requests.Session()
    urls = _urls(events)
    if limit is not None:
        urls = urls[:limit]

    findings: list[Finding] = []
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            findings.append(
                Finding("link.bad_scheme", "error", f"{url} is not an http(s) URL", {"url": url})
            )
            continue
        try:
            response = session.get(
                url,
                timeout=timeout,
                allow_redirects=True,
                headers={"User-Agent": USER_AGENT},
                stream=True,
            )
            status = response.status_code
            final = response.url
            response.close()
        except requests.RequestException as exc:
            findings.append(
                Finding(
                    "link.request_failed",
                    "error",
                    f"{url} failed: {type(exc).__name__}",
                    {"url": url, "error": type(exc).__name__},
                )
            )
            continue

        if status >= 400:
            findings.append(
                Finding(
                    "link.http_error",
                    "error",
                    f"{url} -> HTTP {status}",
                    {"url": url, "status": status},
                )
            )
        else:
            final_parsed = urlparse(final)
            original_segments = [segment for segment in parsed.path.split("/") if segment]
            final_segments = [segment for segment in final_parsed.path.split("/") if segment]
            moved = final_parsed.netloc != parsed.netloc
            collapsed = len(original_segments) > 1 and len(final_segments) <= 1
            if moved or collapsed:
                findings.append(
                    Finding(
                        "link.redirect",
                        "warning",
                        f"{url} redirects to {final}",
                        {"url": url, "final": final},
                    )
                )
        if delay:
            time.sleep(delay)
    return findings


def live_source(source: str, stored_events) -> list[Finding]:
    """Collect one source now and diff it against the committed snapshot."""
    if source not in SOURCE_MODULE:
        return [
            Finding("live.unknown_source", "error", f"unknown source {source!r}", {"source": source})
        ]
    module = dict(MODULES)[SOURCE_MODULE[source]]
    try:
        raw = module.collect()
        events = module.normalize(raw)
        if module is muchticket:
            muchticket.enrich_occurrences(events, raw)
    except Exception as exc:  # network, HTTP, decode or parse failure
        return [
            Finding(
                "live.collect_failed",
                "error",
                f"{source} collection failed: {type(exc).__name__}: {exc}",
                {"source": source},
            )
        ]

    rebuilt = [event for event in events if getattr(event, "source", None) == source]
    stored = [
        event for event in stored_events if event_dict(event).get("source") == source
    ]
    findings = compare_events(stored, rebuilt)
    findings.append(
        Finding(
            "live.collected",
            "info",
            f"{source}: collected {len(rebuilt)} event(s), snapshot has {len(stored)}",
            {"source": source, "collected": len(rebuilt), "stored": len(stored)},
        )
    )
    return findings
