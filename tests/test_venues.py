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
