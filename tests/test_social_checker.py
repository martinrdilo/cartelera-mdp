"""The browser checker targets exactly the post links the snapshot carries."""

import json

from verify import social


def test_every_post_permalink_is_checked_once(tmp_path):
    post = "https://www.instagram.com/p/Dfpe3r7ghri/"
    (tmp_path / "events_normalized.json").write_text(
        json.dumps(
            [
                {"source": "clubtri", "raw_url": post},
                {"source": "clubtri", "raw_url": "https://clubtri.com/"},
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "events_deduped.json").write_text(
        json.dumps({"clusters": [{"events": [{"source": "clubtri", "raw_url": post}]}]}),
        encoding="utf-8",
    )
    assert social.posts_to_check(tmp_path) == [post]


def test_a_snapshot_without_posts_checks_nothing(tmp_path):
    (tmp_path / "events_normalized.json").write_text(
        json.dumps([{"source": "clubtri", "raw_url": "https://clubtri.com/"}]), encoding="utf-8"
    )
    (tmp_path / "events_deduped.json").write_text(json.dumps({"clusters": []}), encoding="utf-8")
    assert social.posts_to_check(tmp_path) == []


def test_a_run_that_could_not_decide_leaves_the_file_untouched(tmp_path, monkeypatch):
    # A blocked runner answers "unknown" for everything. Rewriting the file
    # would move checked_at, claim a check that never happened, and make the
    # scheduled job commit a timestamp every single day.
    previous = {
        "schema": social.SCHEMA,
        "verdicts": {"https://www.instagram.com/p/AAA/": "available"},
        "checked_at": "2026-11-28T14:50:50+00:00",
    }
    target = tmp_path / social.CHECK_FILE
    target.write_text(json.dumps(previous, indent=2) + "\n", encoding="utf-8")
    (tmp_path / "events_normalized.json").write_text(
        json.dumps([{"raw_url": "https://www.instagram.com/p/AAA/"}]), encoding="utf-8"
    )
    monkeypatch.setattr(
        social, "check_urls", lambda urls, timeout_ms=0: {urls[0]: "unknown"}
    )
    before = target.read_bytes()
    social.run(tmp_path)
    assert target.read_bytes() == before


def test_a_run_that_changes_a_verdict_rewrites_the_file(tmp_path, monkeypatch):
    previous = {
        "schema": social.SCHEMA,
        "verdicts": {"https://www.instagram.com/p/AAA/": "available"},
        "checked_at": "2026-11-28T14:50:50+00:00",
    }
    target = tmp_path / social.CHECK_FILE
    target.write_text(json.dumps(previous, indent=2) + "\n", encoding="utf-8")
    (tmp_path / "events_normalized.json").write_text(
        json.dumps([{"raw_url": "https://www.instagram.com/p/AAA/"}]), encoding="utf-8"
    )
    monkeypatch.setattr(
        social, "check_urls", lambda urls, timeout_ms=0: {urls[0]: "unavailable"}
    )
    payload = social.run(tmp_path)
    assert payload["verdicts"]["https://www.instagram.com/p/AAA/"] == "unavailable"
    assert json.loads(target.read_text(encoding="utf-8"))["verdicts"] == payload["verdicts"]


def test_a_snapshot_without_posts_never_empties_the_recorded_verdicts(tmp_path, monkeypatch):
    # The realistic source-down path: nothing collected, nothing to open. The
    # verdict file must survive untouched, or the scheduled commit would push
    # an emptied record.
    previous = {
        "schema": social.SCHEMA,
        "verdicts": {"https://www.instagram.com/p/AAA/": "available"},
        "checked_at": "2026-11-28T14:50:50+00:00",
    }
    target = tmp_path / social.CHECK_FILE
    target.write_text(json.dumps(previous, indent=2) + "\n", encoding="utf-8")
    (tmp_path / "events_normalized.json").write_text(json.dumps([]), encoding="utf-8")
    (tmp_path / "events_deduped.json").write_text(json.dumps({"clusters": []}), encoding="utf-8")
    monkeypatch.setattr(social, "check_urls", lambda urls, timeout_ms=0: {})
    before = target.read_bytes()
    social.run(tmp_path)
    assert target.read_bytes() == before
