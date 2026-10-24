"""Wave 4 acceptance: Qué Hacemos and Fanz/Chauvin are wired end to end."""

from lib.venues import resolve
from run_pipeline import MODULES
import build_site


def test_pipeline_registers_the_wave4_sources():
    names = {name for name, _module in MODULES}
    assert {"quehacemos", "fanz"} <= names


def test_site_labels_and_order_cover_the_wave4_sources():
    assert build_site.SOURCE_LABELS["quehacemos"] == "Qué Hacemos"
    assert build_site.SOURCE_LABELS["chauvin"] == "Chauvin"
    order = build_site.SOURCE_ORDER
    assert "quehacemos" in order
    assert "chauvin" in order


def test_chauvin_sells_its_own_tickets_so_it_outranks_the_aggregator():
    order = build_site.SOURCE_ORDER
    assert order.index("chauvin") < order.index("quehacemos")


def test_chauvin_creation_room_alias_resolves_to_the_venue():
    # Fanz reports "Chauvin Centro de creación" (creación, not recreación).
    assert resolve("Chauvin Centro de creación") == ("chauvin", "Chauvin")
