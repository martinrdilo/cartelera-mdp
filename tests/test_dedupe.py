"""Tests for cross-source dedupe (venue+date fingerprint, slug join, fuzzy title)."""

from lib.dedupe import cluster_events, extract_slug, normalize_text, title_similarity
from lib.schema import Event


def make_event(source, title, venue, date_start, ticket_url=None, event_id=None, **overrides):
    fields = dict(
        source=source,
        source_event_id=event_id or title,
        title=title,
        venue_name=venue,
        venue_raw=venue,
        date_start=date_start,
        ticket_url=ticket_url,
    )
    fields.update(overrides)
    return Event(**fields)


class TestNormalizeText:
    def test_lowercase_and_punctuation(self):
        assert normalize_text("DANTE SPINETTA - CLUB TRI") == "dante spinetta club tri"

    def test_strips_accents(self):
        assert normalize_text("Sáb 14 de Octubre") == "sab 14 de octubre"

    def test_collapses_whitespace(self):
        assert normalize_text("  Jam   de  Jazz & Dibujo ") == "jam de jazz dibujo"


class TestExtractSlug:
    def test_articket_slug_with_trailing_slash(self):
        url = "https://articket.com.ar/DANTE-SPINETTA-CLUB-TRI/"
        assert extract_slug(url) == "articket.com.ar:dante-spinetta-club-tri"

    def test_articket_slug_without_trailing_slash(self):
        url = "https://articket.com.ar/DANTE-SPINETTA-CLUB-TRI"
        assert extract_slug(url) == "articket.com.ar:dante-spinetta-club-tri"

    def test_passline_slug(self):
        url = "https://www.passline.com/eventos/flaco-vazquez-mar-del-plata-5359"
        assert extract_slug(url) == "www.passline.com:flaco-vazquez-mar-del-plata-5359"

    def test_instagram_is_not_a_ticket_slug(self):
        assert extract_slug("https://www.instagram.com/p/Dd7bsectNjW/") is None

    def test_empty_url(self):
        assert extract_slug(None) is None
        assert extract_slug("") is None


class TestTitleSimilarity:
    def test_subset_titles_score_high(self):
        score = title_similarity("Dante Spinetta en Club TRI", "DANTE SPINETTA - CLUB TRI")
        assert score >= 85

    def test_unrelated_titles_score_low(self):
        score = title_similarity("Jam de Jazz & Dibujo", "MALA SANGRE 40 AÑOS DE OKTUBRE")
        assert score < 85


class TestClusterEvents:
    def test_same_slug_joins_exactly(self):
        a = make_event(
            "clubtri", "Dante Spinetta en Club TRI", "Club TRI", "2026-11-14",
            ticket_url="https://articket.com.ar/DANTE-SPINETTA-CLUB-TRI",
        )
        b = make_event(
            "articket", "DANTE SPINETTA - CLUB TRI", "Club TRI", "2026-11-14",
            ticket_url="https://articket.com.ar/DANTE-SPINETTA-CLUB-TRI/",
        )
        clusters = cluster_events([a, b])
        assert len(clusters) == 1
        assert clusters[0]["pairs"][0]["kind"] == "ticket_slug"

    def test_fuzzy_title_joins_within_same_venue_and_date(self):
        a = make_event("municipal", "Dante Spinetta", "Club TRI", "2026-11-14")
        b = make_event("articket", "DANTE SPINETTA - CLUB TRI", "Club TRI", "2026-11-14")
        clusters = cluster_events([a, b])
        assert len(clusters) == 1
        assert clusters[0]["pairs"][0]["kind"] == "title_fuzzy"
        assert clusters[0]["pairs"][0]["score"] >= 85

    def test_date_prefix_noise_does_not_fake_a_match(self):
        # CultuTickets embeds "VIER 16 DE OKTUBRE MDP" in the title; it must
        # not make an unrelated same-venue same-date event look similar.
        a = make_event("municipal", "Oktubre MdP", "Brew House", "2026-10-16")
        b = make_event(
            "cultutickets", "VIER 16 DE OKTUBRE MDP UNA OBRA REDONDA",
            "Ciudad Cultural Brew House", "2026-10-16",
        )
        assert cluster_events([a, b]) == []

    def test_date_prefix_noise_is_stripped_for_matching(self):
        a = make_event("municipal", "Una Obra Redonda en Brew House", "Brew House", "2026-10-16")
        b = make_event(
            "cultutickets", "VIER 16 DE OKTUBRE MDP UNA OBRA REDONDA",
            "Ciudad Cultural Brew House", "2026-10-16",
        )
        assert len(cluster_events([a, b])) == 1

    def test_same_venue_and_date_but_different_show_stays_split(self):
        a = make_event("clubtri", "Jam de Jazz & Dibujo", "Club TRI", "2026-10-15")
        b = make_event("articket", "MALA SANGRE 40 AÑOS DE OKTUBRE", "Club TRI", "2026-10-15")
        assert cluster_events([a, b]) == []

    def test_same_title_different_venue_stays_split(self):
        a = make_event("municipal", "Abel Pintos", "Teatro Tronador", "2026-11-07")
        b = make_event("articket", "Abel Pintos", "Teatro Colón", "2026-11-07")
        assert cluster_events([a, b]) == []

    def test_same_title_same_venue_different_date_stays_split(self):
        a = make_event("clubtri", "Dante Spinetta en Club TRI", "Club TRI", "2026-11-14")
        b = make_event("articket", "DANTE SPINETTA - CLUB TRI", "Club TRI", "2026-11-15")
        assert cluster_events([a, b]) == []

    def test_venue_normalization_ignores_accents_and_case(self):
        a = make_event("municipal", "Abel Pintos", "TEATRO MUNICIPAL COLÓN", "2026-11-07")
        b = make_event("articket", "ABEL PINTOS", "Teatro Municipal Colon", "2026-11-07")
        assert len(cluster_events([a, b])) == 1

    def test_venue_aliases_join_cross_source_spellings(self):
        a = make_event("municipal", "Rey Garufa", "Brew House", "2026-12-05")
        b = make_event("cultutickets", "REY GARUFA", "Ciudad Cultural Brew House", "2026-12-05")
        assert len(cluster_events([a, b])) == 1

    def test_events_without_date_are_ignored(self):
        a = make_event("municipal", "Sin fecha", "Club TRI", None)
        b = make_event("articket", "Sin fecha", "Club TRI", None)
        assert cluster_events([a, b]) == []

    def test_three_way_cluster_reports_pair_evidence(self):
        a = make_event("municipal", "Dante Spinetta", "Club TRI", "2026-11-14")
        b = make_event(
            "clubtri", "Dante Spinetta en Club TRI", "Club TRI", "2026-11-14",
            ticket_url="https://articket.com.ar/DANTE-SPINETTA-CLUB-TRI",
        )
        c = make_event(
            "articket", "DANTE SPINETTA - CLUB TRI", "Club TRI", "2026-11-14",
            ticket_url="https://articket.com.ar/DANTE-SPINETTA-CLUB-TRI/",
        )
        clusters = cluster_events([a, b, c])
        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 3
        kinds = {p["kind"] for p in clusters[0]["pairs"]}
        assert "ticket_slug" in kinds
