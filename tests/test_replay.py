import importlib.util
import json
from pathlib import Path

from roadlog.recorder import Recorder

ROOT = Path(__file__).resolve().parent.parent


def load_builder():
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_recorder_labels_every_message():
    recorder = Recorder()
    recorder.capture("fleet/vehicles/TRK-01/telemetry", {"vehicle_id": "TRK-01"})
    recorder.capture("fleet/vehicles/TRK-01/events", {"kind": "speeding"})
    recorder.capture("fleet/presence/box-1", {"status": "offline"})
    kinds = [item["type"] for item in recorder.timeline]
    assert kinds == ["telemetry", "events", "presence"]
    assert recorder.timeline[2]["data"]["hostname"] == "box-1"
    assert all(item["at"] >= 0 for item in recorder.timeline)


def test_the_bundled_recording_is_a_real_session():
    session = json.loads((ROOT / "site" / "recording.json").read_text(encoding="utf-8"))
    kinds = {item["type"] for item in session["timeline"]}
    assert {"telemetry", "events"} <= kinds
    assert len(session["vehicles"]) == 8 and len(session["routes"]) == 8
    times = [item["at"] for item in session["timeline"]]
    assert times == sorted(times)


def test_the_site_replays_with_the_same_dashboard(tmp_path):
    site = load_builder().build(tmp_path / "site")
    page = (site / "index.html").read_text(encoding="utf-8")
    assert page.index("replay.js") < page.index("static/app.js")
    assert "Recorded replay" in page
    assert (site / "static" / "app.js").exists() and (site / "recording.json").exists()
