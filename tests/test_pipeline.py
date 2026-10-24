"""Tests for the robust pipeline runner (partial-failure policy, outputs)."""

import json
import threading

import run_pipeline
from lib.schema import Event


class GoodCollector:
    """Minimal collector: one raw record, one normalized event."""

    @staticmethod
    def collect():
        return [{"source": "good", "title": "Dante Spinetta", "venue": "Club TRI", "date": "14/11/2026"}]

    @staticmethod
    def normalize(records):
        return [
            Event(
                source="good",
                source_event_id="dante",
                title="Dante Spinetta",
                venue_name="Club TRI",
                date_start="2026-11-14",
                occurrences=["2026-11-14"],
            )
        ]


class FailingCollector:
    """Collector that always fails (network, HTTP, parse, anything)."""

    @staticmethod
    def collect():
        raise RuntimeError("source down")


def test_partial_failure_keeps_outputs_and_exits_nonzero(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    normalized = data_dir / "events_normalized.json"
    deduped = data_dir / "events_deduped.json"
    normalized.write_text('{"sentinel": "normalized"}', encoding="utf-8")
    deduped.write_text('{"sentinel": "deduped"}', encoding="utf-8")

    exit_code = run_pipeline.run(
        modules=(("good", GoodCollector), ("bad", FailingCollector)), data_dir=data_dir
    )

    assert exit_code != 0
    assert json.loads(normalized.read_text(encoding="utf-8")) == {"sentinel": "normalized"}
    assert json.loads(deduped.read_text(encoding="utf-8")) == {"sentinel": "deduped"}
    error = json.loads((data_dir / "raw" / "bad.error.json").read_text(encoding="utf-8"))
    assert error["source"] == "bad"
    assert error["error_type"] == "RuntimeError"
    assert "source down" in error["error"]
    assert not (data_dir / "last_run.json").exists()


def test_success_writes_outputs_and_last_run(tmp_path):
    data_dir = tmp_path / "data"

    exit_code = run_pipeline.run(modules=(("good", GoodCollector),), data_dir=data_dir)

    assert exit_code == 0
    events = json.loads((data_dir / "events_normalized.json").read_text(encoding="utf-8"))
    assert len(events) == 1
    assert events[0]["occurrences"] == ["2026-11-14"]
    deduped = json.loads((data_dir / "events_deduped.json").read_text(encoding="utf-8"))
    assert deduped["total_normalized"] == 1
    assert deduped["unique_events"] == 1
    last_run = json.loads((data_dir / "last_run.json").read_text(encoding="utf-8"))
    assert last_run["sources"]["good"] == {"raw": 1, "normalized": 1}
    assert last_run["totals"]["normalized"] == 1
    assert last_run["totals"]["unique"] == 1
    assert not list(data_dir.glob("*.tmp"))


class TestWriteJsonAtomic:
    def test_replaces_a_lone_surrogate(self, tmp_path):
        # A source can emit a broken JSON-LD escape ("\ud835") that is not
        # valid UTF-8; the runner must not fail the whole run on it.
        path = tmp_path / "out.json"

        run_pipeline._write_json_atomic(path, {"title": "bad \ud835 char"})

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["title"].startswith("bad ")
        assert not list(tmp_path.glob("*.tmp"))


class TestCollectConcurrency:
    def test_modules_collect_concurrently(self):
        barrier = threading.Barrier(2, timeout=3)

        class Slow:
            def __init__(self, name):
                self.name = name

            def collect(self):
                barrier.wait()
                return [{"source": self.name}]

        raw, errors = run_pipeline._collect_all((("a", Slow("a")), ("b", Slow("b"))))

        assert errors == {}
        assert list(raw) == ["a", "b"]

    def test_one_failure_does_not_hide_the_others(self):
        class Good:
            def collect(self):
                return [{"source": "good"}]

        class Bad:
            def collect(self):
                raise RuntimeError("boom")

        raw, errors = run_pipeline._collect_all((("good", Good()), ("bad", Bad())))

        assert list(raw) == ["good"]
        assert set(errors) == {"bad"}
