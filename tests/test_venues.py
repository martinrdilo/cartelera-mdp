"""Tests for the venue registry and name resolution."""

import pytest

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
