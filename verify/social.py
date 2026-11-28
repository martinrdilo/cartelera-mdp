"""Browser check for social post links: does the post open for a stranger?

The pipeline cannot answer that on its own. Over HTTP, a live Instagram post
and one the publishing account restricted answer the same login wall
(`<title>Instagram</title>`, 537 KB, measured 2026-11-28), and
`/api/v1/media/<id>/info/` answers `401 require_login` for both. The rendered
page does differ: with no session, a restricted post renders
`Post isn't available • Instagram` while a live one renders its own page.

So this command opens every post permalink the snapshot carries in a browser
context with no cookies and records one verdict per URL in
`data/social_post_checks.json`. The build refuses only the URLs a verdict marks
unavailable (`lib/social_posts.py`), which is the difference between "publish
the post the club announced" and "publish a link that reads 'not available'".

Opt-in by design: it needs Playwright (`pip install playwright` plus
`playwright install chromium`), which the deploy pipeline does not have. The
verdicts are committed instead, so a deploy never depends on reaching Instagram.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from lib.social_posts import (
    SCHEMA,
    VERDICT_UNKNOWN,
    merge_verdicts,
    post_urls,
    verdict_from_title,
)

CHECK_FILE = "social_post_checks.json"
DEFAULT_TIMEOUT_MS = 25_000
AUTH_STATE_HINT = (
    "playwright is not installed: pip install playwright && playwright install chromium"
)


def posts_to_check(data_dir: Path) -> list[str]:
    """Every social post permalink the snapshot points at."""
    events = []
    normalized = data_dir / "events_normalized.json"
    if normalized.exists():
        events += json.loads(normalized.read_text(encoding="utf-8"))
    deduped = data_dir / "events_deduped.json"
    if deduped.exists():
        payload = json.loads(deduped.read_text(encoding="utf-8"))
        for cluster in payload.get("clusters") or []:
            events += cluster.get("events") or []
    return post_urls(events)


def check_urls(urls, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict:
    """One verdict per URL, read from the page a stranger gets."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(AUTH_STATE_HINT) from exc

    verdicts: dict[str, str] = {}
    with sync_playwright() as playwright:
        # A fresh context holds no cookies: that is the visitor this site serves.
        browser = playwright.chromium.launch()
        context = browser.new_context(locale="es-AR")
        page = context.new_page()
        try:
            for url in urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(1_500)
                    verdicts[url] = verdict_from_title(page.title())
                except Exception:
                    # A timeout or a navigation error is not evidence either way.
                    verdicts[url] = VERDICT_UNKNOWN
        finally:
            context.close()
            browser.close()
    return verdicts


def run(data_dir: Path, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict:
    """Check every post, merge with the recorded verdicts and write the file."""
    url_list = posts_to_check(data_dir)
    fresh = check_urls(url_list, timeout_ms=timeout_ms) if url_list else {}
    target = data_dir / CHECK_FILE
    previous = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
    payload = merge_verdicts(
        previous,
        fresh,
        checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    payload["schema"] = SCHEMA
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
