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
