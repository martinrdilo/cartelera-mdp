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

    def test_registry_variant_not_in_the_old_hardcoded_map_joins(self):
        # The Sheraton oddity: the municipal source names the hall, Articket
        # names the hotel. The registry is the source of truth now.
        a = make_event("municipal", "La Vin - Los Totora Tour", "Sheraton Mar del Plata - Auditorium Victoria Ocampo", "2026-10-24")
        b = make_event("articket", "LA VIN - LOS TOTORA TOUR", "Sheraton Mar del Plata", "2026-10-24")
        assert len(cluster_events([a, b])) == 1

    def test_villa_victoria_and_sheraton_hall_do_not_merge(self):
        # Both spellings contain "Victoria Ocampo" but they are different places.
        a = make_event("municipal", "Coro de Cámara", "Villa Victoria Ocampo", "2026-11-07")
        b = make_event("municipal", "Coro de Cámara", "Sheraton Mar del Plata - Auditorium Victoria Ocampo", "2026-11-07")
        assert cluster_events([a, b]) == []

    def test_unknown_venues_fall_back_to_normalized_raw(self):
        a = make_event("municipal", "Peña del Barrio", "Bolichito de la Esquina!", "2026-11-07")
        b = make_event("municipal", "Peña del Barrio", "Bolichito de la esquina", "2026-11-07")
        c = make_event("municipal", "Peña del Barrio", "Otro Bolichito", "2026-11-07")
        clusters = cluster_events([a, b, c])
        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 2

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


class TestClusterEventsByOccurrences:
    def test_occurrence_intersection_joins_multi_date_events(self):
        # Tan Biónica: municipal expands 21+22/11; Articket lists 21/11 only.
        a = make_event(
            "municipal", "Tan Biónica", "Estadio Polideportivo Islas Malvinas", "2026-11-21",
            occurrences=["2026-11-21", "2026-11-22"],
        )
        b = make_event(
            "articket", "TAN BIONICA", "Polideportivo Islas Malvinas", "2026-11-21",
            occurrences=["2026-11-21"],
        )
        assert len(cluster_events([a, b])) == 1

    def test_occurrence_intersection_joins_when_start_dates_differ(self):
        # Abel Pintos: municipal range 07-08/11; the seller lists the second
        # date. The old date_start gate would miss this pair.
        a = make_event(
            "municipal", "Abel Pintos", "Teatro Tronador", "2026-11-07",
            occurrences=["2026-11-07", "2026-11-08"],
        )
        b = make_event("articket", "ABEL PINTOS", "Teatro Tronador", "2026-11-08", occurrences=["2026-11-08"])
        assert len(cluster_events([a, b])) == 1

    def test_disjoint_occurrences_split_even_when_start_dates_match(self):
        a = make_event(
            "municipal", "Orquesta Municipal de Tango", "Teatro Municipal Colón", "2026-10-17",
            occurrences=["2026-10-17"],
        )
        b = make_event(
            "articket", "ORQUESTA MUNICIPAL DE TANGO", "Teatro Municipal Colón", "2026-10-17",
            occurrences=["2026-10-31"],
        )
        assert cluster_events([a, b]) == []

    def test_disjoint_occurrences_stay_split(self):
        # Same venue and similar title, but different sessions of a cycle.
        a = make_event(
            "municipal", "Orquesta Municipal de Tango", "Teatro Municipal Colón", "2026-10-17",
            occurrences=["2026-10-17"],
        )
        b = make_event(
            "articket", "ORQUESTA MUNICIPAL DE TANGO", "Teatro Municipal Colon", "2026-10-31",
            occurrences=["2026-10-31"],
        )
        assert cluster_events([a, b]) == []

    def test_empty_occurrences_fall_back_to_date_start(self):
        # A range without recurrence info (occurrences=[]) still matches by
        # start date against a source that knows the exact date.
        a = make_event("municipal", "Rey Garufa", "Brew House", "2026-12-05", occurrences=[])
        b = make_event(
            "cultutickets", "REY GARUFA", "Ciudad Cultural Brew House", "2026-12-05",
            occurrences=["2026-12-05"],
        )
        assert len(cluster_events([a, b])) == 1

    def test_empty_occurrences_different_start_dates_stay_split(self):
        a = make_event("municipal", "Rey Garufa", "Brew House", "2026-12-05", occurrences=[])
        b = make_event(
            "cultutickets", "REY GARUFA", "Ciudad Cultural Brew House", "2026-12-06",
            occurrences=["2026-12-06"],
        )
        assert cluster_events([a, b]) == []

    def test_cluster_reports_canonical_venue_and_union_of_dates(self):
        a = make_event(
            "municipal", "Tan Biónica", "Estadio Polideportivo Islas Malvinas", "2026-11-21",
            occurrences=["2026-11-21", "2026-11-22"],
        )
        b = make_event(
            "articket", "TAN BIONICA", "Polideportivo Islas Malvinas", "2026-11-21",
            occurrences=["2026-11-21"],
        )
        cluster = cluster_events([a, b])[0]
        assert cluster["venue"] == "polideportivo-islas-malvinas"
        assert cluster["venue_name"] == "Polideportivo Islas Malvinas"
        assert cluster["dates"] == ["2026-11-21", "2026-11-22"]
