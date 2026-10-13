"""Tests for Spanish date/time parsing helpers."""

from datetime import date

from lib.dates import extract_time, parse_ddmmyyyy, parse_spanish_date, to_iso

TODAY = date(2026, 10, 13)


class TestParseDdmmyyyy:
    def test_plain_date(self):
        assert parse_ddmmyyyy("15/10/2026") == date(2026, 10, 15)

    def test_date_inside_text(self):
        assert parse_ddmmyyyy("desde: 07/11/2026") == date(2026, 11, 7)

    def test_single_digit_parts(self):
        assert parse_ddmmyyyy("1/9/2026") == date(2026, 9, 1)

    def test_invalid_date_returns_none(self):
        assert parse_ddmmyyyy("32/13/2026") is None
        assert parse_ddmmyyyy("sin fecha") is None
        assert parse_ddmmyyyy("") is None


class TestParseSpanishDate:
    def test_upcoming_date_uses_current_year(self):
        assert parse_spanish_date("Mié 14 de Octubre", today=TODAY) == date(2026, 10, 14)

    def test_weekday_accent_is_optional(self):
        assert parse_spanish_date("Mie 14 de Octubre", today=TODAY) == date(2026, 10, 14)

    def test_past_date_rolls_to_next_year(self):
        assert parse_spanish_date("Mié 14 de Octubre", today=date(2026, 10, 20)) == date(2027, 10, 14)

    def test_yesterday_is_kept_in_current_year(self):
        # Agendas may still list an event that happened yesterday.
        assert parse_spanish_date("Lun 12 de Octubre", today=TODAY) == date(2026, 10, 12)

    def test_today_is_kept(self):
        assert parse_spanish_date("Mar 13 de Octubre", today=TODAY) == date(2026, 10, 13)

    def test_explicit_year_is_respected(self):
        assert parse_spanish_date("Sáb 14 de Noviembre de 2026", today=TODAY) == date(2026, 11, 14)

    def test_uppercase_month(self):
        assert parse_spanish_date("DOM 08 DE NOVIEMBRE", today=TODAY) == date(2026, 11, 8)

    def test_no_date_returns_none(self):
        assert parse_spanish_date("Próximamente", today=TODAY) is None


class TestExtractTime:
    def test_hour_with_hs_suffix(self):
        assert extract_time("19 Hs") == "19:00"

    def test_hour_with_h_suffix(self):
        assert extract_time("20 HS") == "20:00"

    def test_hh_mm(self):
        assert extract_time("20:00") == "20:00"

    def test_dot_separator(self):
        assert extract_time("23.59 Hs") == "23:59"

    def test_bare_hour(self):
        assert extract_time("22") == "22:00"

    def test_time_inside_text(self):
        assert extract_time("jueves 18:00") == "18:00"

    def test_no_time_returns_none(self):
        assert extract_time("") is None
        assert extract_time("a confirmar") is None


class TestToIso:
    def test_date_to_iso(self):
        assert to_iso(date(2026, 10, 14)) == "2026-10-14"

    def test_none_to_iso(self):
        assert to_iso(None) is None
