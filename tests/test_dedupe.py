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

