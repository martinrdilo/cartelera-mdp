"""Wave-3 acceptance probes: wired sources, snapshot and site contracts."""

import json
from pathlib import Path

import build_site
import run_pipeline
from collectors import cualpinta, elevenflow, passline

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def test_wave3_collectors_are_wired_and_contractual():
    wired = {name for name, _ in run_pipeline.MODULES}
    assert {"cualpinta", "elevenflow", "passline"} <= wired
    for module in (cualpinta, elevenflow, passline):
        assert callable(module.collect) and callable(module.normalize)
        assert module.USER_AGENT == "cartelera-mdp-pipeline/0.2 (local research)"
        assert module.normalize([]) == []


def test_wave3_labels_and_order():
    assert {"cualpinta", "elevenflow", "passline"} <= set(build_site.SOURCE_LABELS)
    assert all(
        source in build_site.SOURCE_ORDER
        for source in ("cualpinta", "elevenflow", "passline")
    )
