"""Tests for the venue registry and name resolution."""

import pytest

import lib.venues as venues
from lib.venues import all_venues, normalize_name, resolve, venue_key


class TestNormalizeName:
    def test_lowercase_and_accents(self):
        assert normalize_name("Teatro Municipal Colón") == "teatro municipal colon"

    def test_punctuation_and_dots(self):
        assert (
            normalize_name("Centro Cultural Victoria Ocampo. Villa Victoria")
            == "centro cultural victoria ocampo villa victoria"
        )

    def test_hyphens_and_collapsed_spaces(self):
        assert normalize_name("Abbey  Road - Concert   Bar") == "abbey road concert bar"

    def test_empty_values(self):
        assert normalize_name("") == ""
        assert normalize_name(None) == ""


class TestResolve:
    def test_short_name(self):
        assert resolve("Brew House") == ("brew-house", "Ciudad Cultural Brew House")

    def test_alias_variant(self):
        assert resolve("Ciudad Cultural Brew House") == ("brew-house", "Ciudad Cultural Brew House")

    def test_accent_variant_resolves_without_extra_alias(self):
        assert resolve("Teatro Municipal Colon") == ("teatro-municipal-colon", "Teatro Municipal Colón")

    def test_raw_string_with_address(self):
        assert resolve("Brew House, Diag. Garibaldi 4830") == ("brew-house", "Ciudad Cultural Brew House")

    def test_abbey_road_variant(self):
        assert resolve("Abbey Road - Concert Bar") == ("abbey-road", "Abbey Road")

    def test_villa_victoria_variant(self):
        assert resolve("Centro Cultural Victoria Ocampo. Villa Victoria") == (
            "villa-victoria-ocampo",
            "Villa Victoria Ocampo",
        )

    def test_sheraton_oddity_maps_to_the_sheraton(self):
        # The municipal source labels the Sheraton hall "Auditorium Victoria
        # Ocampo"; same address (Alem 4221), so it is the Sheraton, not Villa
        # Victoria (Matheu 1851). See REPORT.md.
        assert resolve("Sheraton Mar del Plata - Auditorium Victoria Ocampo") == (
            "sheraton-mar-del-plata",
            "Sheraton Mar del Plata",
        )

    def test_teatro_auditorium_salas_share_one_venue(self):
        expected = ("teatro-auditorium", "Teatro Auditorium")
        assert resolve("Teatro Auditorium - Sala Roberto J. Payró") == expected
        assert resolve("Teatro Auditorium - Sala Gregorio Nachman") == expected

    def test_chauvin_variant(self):
        assert resolve("Microteatro Chauvin") == ("chauvin", "Chauvin")

    def test_polideportivo_variant(self):
        assert resolve("Estadio Polideportivo Islas Malvinas") == (
            "polideportivo-islas-malvinas",
            "Polideportivo Islas Malvinas",
        )

    def test_ola1_aliases_resolve(self):
        assert resolve("Teatro Colón") == ("teatro-municipal-colon", "Teatro Municipal Colón")
        assert resolve("Arena Mardel Plata") == ("arena-mar-del-plata", "Arena Mar del Plata")
        assert resolve("Bendu Arena") == ("bendu", "Bendu")
        assert resolve("Mute Club de Mar") == ("mute-club-de-mar", "Mute Club de Mar")
        assert resolve("Playas Alfar - Balneario 6 - Mute") == (
            "mute-club-de-mar",
            "Mute Club de Mar",
        )
        assert resolve("Teatro Radio City") == ("radio-city", "Centro de Arte Radio City - Roxy - Melany")
        assert resolve("Vorterix Mar del Plata") == ("vorterix", "Vorterix")
        assert resolve("Teatro Club El Tri") == ("club-tri", "Club TRI")

    def test_auditorium_puerto_is_not_the_auditorium(self):
        assert resolve("Teatro Auditorium Laureti Puerto")[0] == "auditorium-laureti-puerto"
        assert resolve("Teatro Auditorium - Sala Roberto J. Payró")[0] == "teatro-auditorium"

    def test_ola2_aliases_resolve(self):
        assert resolve("Sala Astor Piazzolla") == ("teatro-auditorium", "Teatro Auditorium")
        assert resolve("Sala Roberto J. Payró") == ("teatro-auditorium", "Teatro Auditorium")
        assert resolve("Café Teatral Emilio Alfaro") == ("teatro-auditorium", "Teatro Auditorium")
        assert resolve("Sala Jorge Laureti - Puerto") == (
            "auditorium-laureti-puerto",
            "Teatro Auditorium Laureti Puerto",
        )
        assert resolve("Polideportivo Mar De Plata") == (
            "polideportivo-islas-malvinas",
            "Polideportivo Islas Malvinas",
        )
        assert resolve("Teatro Enrique Carreras") == (
            "teatro-enrique-carreras",
            "Teatro Enrique Carreras",
        )

    def test_ola3_aliases_resolve(self):
        assert resolve("Teatro Roxy Radio City, San Luis 1750") == (
            "radio-city",
            "Centro de Arte Radio City - Roxy - Melany",
        )
        assert resolve("Ciudad Cultural Brewhouse Puerto") == (
            "brew-house",
            "Ciudad Cultural Brew House",
        )
        assert resolve("Auditorium") == ("teatro-auditorium", "Teatro Auditorium")
        assert resolve("Teatro Vorterix") == ("vorterix", "Vorterix")
        assert resolve("Quba cafe del mar") == ("quba", "Quba")
        assert resolve("ROOMIE CLUB, Av. Colón y el Mar") == ("roomie-club", "Roomie Club")
        assert resolve("Jones, Mar del Plata Buenos Aires AR") == ("mr-jones", "Mr. Jones")
        assert resolve("Bajo Tierra Club de Jazz") == ("bajo-tierra", "Bajo Tierra")

    def test_unknown_venue_returns_none(self):
        assert resolve("Bolichito de la esquina") is None

    def test_empty_values_return_none(self):
        assert resolve("") is None
        assert resolve(None) is None

    def test_villa_victoria_and_sheraton_do_not_cross_match(self):
        # Both contain "Victoria Ocampo"; alias matching must keep them apart.
        assert resolve("Villa Victoria Ocampo")[0] != resolve("Sheraton Mar del Plata")[0]

    def test_ola5_venue_spellings_resolve_to_the_registered_venue(self):
        # Spellings the corpus publishes for venues the registry already knows.
        assert resolve("RADIO CITY / ROXY / MELANY") == (
            "radio-city",
            "Centro de Arte Radio City - Roxy - Melany",
        )
        assert resolve("Hotel Sheraton") == ("sheraton-mar-del-plata", "Sheraton Mar del Plata")
        assert resolve("Teatro Vorterix Mar del Plata") == ("vorterix", "Vorterix")
        assert resolve("Dickens Pub") == ("dickens", "Dickens")
        assert resolve("Hoffen Bar") == ("hoffen", "Hoffen")
        assert resolve("BAI-BAI Surf House") == ("bai-bai", "Bai Bai")
        assert resolve("Centro Cultural Séptimo Fuego") == ("el-septimo-fuego", "El Séptimo Fuego")
        assert resolve("Colectivo Cultural a La Vuelta de La Esquina") == ("ccave", "CCAVE")
        assert resolve("La Carpa Mar del Plata") == ("la-carpa", "La Carpa")
        assert resolve("Playas Alfar - Balneario 10 - La Carpa") == ("la-carpa", "La Carpa")

    def test_ola5_normandina_spellings_are_one_complex(self):
        # Same address (Paseo Victoria Ocampo / Peralta Ramos 5050) and the
        # same nights published under both names: Bart Skils on 30/01 and the
        # Loco Dice NYE party.
        expected = ("stadium-la-normandina", "Stadium Complejo La Normandina")
        assert resolve("Stadium (La Normandina)") == expected
        assert resolve("La Normandina Destino Arena") == expected
        assert resolve("La normandinda salon de eventos") == expected

    def test_ola5_umn_is_umano(self):
        # Venti publishes the "UMN ELECTRONIK" series at UMANO (8, 15, 22 and
        # 29/01) and Qué Hacemos lists the same four nights at "UMN" through
        # allmusicparties' /umn-mar-del-plata pages, so UMN is the venue's own
        # short spelling.
        assert resolve("UMANO") == ("umano", "UMANO")
        assert resolve("UMN") == ("umano", "UMANO")

    def test_ola5_new_venues_resolve(self):
        expected_ids = {
            "La Caseta": "la-caseta",
            "Cars & Coffee Mar del Plata": "cars-coffee-mdp",
            "Smith": "smith",
            "Espacio Fortunato": "espacio-fortunato",
            "Microdestileria Restinga Gin - Faro Norte": "microdestileria-restinga-gin",
            "Microdestileria Restinga Gin - Faro Norte, Mar del Plata": "microdestileria-restinga-gin",
            "Soberano": "soberano",
            "El Calamar Loco Chapadmalal": "el-calamar-loco-chapadmalal",
            "Hawaii Bar Pool": "hawaii-bar-pool",
            "EL CLUB DEL TEATRO": "el-club-del-teatro",
            "Feria de Artesanos del Bosque Peralta Ramos": "feria-artesanos-bosque-peralta-ramos",
            "Hotel dos Reyes": "hotel-dos-reyes",
            "AUDITORIO PUERTA DE VIDA": "auditorio-puerta-de-vida",
            "Coliseo Arena Gamer": "coliseo-arena-gamer",
            "Biblioteca Popular Juventud Moderna": "biblioteca-juventud-moderna",
            "Librería El Gran Pez": "libreria-el-gran-pez",
            "TMT EDISON": "tmt-edison",
            "Plaza De La Naturaleza": "plaza-de-la-naturaleza",
            "Casa Chasqui": "casa-chasqui",
            "Proyecto Bar": "proyecto-bar",
            "Baum Cervecería": "baum-cerveceria",
            "Museum MDQ": "museum-mdq",
            "Ananá": "anana",
            "El destino": "el-destino",
        }
        for name, venue_id in expected_ids.items():
            assert resolve(name)[0] == venue_id, name

    def test_ola5_sala_amp_is_the_arena_not_bendu(self):
        # "Sala AMP de Arena Mardel" is the Arena Mar del Plata hall: the
        # name says so and Venti publishes Kapanga there under the same slug
        # as the Arena. The "Av. de los Trabajadores 150" address in that row
        # is the elevenflow slip that also tags Bendu Arena.
        assert resolve("Sala AMP de Arena Mardel") == ("arena-mar-del-plata", "Arena Mar del Plata")

    def test_ola5_address_shaped_branches_stay_apart(self):
        # Same brand, different address: the registry must not fold the
        # Chapadmalal branch into the Playa Grande one, nor Baum's
        # Av. Constitución branch into Baum Playa Grande.
        assert resolve("El Calamar Loco Chapadmalal")[0] != resolve("El Calamar Loco PG")[0]
        assert resolve("El Calamar Loco Chapadmalal")[0] != resolve("Calamar Loco PG")[0]
        assert resolve("Baum Cervecería")[0] != resolve("Baum Playa Grande")[0]
        assert resolve("La Caseta")[0] != resolve("La Carpa")[0]

    def test_ola5_unresolved_categories_stay_unresolved(self):
        # Production company, city/zone strings, bare routes and a missing
        # venue field: resolving these would invent a venue or hide a real one.
        for name in (
            "",
            "Antesala",
            "Mar Del Plata",
            "MAR DEL PLATA",
            "Playa Grande",
            "Playa Chapadmalal",
            "Avenida Patricio Peralta Ramos",
            "Ruta Provincial 11",
            "Festival Silvermare",
            "El Plan de la Mariposa",
        ):
            assert resolve(name) is None, name


class TestEventVenue:
    """Qué Hacemos publishes Dogma shows with no venue field at all and names
    the room only in the title ("Max Styler en MUTE"). The fields stay
    authoritative; the title is a venue statement only where it attributes the
    show to a registered alias after "en"/"at"/"@". Cities, zones, bare
    routes, brands and artist names carry no venue and stay unresolved.
    """

    def test_max_styler_at_mute_resolves_from_the_title(self):
        assert venues.resolve_event(
            title="Max Styler en MUTE", venue_name="", venue_raw=""
        ) == ("mute-club-de-mar", "Mute Club de Mar")

    def test_konstantin_sibold_at_mute_resolves_from_the_title(self):
        # Dogma publishes this night with only the route as its address.
        assert venues.resolve_event(
            title="Konstantin Sibold en MUTE",
            venue_name="",
            venue_raw=", Ruta Provincial 11",
        ) == ("mute-club-de-mar", "Mute Club de Mar")

    def test_massano_and_kevin_de_vries_at_mute_resolves_from_the_title(self):
        assert venues.resolve_event(
            title="MASSANO & KEVIN DE VRIES at MUTE",
            venue_name="",
            venue_raw=", Ruta Provincial 11",
        ) == ("mute-club-de-mar", "Mute Club de Mar")

    def test_time_after_the_room_does_not_hide_the_earlier_mention(self):
        # The room is followed by a time, so the phrase after "@" names a
        # clock, not a venue. The "en" mention before it still stands.
        assert venues.resolve_event(
            title="Max Styler en MUTE @ 23:00", venue_name="", venue_raw=""
        ) == ("mute-club-de-mar", "Mute Club de Mar")

    def test_bare_handle_after_the_at_sign_resolves(self):
        # People write the handle glued to the sign; the alias is what counts.
        assert venues.resolve_event(
            title="Max Styler @MUTE", venue_name="", venue_raw=""
        ) == ("mute-club-de-mar", "Mute Club de Mar")

    def test_event_suffix_after_the_room_does_not_hide_it(self):
        assert venues.resolve_event(
            title="Max Styler en MUTE - 5 aniversario", venue_name="", venue_raw=""
        ) == ("mute-club-de-mar", "Mute Club de Mar")

    def test_city_after_the_room_does_not_hide_it(self):
        # "en Mar del Plata" is the city, not the room; the earlier "en MUTE"
        # is the venue statement the row actually makes.
        assert venues.resolve_event(
            title="Max Styler en MUTE en Mar del Plata", venue_name="", venue_raw=""
        ) == ("mute-club-de-mar", "Mute Club de Mar")

    def test_multi_word_room_wins_over_a_shorter_registered_prefix(self):
        # "Teatro Auditorium" is a registered alias of the city auditorium and
        # the first two words of the registered four-word alias of the Puerto
        # hall, so a shorter candidate that wins here answers the wrong room.
        # The trailing city or time makes the whole remainder unresolvable, so
        # only the candidate order decides.
        expected = (
            "auditorium-laureti-puerto",
            "Teatro Auditorium Laureti Puerto",
        )
        for title in (
            "Nick Warren en Teatro Auditorium Laureti Puerto en Mar del Plata",
            "Nick Warren en Teatro Auditorium Laureti Puerto @ 23:00",
        ):
            assert venues.resolve_event(
                title=title, venue_name="", venue_raw=""
            ) == expected, title

    def test_title_naming_no_registered_alias_stays_unresolved(self):
        # Shorter candidates must never be invented into a venue: a room, a
        # zone and a city that the registry does not know add no evidence.
        for title in (
            "Max Styler en Bolichito de la Esquina",
            "Max Styler en El Galpón de la Costa",
            "Noche en Playa Grande @ 23:00",
        ):
            assert venues.resolve_event(
                title=title, venue_name="", venue_raw=""
            ) is None, title

    def test_time_only_after_the_at_sign_falls_back_to_the_en_mention(self):
        # Same failure with no space after the sign: the rightmost preposition
        # is introduced by "@" and names a time, so the earlier "en" decides.
        assert venues.resolve_event(
            title="Max Styler en MUTE @23:00", venue_name="", venue_raw=""
        ) == ("mute-club-de-mar", "Mute Club de Mar")

    def test_camelphat_row_keeps_the_bare_route_unresolved(self):
        # Same night and room as the Bombo and Cual Pinta MUTE rows of the
        # same show, but this row names no venue: the route alone is not
        # evidence, and the artist name is not a place.
        assert venues.resolve_event(
            title="CAMELPHAT", venue_name="", venue_raw=", Ruta Provincial 11"
        ) is None

    def test_venue_fields_win_over_a_title_mention(self):
        assert venues.resolve_event(
            title="Tributo en Abbey Road",
            venue_name="Brew House",
            venue_raw="Brew House, Diag. Garibaldi 4830",
        ) == ("brew-house", "Ciudad Cultural Brew House")

    def test_unresolved_rows_of_the_snapshot_stay_unresolved(self):
        # Every row S2 leaves unresolved, with its published fields.
        rows = [
            (
                "Festival de la Plaza de la Naturaleza",
                "Playa Chapadmalal",
                "Playa Chapadmalal, Paseo Costanero Sur Presidente Illia 20",
            ),
            (
                "ANTESALA 07 NAVIDAD PETER SWAREZ - FRAN OTERO - TOMY RAIZ",
                "Antesala",
                (
                    "P.º Jesús de Galindez s/n, B7600 Mar del Plata,"
                    " Provincia de Buenos Aires, Argentina"
                ),
            ),
            (
                "Sector Recreacionista Vikingo - Klan Venner",
                "Festival Silvermare",
                "Festival Silvermare, Armando Chulac 6635",
            ),
            (
                "El Plan De La Mariposa",
                "El Plan de la Mariposa",
                "El Plan de la Mariposa, Av. de los Trabajadores 150",
            ),
            ("TERRIBLE DOMINGO - 22.11 - +18", "Mar del Plata", "Mar del Plata"),
            (
                "LA LLAMADA",
                "Mar Del Plata",
                "Mar Del Plata, Av. Pedro Luro 2335, Mar del Plata, Buenos Aires, Argentina",
            ),
            ("Argy", "Mar Del Plata", "Mar Del Plata, 2299-2399"),
            ("LUN 11.1 - LADIES NIGHT (+18)", "MAR DEL PLATA", "MAR DEL PLATA"),
            (
                "MAKE ME FLY - OPEN AIR",
                "Avenida Patricio Peralta Ramos",
                "Avenida Patricio Peralta Ramos",
            ),
            ("Sunset Night - Nick Warren", "Playa Grande", "Playa Grande"),
            ("Fiesta Bresh en Mar del Plata - 22 de Enero", "", ""),
        ]
        for title, venue_name, venue_raw in rows:
            assert venues.resolve_event(
                title=title, venue_name=venue_name, venue_raw=venue_raw
            ) is None, title


class TestRemainingVenueRows:
    """The rows of the S2 snapshot that name a room and a street address but
    had no registry entry. Each row keeps the exact published strings; the
    expected value is the registry entry that now covers it.
    """

    def test_samsara_beach_on_ruta_provincial_11(self):
        assert venues.resolve_event(
            title="SAMSARA | Christmas Edition | Jueves 24 dic",
            venue_name="SAMSARA BEACH",
            venue_raw="SAMSARA BEACH, Ruta Provincial 11 4866, Mar del Plata",
        ) == ("samsara-beach", "Samsara Beach")

    def test_immc_on_chacabuco(self):
        assert venues.resolve_event(
            title="RODA DE SAMBA del Insti",
            venue_name="IMMC",
            venue_raw="IMMC, Chacabuco 3639, B7600HNM Mar del Plata, Provincia de Buenos Aires",
        ) == ("immc", "IMMC")

    def test_the_clap_on_jujuy(self):
        # Cual Pinta publishes the sign in bold mathematical capitals.
        assert venues.resolve_event(
            title="FAUFER + BRANCO SIMON",
            venue_name="𝐓𝐇𝐄 𝐂𝐋𝐀𝐏",
            venue_raw=(
                "𝐓𝐇𝐄 𝐂𝐋𝐀𝐏, Jujuy 1559, B7600DCE Mar del Plata,"
                " Provincia de Buenos Aires"
            ),
        ) == ("the-clap", "The Clap")

    def test_fisker_on_guemes(self):
        assert venues.resolve_event(
            title="Viernes de Cartas en Fisker",
            venue_name="Fisker",
            venue_raw=(
                "Fisker, Martín Miguel de Güemes 4790, B7600 Mar del Plata,"
                " Provincia de Buenos Aires"
            ),
        ) == ("fisker", "Fisker")

    def test_lina_club_cultural_on_chacabuco(self):
        assert venues.resolve_event(
            title="Ciclo 'Ayer, hoy y siempre': Conversación sobre Yo, robot de Isaac Asimov",
            venue_name="Lina Club Cultural",
            venue_raw="Lina Club Cultural, Chacabuco 3591 Mar del Plata",
        ) == ("lina-club-cultural", "Lina Club Cultural")

    def test_fichin_bar_on_rawson(self):
        assert venues.resolve_event(
            title="KARAOKE",
            venue_name="Fichin Bar",
            venue_raw=(
                "Fichin Bar, Rawson 2019, B7600 Mar del Plata,"
                " Provincia de Buenos Aires"
            ),
        ) == ("fichin-bar", "Fichin Bar")

    def test_club_de_foodies_on_lamadrid(self):
        assert venues.resolve_event(
            title="Tu Ruta - Show en Vivo",
            venue_name="Club de Foodies",
            venue_raw=(
                "Club de Foodies, Lamadrid 2372, B7600EHF Mar del Plata,"
                " Provincia de Buenos Aires"
            ),
        ) == ("club-de-foodies", "Club de Foodies")

    def test_casino_central_de_mar_del_plata_is_the_registered_casino(self):
        # Same hall as the existing aliases, spelled with the "de".
        assert venues.resolve_event(
            title="LA TM - MAR DEL PLATA",
            venue_name="Casino Central de Mar del Plata",
            venue_raw="Casino Central de Mar del Plata",
        ) == ("casinos-de-la-provincia", "Casinos de la Provincia")
        assert venues.resolve("Casino Central de Mar del Plata") == (
            "casinos-de-la-provincia",
            "Casinos de la Provincia",
        )


class TestPipelineVenueStats:
    @staticmethod
    def _event(title, venue_name="", venue_raw=""):
        from lib.schema import Event

        return Event(
            source="quehacemos",
            source_event_id="1",
            title=title,
            venue_name=venue_name,
            venue_raw=venue_raw,
            date_start="2027-01-10",
            date_end="2027-01-10",
            occurrences=["2027-01-10"],
        )

    def test_title_named_venue_is_materialised_into_the_event(self):
        # The counter used to resolve the title again, so a row could be
        # counted as resolved while the event itself carried no venue. The
        # pipeline now writes the registry name into the event, and the
        # counter reads only what the event carries.
        from run_pipeline import _materialise_venues, _venue_stats

        events = [
            self._event("Max Styler en MUTE"),
            self._event(
                "SAMSARA | Christmas Edition | Jueves 24 dic",
                "SAMSARA BEACH",
                "SAMSARA BEACH, Ruta Provincial 11 4866, Mar del Plata",
            ),
            self._event("CAMELPHAT", "", ", Ruta Provincial 11"),
        ]

        _materialise_venues(events)

        assert events[0].venue_name == "Mute Club de Mar"
        # A source that already names a resolvable venue keeps its own string.
        assert events[1].venue_name == "SAMSARA BEACH"
        # Nothing is invented from a route: the row stays unresolved.
        assert events[2].venue_name == ""
        assert _venue_stats(events) == {"resolved": 2, "unknown": 1}

    def test_title_only_row_ends_with_the_venue_in_the_event(self):
        from run_pipeline import _materialise_venues, _venue_stats

        event = self._event("Max Styler en MUTE")

        _materialise_venues([event])

        assert resolve(event.venue_name) == ("mute-club-de-mar", "Mute Club de Mar")
        assert event.to_dict()["venue_name"] == "Mute Club de Mar"
        assert _venue_stats([event]) == {"resolved": 1, "unknown": 0}

    def test_counter_does_not_resolve_the_title_on_its_own(self):
        # The count must describe the events, not a second independent
        # inference: an unmaterialised row is unknown however its title reads.
        from run_pipeline import _venue_stats

        events = [
            self._event("Max Styler en MUTE"),
            self._event("CAMELPHAT", "", ", Ruta Provincial 11"),
        ]

        assert _venue_stats(events) == {"resolved": 0, "unknown": 2}


class TestVenueKey:
    def test_resolvable_venue_uses_registry_id(self):
        assert venue_key("Brew House") == "brew-house"

    def test_unknown_venue_falls_back_to_normalized_name(self):
        assert venue_key("Bolichito de la Esquina!") == "bolichito de la esquina"


class TestRegistryConsistency:
    def test_ids_are_unique(self):
        ids = [venue["id"] for venue in all_venues()]
        assert len(ids) == len(set(ids))

    def test_every_alias_resolves_to_its_own_venue(self):
        for venue in all_venues():
            for alias in venue["aliases"]:
                assert resolve(alias) == (venue["id"], venue["name"]), alias

    def test_every_venue_has_at_least_one_alias(self):
        for venue in all_venues():
            assert venue["aliases"], venue["id"]

    def test_every_venue_declares_its_display_name_as_an_alias(self):
        for venue in all_venues():
            assert resolve(venue["name"]) == (venue["id"], venue["name"]), venue["id"]

    def test_corpus_venue_names_all_resolve(self):
        # Names observed in data/raw/*.json; keep the registry honest when the
        # corpus grows.
        observed = [
            "Brew House", "Teatro Municipal Colón", "Arena Mar del Plata", "Club TRI",
            "Vorterix", "Abbey Road - Concert Bar", "Centro de Arte Radio City - Roxy - Melany",
            "Centro Cultural Victoria Ocampo. Villa Victoria", "Bendu",
            "La Bancaria - Sala Arturo Jauretche", "Chauvin", "Capilla del Divino Maestro - Pías Discípulas",
            "Teatro Tronador", "Sheraton Mar del Plata - Auditorium Victoria Ocampo",
            "Teatro Auditorium - Sala Roberto J. Payró", "Vinoteca Perrier",
            "Estadio Polideportivo Islas Malvinas", "Casa de Madera",
            "Teatro Auditorium - Sala Gregorio Nachman",
            "Archivo Museo Histórico Municipal Don Roberto T. Barili. Villa Mitre", "José Hernandez",
            "Sheraton Mar del Plata", "Wolfgang Teatro Bar", "Polideportivo Islas Malvinas",
            "Club 39 Cervecería", "Espacio La Rosa", "Ogham diagonal", "Casa del Mar",
            "NH Gran Hotel Provincial", "Teatro Municipal Colon", "CCAVE", "Microteatro Chauvin",
            "Villa Victoria Ocampo", "Teatro San Martin", "PLAZA DE LA MÚSICA",
            "Lo de Julio Cerveceria", "Ciudad Cultural Brew House",
        ]
        for name in observed:
            assert resolve(name) is not None, name
