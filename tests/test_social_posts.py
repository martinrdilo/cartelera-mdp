"""Social post verdicts: only a post verified unavailable stops being a source.

Instagram answers an HTTP client with the same login wall for a live post and
for one the publishing account restricted (measured 2026-11-28: 537 KB,
`<title>Instagram</title>`), so the pipeline cannot decide by itself. The
rendered page does differ, which is what `verify/social.py` records.
"""

import pytest

from lib.social_posts import (
    VERDICT_AVAILABLE,
    VERDICT_UNAVAILABLE,
    VERDICT_UNKNOWN,
    is_social_post,
    unavailable_urls,
    verdict_from_title,
)


@pytest.mark.parametrize(
    "title",
    (
        "Post isn't available • Instagram",
        "Post isn’t available • Instagram",
        # The es-AR spelling Instagram actually served to the checker on
        # 2026-11-28: an accent-folded marker set is what catches it.
        "Post no está disponible • Instagram",
        "La publicación no está disponible • Instagram",
    ),
)
def test_a_restricted_post_is_read_from_the_rendered_title(title):
    assert verdict_from_title(title) == VERDICT_UNAVAILABLE


def test_a_post_that_renders_its_page_is_available():
    # The shortest signal a logged-out browser gets: the page itself.
    assert verdict_from_title("Club TRI on Instagram: “CICLO COSTA CANNABIS”") == VERDICT_AVAILABLE
    assert verdict_from_title("Instagram") == VERDICT_AVAILABLE


@pytest.mark.parametrize("title", ("", None, "   "))
def test_a_page_without_a_signal_stays_unknown(title):
    # Never guess: an unknown verdict must not remove a link that works.
    assert verdict_from_title(title) == VERDICT_UNKNOWN


def test_only_unavailable_urls_are_blocked():
    payload = {
        "schema": "cartelera-mdp.social-post-checks/v1",
        "checked_at": "2026-11-28T14:00:00+00:00",
        "verdicts": {
            "https://www.instagram.com/p/AAA/": VERDICT_AVAILABLE,
            "https://www.instagram.com/p/BBB/": VERDICT_UNAVAILABLE,
            "https://www.instagram.com/p/CCC/": VERDICT_UNKNOWN,
        },
    }
    assert unavailable_urls(payload) == frozenset({"https://www.instagram.com/p/BBB/"})


@pytest.mark.parametrize("payload", (None, {}, {"verdicts": {}}, {"verdicts": "nope"}, []))
def test_a_missing_or_broken_file_blocks_nothing(payload):
    assert unavailable_urls(payload) == frozenset()


@pytest.mark.parametrize(
    "url",
    (
        "https://www.instagram.com/p/Dfpe3r7ghri/",
        "https://www.instagram.com/p/Df5eV8hmEhG/?img_index=1",
        "https://instagram.com/reel/Cabc123/",
        "https://www.instagram.com/stories/club.tri/3141592653/",
    ),
)
def test_a_post_permalink_is_recognised(url):
    assert is_social_post(url) is True


@pytest.mark.parametrize(
    "url",
    (
        "https://www.instagram.com/club.tri/",
        "https://clubtri.com/",
        "https://puntomardelplata.com/actividades/fiesta-plop-20501",
        None,
        "",
        42,
    ),
)
def test_anything_else_is_not_a_post_permalink(url):
    assert is_social_post(url) is False


def test_a_flaky_run_does_not_resurrect_a_dead_post():
    # A blocked or timed-out run answers "unknown"; it must not overwrite what a
    # run that actually opened the page recorded.
    from lib.social_posts import merge_verdicts

    previous = {
        "schema": "cartelera-mdp.social-post-checks/v1",
        "verdicts": {"https://www.instagram.com/p/BBB/": VERDICT_UNAVAILABLE},
    }
    payload = merge_verdicts(
        previous,
        {
            "https://www.instagram.com/p/BBB/": VERDICT_UNKNOWN,
            "https://www.instagram.com/p/CCC/": VERDICT_AVAILABLE,
        },
        checked_at="2026-11-28T15:00:00+00:00",
    )
    assert payload["verdicts"] == {
        "https://www.instagram.com/p/BBB/": VERDICT_UNAVAILABLE,
        "https://www.instagram.com/p/CCC/": VERDICT_AVAILABLE,
    }
    assert payload["checked_at"] == "2026-11-28T15:00:00+00:00"


def test_a_post_that_comes_back_is_recorded_as_available():
    from lib.social_posts import merge_verdicts

    previous = {"verdicts": {"https://www.instagram.com/p/BBB/": VERDICT_UNAVAILABLE}}
    payload = merge_verdicts(previous, {"https://www.instagram.com/p/BBB/": VERDICT_AVAILABLE})
    assert payload["verdicts"]["https://www.instagram.com/p/BBB/"] == VERDICT_AVAILABLE
