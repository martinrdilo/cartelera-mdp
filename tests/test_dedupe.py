"""Tests for cross-source dedupe (venue+date fingerprint, slug join, fuzzy title)."""

from lib.dedupe import cluster_events, extract_slug, normalize_text, strip_title_noise, title_similarity
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


class TestSpanishDatePhrase:
    """A date stamped into the title names the same event, not a new one."""

    def test_date_phrase_is_stripped_for_matching(self):
        assert strip_title_noise("Colyn 21 noviembre 2026") == "Colyn"
        assert strip_title_noise("Solomun 2 de enero de 2027") == "Solomun"

    def test_single_artist_title_matches_the_date_stamped_copy(self):
        stamped = make_event("quehacemos", "Colyn 21 noviembre 2026", "Mute", "2026-11-21")
        opening = make_event("bombo", "OPENING COLYN, COEUS, CROMIND", "Mute", "2026-11-21")
        clusters = cluster_events([stamped, opening])
        assert len(clusters) == 1


class TestSameSourceCorroboration:
    """A third source can prove two same-source titles are one event."""

    def test_two_quehacemos_titles_join_through_bombo(self):
        opening = make_event("quehacemos", "MUTE OPENING", "Mute", "2026-11-21")
        bombo = make_event("bombo", "OPENING COLYN, COEUS, CROMIND", "Mute", "2026-11-21")
        stamped = make_event(
            "quehacemos",
            "Colyn 21 noviembre 2026",
            "Mute",
            "2026-11-21",
            event_id="quehacemos-2",
        )
        clusters = cluster_events([opening, bombo, stamped])
        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 3

    def test_two_distinct_same_source_titles_stay_apart_without_a_bridge(self):
        first = make_event("quehacemos", "MUTE OPENING", "Mute", "2026-11-21")
        second = make_event("quehacemos", "Colyn 21 noviembre 2026", "Mute", "2026-11-21", event_id="q2")
        assert cluster_events([first, second]) == []

    def test_other_show_at_the_venue_does_not_pull_a_single_title_in(self):
        fabiana = make_event(
            "cultutickets",
            "SAB 21 DE NOV FABIANA CANTILO EN MAR DEL PLATA",
            "Brew House",
            "2026-11-21",
        )
        pepo = make_event("cultutickets", "SAB 21 NOV EL PEPO", "Brew House", "2026-11-21", event_id="c2")
        bridge = make_event("cualpinta", "Fabiana Cantilo", "Brew House", "2026-11-21")
        clusters = cluster_events([fabiana, pepo, bridge])
        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 2
        assert {event["source"] for event in clusters[0]["events"]} == {"cultutickets", "cualpinta"}

    def test_supermerk_single_token_needs_its_own_corroboration(self):
        rastone = make_event("cultutickets", "NOCHE RASTONE", "Brew House", "2026-11-27")
        supermerk = make_event(
            "cultutickets",
            "VIER 27 DE NOV SUPERMERK2",
            "Brew House",
            "2026-11-27",
            event_id="c2",
        )
        bridge = make_event("elevenflow", "NOCHE RASTONE", "Brew House", "2026-11-27")
        clusters = cluster_events([rastone, supermerk, bridge])
        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 2

    def test_independent_bridges_do_not_merge_two_distinct_same_source_shows(self):
        dante = make_event("quehacemos", "Dante", "Brew House", "2026-11-21")
        dante_bridge = make_event("cualpinta", "Dante", "Brew House", "2026-11-21")
        nico = make_event("quehacemos", "Nico", "Brew House", "2026-11-21", event_id="q2")
        nico_bridge = make_event("elevenflow", "Nico", "Brew House", "2026-11-21")
        clusters = cluster_events([dante, dante_bridge, nico, nico_bridge])
        assert len(clusters) == 2
        assert all(len(cluster["events"]) == 2 for cluster in clusters)


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

    def test_ticketek_uses_the_event_segment_not_the_venue(self):
        # Ticketek ends its URLs with the venue: /<event>/<venue>.
        assert extract_slug("https://www.ticketek.com.ar/hairspray/teatro-tronador") == (
            "www.ticketek.com.ar:hairspray"
        )
        assert extract_slug("https://www.ticketek.com.ar/abel-pintos/teatro-tronador") == (
            "www.ticketek.com.ar:abel-pintos"
        )

    def test_ticketek_single_segment_still_works(self):
        assert extract_slug("https://www.ticketek.com.ar/abel-pintos") == (
            "www.ticketek.com.ar:abel-pintos"
        )

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

    def test_same_source_festival_prefix_does_not_merge_distinct_shows(self):
        a = make_event(
            "auditorium",
            "41° Festival Internacional de Cine: Children Untold",
            "Teatro Auditorium",
            "2026-11-06",
        )
        b = make_event(
            "auditorium",
            "41° Festival Internacional de Cine: Los relatos",
            "Teatro Auditorium",
            "2026-11-06",
        )
        assert cluster_events([a, b]) == []

    def test_festival_prefix_does_not_merge_distinct_films_across_sources(self):
        a = make_event(
            "auditorium",
            "41° Festival Internacional de Cine: Children Untold",
            "Teatro Auditorium",
            "2026-11-06",
        )
        b = make_event(
            "auditorium",
            "41° Festival Internacional de Cine: Los relatos",
            "Teatro Auditorium",
            "2026-11-06",
        )
        c = make_event(
            "elevenflow",
            "41 FESTIVAL INTERNACIONAL DE CINE - LOS RELATOS",
            "Teatro Auditorium",
            "2026-11-06",
        )

        clusters = cluster_events([a, b, c])

        assert len(clusters) == 1
        assert {event["title"] for event in clusters[0]["events"]} == {b.title, c.title}

    def test_cross_source_bridge_does_not_merge_two_same_source_shows(self):
        kids = make_event("cultutickets", "HALLOWEEN KIDS", "Brew House", "2026-10-31")
        nico = make_event("cultutickets", "HALLOWEEN NICO MATTIOLI", "Brew House", "2026-10-31")
        bridge = make_event(
            "cualpinta",
            "Halloween Kids - Nico Mattioli",
            "Brew House",
            "2026-10-31",
        )

        clusters = cluster_events([kids, nico, bridge])

        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 2
        assert {event["source"] for event in clusters[0]["events"]} == {
            "cultutickets",
            "cualpinta",
        }

    def test_same_source_exact_title_still_joins(self):
        a = make_event("venti", "CLUB QUBA | 22.10 QUEVES", "Quba", "2026-10-22")
        b = make_event("venti", "CLUB QUBA | 22.10 QUEVES", "Quba", "2026-10-22")
        clusters = cluster_events([a, b])
        assert len(clusters) == 1
        assert clusters[0]["pairs"][0]["kind"] == "title_fuzzy"
        assert clusters[0]["pairs"][0]["score"] == 100.0

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


class TestOla1Sources:
    """New wave-1 sources must join the same event, not duplicate it."""

    def test_venti_and_punto_la_vin_join(self):
        a = make_event("venti", "LA VIN - LOS TOTORA TOUR", "Sheraton Mar del Plata Hotel", "2026-10-24")
        b = make_event("punto", "La Vin - Los Totora Tour", "Sheraton Mar del Plata Hotel", "2026-10-24")
        assert len(cluster_events([a, b])) == 1

    def test_ticketek_and_punto_dillom_join(self):
        a = make_event("ticketek", "Dillom", "Bendu Arena", "2027-01-30")
        b = make_event("punto", "Dillom", "Bendu Arena", "2027-01-30")
        assert len(cluster_events([a, b])) == 1

    def test_venti_ticket_slug_joins_its_event_page(self):
        a = make_event(
            "venti", "CLUB QUBA | 22.10 QUEVES", "Quba, café de mar", "2026-10-22",
            ticket_url="https://venti.live/evento/club-quba-22-10-queves",
        )
        b = make_event(
            "punto", "CLUB QUBA | 22.10 QUEVES", "Quba, café de mar", "2026-10-22",
            ticket_url="https://venti.live/evento/club-quba-22-10-queves/",
        )
        cluster = cluster_events([a, b])[0]
        assert cluster["pairs"][0]["kind"] == "ticket_slug"

    def test_bombo_and_punto_mute_join(self):
        a = make_event("bombo", "SOLOMUN - MUTE", "Mute Club de Mar", "2027-01-02")
        b = make_event("punto", "Solomun", "Mute Club de Mar", "2027-01-02")
        assert len(cluster_events([a, b])) == 1

    def test_date_token_in_the_middle_does_not_block_a_match(self):
        a = make_event("bombo", "CLUB QUBA | 22.10 QUEVES", "Quba, café de mar", "2026-10-22")
        b = make_event("punto", "Queves", "Quba", "2026-10-22")
        assert len(cluster_events([a, b])) == 1

    def test_artist_plus_album_title_joins(self):
        a = make_event("municipal", "Diego Torres - Mi Norte y Mi Sur", "Arena Mar del Plata", "2026-11-04")
        b = make_event("punto", "Diego Torres en Arena Mardel Plata", "Arena Mardel Plata", "2026-11-04")
        cluster = cluster_events([a, b])[0]
        assert cluster["pairs"][0]["kind"] in {"title_core", "title_prefix"}

    def test_artist_plus_tour_title_joins(self):
        a = make_event("punto", "Sergio Dalma en Arena Mardel Plata", "Arena Mardel Plata", "2026-11-10")
        b = make_event("municipal", "Sergio Dalma Tour Ritorno a Via Dalma", "Arena Mar del Plata", "2026-11-10")
        assert len(cluster_events([a, b])) == 1

    def test_small_spelling_variant_joins(self):
        a = make_event("municipal", "Baglieto Vitale", "Radio City", "2026-11-07")
        b = make_event("punto", "Baglietto Vital presentan Bodas de Coral", "Teatro Radio City", "2026-11-07")
        assert len(cluster_events([a, b])) == 1

    def test_artist_prefix_with_different_show_title_joins(self):
        a = make_event("municipal", "Patricia Luca - Ahora Solo Faltas Tú.", "Vorterix", "2026-10-31")
        b = make_event("punto", "PATRICIA LUCAS - TRIBUTO A RITA LEE EN VORTERIX", "Vorterix Mar del Plata", "2026-10-31")
        cluster = cluster_events([a, b])[0]
        assert cluster["pairs"][0]["kind"] == "title_prefix"

    def test_generic_first_words_do_not_fake_a_match(self):
        a = make_event("municipal", "Fiesta de la Cerveza", "Brew House", "2026-11-07")
        b = make_event("punto", "Fiesta de la Primavera", "Brew House", "2026-11-07")
        assert cluster_events([a, b]) == []

    def test_different_festival_and_band_same_night_stay_split(self):
        a = make_event("punto", "Jurassic Fest 10 en Vorterix", "Vorterix", "2026-11-07")
        b = make_event("municipal", "LOS PEREZ GARCIA - VORTERIX", "Vorterix", "2026-11-07")
        assert cluster_events([a, b]) == []

    def test_known_title_false_negative_from_report_is_fixed(self):
        a = make_event("municipal", "Sebastián Molina presenta Vivo Arjona", "Teatro Tronador", "2026-11-07")
        b = make_event("punto", "VIVO ARJONA EN MAR DEL PLATA", "Teatro Tronador", "2026-11-07")
        assert len(cluster_events([a, b])) == 1


class TestOla5Buckets:
    """Venue+date buckets that still held two clusters, decided one by one."""

    def test_cross_source_single_token_title_joins(self):
        # Chauvin 04/12: elevenflow lists the full bill, Qué Hacemos only the
        # artist ("Joystick", whose own description names Sideral and the
        # "Diarios de Humo" show). Same venue, same date, same act.
        listed = make_event(
            "elevenflow",
            "JOYSTIK presenta Diarios de Humo junto a (Sideral)",
            "Chauvin Centro de creación",
            "2026-12-04",
        )
        artist_only = make_event("quehacemos", "Joystick", "Chauvin Centro de creación", "2026-12-04")
        clusters = cluster_events([listed, artist_only])
        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 2
        assert clusters[0]["pairs"][0]["kind"] == "title_core"

    def test_single_token_does_not_bridge_a_solo_show_into_a_project(self):
        # Polideportivo 23/01: "David Lebón" and "Seru Girán por Lebón y
        # Aznar" share the artist but not the show's name; the solo listing
        # does not prove it is the Serú Girán project, so they stay apart.
        solo = make_event("quehacemos", "David Lebón", "Polideportivo Islas Malvinas", "2027-01-23")
        project = make_event(
            "tuentrada",
            "Seru Girán por Lebón y Aznar",
            "Polideportivo Mar Del Plata",
            "2027-01-23",
            ticket_url="https://www.tuentrada.com/seru-giran-mdq-27",
        )
        assert cluster_events([solo, project]) == []

    def test_two_functions_of_one_day_at_club_tri_stay_apart(self):
        # Club TRI 20/11: An Espil and Argentina Electrónica are two shows,
        # not one event announced twice.
        espil = make_event(
            "clubtri",
            "AN ESPIL EN CLUB TRI",
            "Club TRI",
            "2026-11-20",
            ticket_url="https://articket.com.ar/AN-ESPIL-EN-CLUB-TRI",
        )
        electronica = make_event(
            "articket",
            "ARGENTINA ELECTRONICA - CLUB TRI",
            "Club TRI",
            "2026-11-20",
            ticket_url="https://articket.com.ar/ARGENTINA-ELECTRONICA-CLUB-TRI",
        )
        assert cluster_events([espil, electronica]) == []

    def test_municipal_and_colon_rows_of_one_event_join(self):
        # The five municipal/Colón pairs are the same event published twice.
        municipal = make_event("municipal", "Orquesta Sinfónica Municipal", "Teatro Municipal Colón", "2026-11-21")
        colon = make_event("colon", "ORQUESTA SINFÓNICA MUNICIPAL", "Teatro Municipal Colón", "2026-11-21")
        clusters = cluster_events([municipal, colon])
        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 2

    def test_two_candlelight_programmes_of_one_day_stay_apart(self):
        # Colón 11/12: Fever runs different setlists the same night.
        swift = make_event(
            "punto", "Candlelight: Tributo a Taylor Swift", "Teatro Colón", "2026-12-11",
            event_id="p1",
        )
        navidad = make_event(
            "elevenflow", "Candlelight: Clásicos de Navidad", "Teatro Municipal Colón", "2026-12-11",
            event_id="p2",
        )
        assert cluster_events([swift, navidad]) == []

    def test_la_caseta_and_la_carpa_stay_apart(self):
        # Both sit on Ruta 11 and are published as "La Carpa" in the titles,
        # but the venue fields name two different places: no merge without a
        # shared slug or an identical title.
        caseta = make_event("passline", "LUMEN FESTIVAL", "La Caseta", "2027-01-20")
        carpa = make_event("quehacemos", "MIE 20.01 - LUMEN", "LA CARPA", "2027-01-20")
        assert cluster_events([caseta, carpa]) == []

    def test_normandina_aliases_join_the_sunset_night(self):
        # punto 30/01 says "La Normandina Destino Arena"; Qué Hacemos says
        # "Stadium Complejo La Normandina". Same artist, same night, same
        # Peralta Ramos 5050 complex.
        punto = make_event(
            "punto", "Bart Skils – Sunset en Playa Grande", "La Normandina Destino Arena", "2027-01-30"
        )
        quehacemos = make_event(
            "quehacemos",
            "BART SKILS + VICTORIA ENGEL | SUNSET NIGHT",
            "Stadium Complejo La Normandina",
            "2027-01-30",
        )
        clusters = cluster_events([punto, quehacemos])
        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 2

    def test_arena_rows_keep_two_different_shows_of_one_day_apart(self):
        # Arena 05/12: a 90s party and a Vinmusic sparkling session are two
        # functions, not one event announced twice.
        nineties = make_event(
            "punto", "Fiesta de los 90 con VIlma Palma en Arena Mardel Plata", "Arena Mardel Plata", "2026-12-05"
        )
        vinmusic = make_event("punto", "Vinmusic MDQ - Sparkling Session", "Arena Mardel Plata", "2026-12-05", event_id="p2")
        assert cluster_events([nineties, vinmusic]) == []


class TestSlugDateCompatibility:
    """A shared ticket page joins one night, never two.

    The wave-3 slug join is deliberately cross-venue (one source often fills
    the venue field with the event name), so the slug alone has to carry the
    evidence. Sellers reuse one ticket page for every function of a show: the
    Club TRI page serves the 22/11 and the 19/12 Cumbia Grande nights, which
    are two events, and dedupe merged them across dates until this rule.
    """

    def test_shared_slug_on_two_different_nights_stays_split(self):
        # Real pair from the refreshed snapshot: Articket lists CUMBIA GRANDE
        # on 19/12 and elevenflow on 22/11 under the same ticket page.
        articket = make_event(
            "articket",
            "CUMBIA GRANDE EN EL TRI",
            "Club TRI",
            "2026-12-19",
            occurrences=["2026-12-19"],
            ticket_url="https://articket.com.ar/CUMBIA-GRANDE-EN-EL-TRI/",
        )
        elevenflow = make_event(
            "elevenflow",
            "CUMBIA GRANDE EN EL TRI",
            "Club TRI",
            "2026-11-22",
            event_id="cumbia-grande-en-el-tri-20261122-7d9i",
            occurrences=["2026-11-22"],
            ticket_url="https://articket.com.ar/CUMBIA-GRANDE-EN-EL-TRI",
        )

        assert cluster_events([articket, elevenflow]) == []

    def test_shared_slug_on_the_same_night_joins(self):
        # The same two rows on the night both sources published.
        articket = make_event(
            "articket",
            "CUMBIA GRANDE EN EL TRI",
            "Club TRI",
            "2026-12-19",
            occurrences=["2026-12-19"],
            ticket_url="https://articket.com.ar/CUMBIA-GRANDE-EN-EL-TRI/",
        )
        elevenflow = make_event(
            "elevenflow",
            "CUMBIA GRANDE EN EL TRI",
            "Club TRI",
            "2026-12-19",
            event_id="cumbia-grande-en-el-tri-20261219-7d9i",
            occurrences=["2026-12-19"],
            ticket_url="https://articket.com.ar/CUMBIA-GRANDE-EN-EL-TRI",
        )

        clusters = cluster_events([articket, elevenflow])

        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 2
        assert clusters[0]["pairs"][0]["kind"] == "ticket_slug"
        assert clusters[0]["dates"] == ["2026-12-19"]

    def test_shared_slug_still_joins_across_venues_on_one_night(self):
        # The wave-3 case the slug join exists for: Ticketek 22/01 has Punto
        # naming the hall (Bendu Arena) and elevenflow putting the event name
        # in the venue field. One ticket page, one event, two venue spellings.
        punto = make_event(
            "punto",
            "El Plan de la Mariposa",
            "Bendu Arena",
            "2027-01-22",
            event_id="20461",
            occurrences=["2027-01-22"],
            ticket_url="https://www.ticketek.com.ar/el-plan-de-la-mariposa",
        )
        elevenflow = make_event(
            "elevenflow",
            "El Plan De La Mariposa",
            "El Plan de la Mariposa",
            "2027-01-22",
            event_id="avif-20270122-1nyw",
            occurrences=["2027-01-22"],
            ticket_url="https://www.ticketek.com.ar/el-plan-de-la-mariposa/bendu-arena",
        )

        clusters = cluster_events([punto, elevenflow])

        assert len(clusters) == 1
        assert {event["source"] for event in clusters[0]["events"]} == {"punto", "elevenflow"}
        assert clusters[0]["pairs"][0]["kind"] == "ticket_slug"

    def test_unknown_session_dates_keep_the_slug_join(self):
        # Punto's row for Tan Bionica has no recurrence info: its start date
        # is the 21/11 and Articket lists the 22/11 function on the same page.
        # An unknown date set on either side leaves the slug as the evidence.
        articket = make_event(
            "articket",
            "TAN BIONICA EN MAR DEL PLATA 22-11",
            "Polideportivo Islas Malvinas",
            "2026-11-22",
            occurrences=["2026-11-22"],
            ticket_url="https://articket.com.ar/TAN-BIONICA-EN-MAR-DEL-PLATA-22-11/",
        )
        punto = make_event(
            "punto",
            "Tan Bionica llega a Mar del Plata",
            "Estadio Polideportivo Islas Malvinas",
            "2026-11-21",
            event_id="19994",
            occurrences=[],
            ticket_url="https://articket.com.ar/TAN-BIONICA-EN-MAR-DEL-PLATA-22-11/",
        )

        clusters = cluster_events([articket, punto])

        assert len(clusters) == 1
        assert clusters[0]["pairs"][0]["kind"] == "ticket_slug"


    def test_a_bridging_page_gives_the_same_result_in_any_order(self):
        # A={19/12}, B={20/12} and C={19/12, 20/12} share one ticket page but
        # sit in different venues with different titles, so only the slug pass
        # can join them. Anchoring each row on a single earlier candidate made
        # the clustering depend on input order: with C last, B never met C.
        first = make_event(
            "articket",
            "TRES NOCHES",
            "Club Uno",
            "2026-12-19",
            event_id="tres-noches-a",
            occurrences=["2026-12-19"],
            ticket_url="https://articket.com.ar/TRES-NOCHES/",
        )
        second = make_event(
            "punto",
            "TRES NOCHES BIS",
            "Club Dos",
            "2026-12-20",
            event_id="tres-noches-b",
            occurrences=["2026-12-20"],
            ticket_url="https://articket.com.ar/TRES-NOCHES",
        )
        both = make_event(
            "cualpinta",
            "TRES NOCHES FINAL",
            "Club Tres",
            "2026-12-19",
            event_id="tres-noches-c",
            occurrences=["2026-12-19", "2026-12-20"],
            ticket_url="https://articket.com.ar/TRES-NOCHES/",
        )

        shapes = set()
        for order in (
            [first, second, both],
            [both, first, second],
            [first, both, second],
            [second, first, both],
        ):
            clusters = cluster_events(list(order))
            shapes.add(tuple(sorted(len(cluster["events"]) for cluster in clusters)))

        assert len(shapes) == 1, shapes


class TestSlugPairEvidence:
    """The slug join records every anchor it unions, in a stable form.

    One ticket page can list every night of a show, so a single row bridges
    several rows at once. Naming only the last compatible anchor made the
    cluster's evidence look narrower than the merge and let the recorded pair
    depend on the order the rows arrived in.
    """

    @staticmethod
    def _evidence(clusters):
        """Cluster membership plus pair records, in an order-free shape."""
        assert len(clusters) == 1, clusters
        cluster = clusters[0]
        members = sorted(event["source_event_id"] for event in cluster["events"])
        pairs = sorted(
            (tuple(sorted((pair["a"], pair["b"]))), pair["kind"], pair["slug"])
            for pair in cluster["pairs"]
        )
        return members, pairs

    def test_three_way_slug_bridge_records_every_anchor(self):
        # One Articket page sells the 19/12 and the 20/12 functions; the three
        # rows sit in different venues with different titles, so only the slug
        # pass can join them. The 20/12 row is compatible with both earlier
        # rows, so the cluster owes one pair per anchor, not just the last.
        opening = make_event(
            "punto",
            "FESTIVAL TRES NOCHES",
            "Sala Uno",
            "2026-12-19",
            event_id="tres-noches-a",
            occurrences=["2026-12-19"],
            ticket_url="https://articket.com.ar/FESTIVAL-TRES-NOCHES/",
        )
        middle = make_event(
            "articket",
            "FESTIVAL TRES NOCHES - SEGUNDA",
            "Sala Dos",
            "2026-12-19",
            event_id="tres-noches-b",
            occurrences=["2026-12-19", "2026-12-20"],
            ticket_url="https://articket.com.ar/FESTIVAL-TRES-NOCHES",
        )
        closing = make_event(
            "cualpinta",
            "FESTIVAL TRES NOCHES - CIERRE",
            "Sala Tres",
            "2026-12-20",
            event_id="tres-noches-c",
            occurrences=["2026-12-19", "2026-12-20"],
            ticket_url="https://articket.com.ar/FESTIVAL-TRES-NOCHES/",
        )

        members, pairs = self._evidence(cluster_events([opening, middle, closing]))

        assert members == ["tres-noches-a", "tres-noches-b", "tres-noches-c"]
        slug = "articket.com.ar:festival-tres-noches"
        expected = {
            (("articket:tres-noches-b", "punto:tres-noches-a"), "ticket_slug", slug),
            (("articket:tres-noches-b", "cualpinta:tres-noches-c"), "ticket_slug", slug),
            (("cualpinta:tres-noches-c", "punto:tres-noches-a"), "ticket_slug", slug),
        }
        assert len(pairs) == 3
        assert set(pairs) == expected

    def test_pair_evidence_does_not_depend_on_input_order(self):
        # Same three rows, same single cluster: only the arrival order of the
        # bridging row changes. The pair set must not follow it.
        first_night = make_event(
            "punto",
            "FIESTA TRES - PRIMERA",
            "Sala Uno",
            "2026-12-19",
            event_id="fiesta-tres-a",
            occurrences=["2026-12-19"],
            ticket_url="https://articket.com.ar/FIESTA-TRES/",
        )
        second_night = make_event(
            "cualpinta",
            "FIESTA TRES - SEGUNDA",
            "Sala Dos",
            "2026-12-20",
            event_id="fiesta-tres-b",
            occurrences=["2026-12-20"],
            ticket_url="https://articket.com.ar/FIESTA-TRES",
        )
        bridge = make_event(
            "articket",
            "FIESTA TRES - ABONO",
            "Sala Tres",
            "2026-12-19",
            event_id="fiesta-tres-c",
            occurrences=["2026-12-19", "2026-12-20"],
            ticket_url="https://articket.com.ar/FIESTA-TRES/",
        )

        bridge_first = self._evidence(cluster_events([bridge, first_night, second_night]))
        bridge_last = self._evidence(cluster_events([first_night, second_night, bridge]))

        assert bridge_first == bridge_last
        members, pairs = bridge_first
        assert members == ["fiesta-tres-a", "fiesta-tres-b", "fiesta-tres-c"]
        slug = "articket.com.ar:fiesta-tres"
        expected = {
            (("articket:fiesta-tres-c", "punto:fiesta-tres-a"), "ticket_slug", slug),
            (("articket:fiesta-tres-c", "cualpinta:fiesta-tres-b"), "ticket_slug", slug),
        }
        assert len(pairs) == 2
        assert set(pairs) == expected


class TestDateNoise:
    """Source date prefixes are noise; they must not leak into the title match."""

    def test_weekday_before_a_dot_date_is_date_noise(self):
        # Qué Hacemos prints "JUE 24.12 - <title>": the dot date is not in the
        # prefix pattern, so the weekday used to survive as a title token.
        assert strip_title_noise("JUE 24.12 - XMAS Sinergia x big family") == (
            "XMAS Sinergia x big family"
        )

    def test_stamped_date_with_a_space_before_the_dot_is_date_noise(self):
        # Qué Hacemos prints the Umano date stamp as "08 .01.2027".
        assert strip_title_noise("Mariano Mellino 08 .01.2027") == "Mariano Mellino"


class TestDeudaAgendaBuckets:
    """The eight duplicate buckets of S1, each closed with its verdict.

    A joined bucket carries the minimal evidence its rows support. A rejected
    bucket keeps the guard that splits it and pins the two different events
    that guard exists for, so a later cheap widening fails here.
    """

    def test_municipal_festival_joins_the_concatenated_articket_title(self):
        # abbey-road 05/12: the municipal agenda prints the festival name on
        # its own; Articket glues that name into one word and appends the bill.
        municipal = make_event(
            "municipal",
            "Retropartuza Fest",
            "Abbey Road - Concert Bar",
            "2026-12-05",
            time="21:00",
        )
        articket = make_event(
            "articket",
            "RETROPARTUZAFEST - CHARLY MORENO Y LOS CHIKILINES - CELE MARTINEZ Y DJ PASTOCCHI",
            "Abbey Road",
            "2026-12-05",
            ticket_url="https://articket.com.ar/RETROPARTUZAFEST-CHARLY-MORENO-CELE-MARTINEZ-PASTOCCHI/",
            time="21:00",
        )

        clusters = cluster_events([municipal, articket])

        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 2
        assert clusters[0]["pairs"][0]["kind"] == "title_core"

    def test_second_show_of_the_same_night_stays_out_of_the_party(self):
        # brew-house 27/11 has two shows: the 20:00 party Rastone and
        # SUPERMERK2 at 23:30. The glued-name and wrapper rules must not pull
        # the late show into the party.
        party = make_event(
            "cualpinta",
            "¡FIESTA EN MAR DEL RASTONE! 💚💛❤️ 🎸 50% RASTA, 50% STONE",
            "Ciudad Cultural Brewhouse Puerto",
            "2026-11-27",
            time="20:00",
        )
        second_show = make_event(
            "cultutickets",
            "VIER 27 DE NOV SUPERMERK2",
            "Ciudad Cultural Brew House",
            "2026-11-27",
            time="23:30",
        )

        assert cluster_events([party, second_show]) == []

    def test_party_wrapper_title_joins_noche_rastone(self):
        # brew-house 27/11: CultuTickets sells the 20:00 party as "NOCHE
        # RASTONE"; Cual Pinta brands the same party with a wrapper and bill.
        cultutickets = make_event(
            "cultutickets",
            "NOCHE RASTONE",
            "Ciudad Cultural Brew House",
            "2026-11-27",
            ticket_url="https://cultutickets.com/NOCHE-RASTONE-/",
            time="20:00",
        )
        cualpinta = make_event(
            "cualpinta",
            "¡FIESTA EN MAR DEL RASTONE! 💚💛❤️ 🎸 50% RASTA, 50% STONE",
            "Ciudad Cultural Brewhouse Puerto",
            "2026-11-27",
            time="20:00",
        )

        clusters = cluster_events([cultutickets, cualpinta])

        assert len(clusters) == 1
        assert clusters[0]["pairs"][0]["kind"] == "title_core"

    def test_wrapper_word_alone_does_not_name_the_event(self):
        # Two different 90s nights at one venue and date share only the
        # wrapper and a three-character tag: a genre slot is not a name, so
        # the wrapper rule needs a real name on both sides.
        fiesta = make_event("municipal", "Fiesta 90s", "Club Uno", "2026-12-12")
        noche = make_event("punto", "Noche 90s", "Club Uno", "2026-12-12", event_id="p2")

        assert cluster_events([fiesta, noche]) == []

    def test_municipal_fiesta_la_nosti_joins_the_anniversary_title(self):
        # stadium-la-normandina 21/11: the municipal agenda prints the party's
        # wrapper title, Venti prints the party plus its anniversary bill.
        municipal = make_event(
            "municipal",
            "Fiesta La Nosti",
            "Stadium (La Normandina)",
            "2026-11-21",
            venue_raw="Stadium (La Normandina), Paseo Victoria Ocampo 5050",
        )
        venti = make_event(
            "venti",
            "La Nosti - 5 aniversario-sábado 21/11",
            "Stadium Complejo La Normandina",
            "2026-11-21",
            venue_raw=(
                "Stadium Complejo La Normandina, Victoria Ocampo Complejo "
                "La Normandina Loc. 4 Playa Grande, EAQ, Mar del Plata"
            ),
            ticket_url="https://venti.live/evento/la-nosti-5-aniversario-s-bado-21-11",
        )

        clusters = cluster_events([municipal, venti])

        assert len(clusters) == 1
        assert len(clusters[0]["events"]) == 2

    def test_artist_name_prefix_is_not_a_festival_series(self):
        # teatro-auditorium 05/12: one concert, two titles. The shared opening
        # is the artist's name, not a festival prefix hiding two entries, so
        # the series guard must not swallow the pair.
        auditorium = make_event(
            "auditorium",
            "Valentín Garvie Quinteto llega al Teatro Auditorium con una propuesta de jazz contemporáneo",
            "Teatro Auditorium",
            "2026-12-05",
            venue_raw="Sala Gregorio Nachman",
            time="21:00",
        )
        quehacemos = make_event(
            "quehacemos",
            "VALENTIN GARVIE QUINTETO FEAT HERNAN HECHT",
            "Auditorium",
            "2026-12-05",
            venue_raw=(
                "Auditorium, Boulevard Maritimo Patricio Peralta Ramos 2280, "
                "Mar del Plata, Buenos Aires, Argentina"
            ),
            ticket_url=(
                "https://www.plateanet.com/obra/35972?obra="
                "VALENTIN-GARVIE-QUINTETO-FEAT-HERNAN-HECHT"
            ),
        )

        clusters = cluster_events([auditorium, quehacemos])

        assert len(clusters) == 1
        assert clusters[0]["pairs"][0]["kind"] == "title_prefix"

    def test_date_stamp_with_a_space_joins_the_lineup_title(self):
        # umano 08/01: Qué Hacemos stamps the date as "08 .01.2027", with a
        # space before the dot. The stamped copy is the act Venti lists.
        venti = make_event(
            "venti",
            "UMN ELECTRONIK | Audioholics - Mariano Mellino | Vie 8 de Enero",
            "UMANO",
            "2027-01-08",
            venue_raw="UMANO, Av. de los Trabajadores 6230, Mar del Plata",
            ticket_url="https://venti.live/evento/umn-electronik-vie-8-de-enero",
            time="23:00",
        )
        stamped = make_event(
            "quehacemos",
            "Mariano Mellino 08 .01.2027",
            "UMN",
            "2027-01-08",
            venue_raw=(
                "UMN, Av. de los Trabajadores 4044, B7600 Mar del Plata, "
                "Provincia de Buenos Aires"
            ),
        )

        clusters = cluster_events([venti, stamped])

        assert len(clusters) == 1
        assert clusters[0]["pairs"][0]["kind"] == "title_fuzzy"
        assert clusters[0]["pairs"][0]["score"] == 100.0

    def test_xmas_sinergia_rows_join_once_the_weekday_prefix_is_noise(self):
        # la-carpa 24/12: Qué Hacemos published the same Xmas edition twice;
        # the date prefix "JUE 24.12" kept the older row from matching.
        stamped = make_event(
            "quehacemos",
            "JUE 24.12 - XMAS Sinergia x big family",
            "LA CARPA",
            "2026-12-24",
            ticket_url="https://www.passline.com/eventos/jue-2412-xmas-sinergia-x-big-family",
        )
        plain = make_event(
            "quehacemos",
            "XMAS EDITION - SINERGIA x BIG FAMILY",
            "La Carpa Mar del Plata",
            "2026-12-24",
            event_id="quehacemos-xmas-edition",
            ticket_url="https://getdogma.app/web/event/hgGIEFGD86tU",
        )

        clusters = cluster_events([stamped, plain])

        assert len(clusters) == 1
        assert clusters[0]["pairs"][0]["kind"] == "title_core"

    def test_same_source_fuzzy_duplicate_stays_split_by_design(self):
        # el-argentino-bar 20/11: Cual Pinta lists one 22:00 show twice under
        # different titles. The same-source gate accepts only an exact or a
        # core-contained title; a fuzzy join there would also merge two
        # different screenings of one festival day, so this pair stays apart.
        first = make_event(
            "cualpinta",
            "COMIDA CHINA Todo Calamaro",
            "El Argentino Bar",
            "2026-11-20",
            event_id="comida-china-todo-calamaro",
            time="22:00",
        )
        second = make_event(
            "cualpinta",
            "Comida China - Canciones de Calamaro",
            "El Argentino Bar",
            "2026-11-20",
            event_id="comida-china-canciones-de-calamaro",
            time="22:00",
        )

        assert cluster_events([first, second]) == []

    def test_two_vinmusic_editions_keep_their_own_rows(self):
        # sheraton 05/12: Venti sells two editions of the same hotel evening
        # under two ticket pages (sparkling-ii and aniversario-ii) and Punto
        # listed both. Punto's two titles are not one event: each edition
        # keeps its own cluster and the Cheers rows join each other.
        municipal = make_event(
            "municipal",
            "Vinmusic MDQ Cheers 2026",
            "Sheraton Mar del Plata",
            "2026-12-05",
            event_id="47265",
            time="18:00",
        )
        venti = make_event(
            "venti",
            "VINMUSIC MDQ -  SPARKLING SESSION",
            "Sheraton Mar del Plata Hotel",
            "2026-12-05",
            event_id="10639",
            venue_raw="Sheraton Mar del Plata Hotel, Leandro N. Alem 4221, Mar del Plata",
            occurrences=["2026-12-05"],
            ticket_url="https://venti.live/evento/vinmusic-mdq-sparkling-ii",
            time="18:00",
        )
        punto_sparkling = make_event(
            "punto",
            "Vinmusic MDQ - Sparkling Session",
            "Arena Mardel Plata",
            "2026-12-05",
            event_id="20628",
            date_end="2026-12-06",
            occurrences=[],
            ticket_url="https://venti.live/evento/vinmusic-mdq-sparkling-ii",
            time="18:00",
        )
        punto_cheers = make_event(
            "punto",
            "Vinmusic MDQ - Cheers 2026",
            "Sheraton Mar del Plata Hotel",
            "2026-12-05",
            event_id="20331",
            date_end="2026-12-06",
            occurrences=[],
            ticket_url="https://venti.live/evento/vinmusic-mdq-aniversario-ii",
            time="18:00",
        )
        cualpinta = make_event(
            "cualpinta",
            "Sparkling Cheers con Franco Schmidt y Fede López",
            "Sheraton Mar del Plata",
            "2026-12-05",
            event_id="sparkling-cheers-con-franco-schmidt-y-fede-lopez",
            venue_raw=(
                "Sheraton Mar del Plata, Leandro N. Alem 4221, B7600 Mar del "
                "Plata, Provincia de Buenos Aires"
            ),
            occurrences=["2026-12-05"],
            ticket_url="https://venti.live/evento/vinmusic-mdq-aniversario-ii",
            time="18:00",
        )
        quehacemos = make_event(
            "quehacemos",
            "VINMUSIC MDQ - CHEERS 2026",
            "Sheraton Mar del Plata Hotel",
            "2026-12-05",
            event_id="53815",
            venue_raw="Sheraton Mar del Plata Hotel, Leandro N. Alem 4221, Mar del Plata",
            occurrences=["2026-12-05"],
            ticket_url="https://venti.com.ar/evento/vinmusic-mdq-aniversario-ii",
        )

        clusters = cluster_events(
            [municipal, venti, punto_sparkling, punto_cheers, cualpinta, quehacemos]
        )

        members = sorted(
            sorted(f"{event['source']}:{event['source_event_id']}" for event in cluster["events"])
            for cluster in clusters
        )
        assert members == [
            [
                "cualpinta:sparkling-cheers-con-franco-schmidt-y-fede-lopez",
                "municipal:47265",
                "punto:20331",
                "quehacemos:53815",
            ],
            ["punto:20628", "venti:10639"],
        ]
