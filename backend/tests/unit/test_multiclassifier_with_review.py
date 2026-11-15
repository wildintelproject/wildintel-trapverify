"""A combined dataset ("Classifiers and reference") used as a session with the review features."""
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from multiclassifier import run

from .test_multiclassifier import _cfg, archive  # noqa: F401  (the synthetic archive fixture)

SPECIES = ["Cervus elaphus", "Dama dama", "Sus scrofa"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    import services.session_service as ss
    from main import app
    monkeypatch.setattr(ss, "_state", {})
    monkeypatch.setattr(ss, "SESSION_FILE", tmp_path / "last.json")
    monkeypatch.setattr(ss, "RECENT_SESSIONS_FILE", tmp_path / "recent.json")
    monkeypatch.setattr(ss, "APP_DIR", tmp_path)
    return TestClient(app)


def _session(client, archive, tmp_path, **extra):  # noqa: F811
    res = run(_cfg(archive), tmp_path / "combined")
    body = {"camtrap_dir": res["camtrap_dir"], "output_dir": str(tmp_path / "out"), "target_species": SPECIES,
            "study_start": "2024-03-01", "study_end": "2024-04-30", "occasion_days": 5, "gap_seconds": 60,
            "min_score": 0, "record_rejection_species": True, **extra}
    r = client.post("/api/setup", json=body)
    assert r.status_code == 200, r.text
    return Path(r.json()["session_dir"]), Path(res["camtrap_dir"])


def test_the_review_shows_the_events_the_combination_kept(client, archive, tmp_path):  # noqa: F811
    sd, combined = _session(client, archive, tmp_path)
    obs = pd.read_csv(combined / "observations.csv", dtype=str).fillna("")
    flt = obs[obs["observationTags"].eq("camtrapverify:filtered")]
    filtered = set(zip(flt["mediaID"], flt["scientificName"]))          # a photo can be filtered for one species only
    shown = {(f["mediaId"], sp.replace("_", " ")) for sp in ("Cervus_elaphus", "Dama_dama", "Sus_scrofa")
             for e in client.get(f"/api/species/{sp}/events", params={"iteration": 1}).json() for f in e["frames"]}
    assert filtered and shown and not (shown & filtered)


def test_review_tags_are_added_next_to_the_combination_tags(client, archive, tmp_path):  # noqa: F811
    sd, combined = _session(client, archive, tmp_path)
    ev = client.get("/api/species/Dama_dama/events", params={"iteration": 1}).json()
    assert ev
    client.post("/api/decisions", json={"species": "Dama_dama", "iteration": 1, "confirmed": [ev[0]["repObsId"]],
                                        "uncertain": [ev[1]["repObsId"]] if len(ev) > 1 else []})
    client.get("/api/results")
    v = pd.read_csv(sd / "camtrap_dp_verified" / "observations.csv", dtype=str).fillna("")
    tags = v["observationTags"]
    assert tags.str.contains("camtrapverify:filtered").any()           # kept from the combination
    assert tags.str.contains("camtrapverify:confirmed").any()          # added by the review
    original = pd.read_csv(combined / "observations.csv", dtype=str).fillna("")
    assert len(v) == len(original)                                     # nothing lost, nothing duplicated


def test_effort_report_and_ttd_work_with_a_combined_dataset(client, archive, tmp_path):  # noqa: F811
    sd, _ = _session(client, archive, tmp_path, review_order="time")
    client.get("/api/species/Dama_dama/events", params={"iteration": 1})
    r = client.get("/api/results")
    assert r.status_code == 200 and r.json()["effort_by_species"]
    assert (sd / "occupancy_inputs" / "ttd_naive_Dama_dama.csv").exists()
