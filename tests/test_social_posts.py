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
    is_social_account,
    is_social_host,
    is_social_post,
    publishable_social,
    verdict_from_page,
    verdict_from_title,
    verdict_map,
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


def test_only_a_title_that_names_the_post_is_available():
    assert verdict_from_title("Club TRI on Instagram: “CICLO COSTA CANNABIS”") == VERDICT_AVAILABLE
    # A bare "Instagram" is the login wall: reading it as available is the false
    # positive that published a dead link once already.
    assert verdict_from_title("Instagram") == VERDICT_UNKNOWN


def test_a_live_post_behind_the_login_wall_is_available():
    # Measured 2026-11-28: the live post keeps og:title and markup (14 <time>,
    # 26 media) and the error page has none.
    assert verdict_from_page("Instagram", 'Club TRI en Instagram: "x"', True) == VERDICT_AVAILABLE
    assert verdict_from_page("Instagram", "", True) == VERDICT_AVAILABLE
    assert verdict_from_page("Instagram", "", False) == VERDICT_UNKNOWN
    assert verdict_from_page("Post no está disponible • Instagram", "x en Instagram: y", True) == VERDICT_UNAVAILABLE


@pytest.mark.parametrize("title", ("", None, "   "))
def test_a_page_without_a_signal_stays_unknown(title):
    # Never guess: an unknown verdict must not remove a link that works.
    assert verdict_from_title(title) == VERDICT_UNKNOWN


def test_a_reserved_section_root_is_not_an_account_page():
    # /reels/ and /explore/ are one segment too; exempting them from the verdict
    # (as any one-segment path was) publishes them unchecked.
    assert is_social_account("https://www.instagram.com/club.tri/") is True
    for url in (
        "https://www.instagram.com/reels/",
        "https://www.instagram.com/explore/",
        "https://www.instagram.com/p/",
    ):
        assert is_social_account(url) is False, url


def test_publishing_a_post_needs_a_recorded_available_verdict():
    payload = {
        "schema": "cartelera-mdp.social-post-checks/v1",
        "verdicts": {
            "https://www.instagram.com/p/AAA/?img_index=1": VERDICT_AVAILABLE,
            "https://www.instagram.com/p/BBB/": VERDICT_UNAVAILABLE,
            "https://www.instagram.com/p/CCC/": VERDICT_UNKNOWN,
        },
    }
    verdicts = verdict_map(payload)
    # The stored key keeps a query string; the bare permalink still matches it.
    assert publishable_social("https://www.instagram.com/p/AAA/", verdicts) is True
    assert publishable_social("https://www.instagram.com/p/BBB/", verdicts) is False
    assert publishable_social("https://www.instagram.com/p/CCC/", verdicts) is False
    # Never checked: not published. The loose direction is the bug.
    assert publishable_social("https://www.instagram.com/p/DDD/", verdicts) is False


def test_the_account_page_is_the_only_social_url_that_needs_no_verdict():
    assert is_social_host("https://www.instagram.com/reels/audio/1/") is True
    assert is_social_account("https://www.instagram.com/club.tri/") is True
    assert is_social_account("https://www.instagram.com/p/abc/") is False


@pytest.mark.parametrize("payload", (None, {}, {"verdicts": {}}, {"verdicts": "nope"}, []))
def test_a_missing_or_broken_file_decides_nothing(payload):
    assert verdict_map(payload) == {}


@pytest.mark.parametrize(
    "url",
    (
        "https://www.instagram.com/p/Dfpe3r7ghri/",
        "https://www.instagram.com/p/Df5eV8hmEhG/?img_index=1",
        "https://instagram.com/reel/Cabc123/",
        "https://www.instagram.com/tv/Cabc123/",
    ),
)
def test_a_post_permalink_is_recognised(url):
    assert is_social_post(url) is True


@pytest.mark.parametrize(
    "url",
    (
        "https://www.instagram.com/club.tri/",
        "https://www.instagram.com/stories/club.tri/1/",
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
