"""Integration tests for the FastAPI endpoints in main.py."""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Clear the global _state dict before every test."""
    import main
    monkeypatch.setattr(main, "_state", {})


@pytest.fixture
def client():
    from main import app
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def setup_session(client, camtrap_dir, tmp_path):
    """POST /api/setup and return the response JSON."""
    out = tmp_path / "out"
    resp = client.post("/api/setup", json={
        "camtrap_dir":      str(camtrap_dir),
        "output_dir":       str(out),
        "target_species":   ["Vulpes vulpes"],
        "study_start":      "2025-11-01",
        "study_end":        "2025-11-10",
        "occasion_days":    5,
        "total_iterations": 100_000,
        "gap_seconds":      60,
        "min_score":        0.5,
    })
    assert resp.status_code == 200
    return resp.json()


# ─── /api/health ──────────────────────────────────────────────────────────────

def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ─── /api/fs/inspect ──────────────────────────────────────────────────────────

def test_fs_inspect_returns_species(client, camtrap_dir):
    resp = client.get("/api/fs/inspect", params={"path": str(camtrap_dir)})
    assert resp.status_code == 200
    data = resp.json()
    assert "Vulpes vulpes" in data["species"]
    assert data["study_start"] is not None
    assert data["study_end"] is not None

def test_fs_inspect_missing_observations(client, tmp_path):
    resp = client.get("/api/fs/inspect", params={"path": str(tmp_path)})
    assert resp.status_code == 400

def test_fs_inspect_date_range_order(client, camtrap_dir):
    resp = client.get("/api/fs/inspect", params={"path": str(camtrap_dir)})
    data = resp.json()
    assert data["study_start"] <= data["study_end"]


# ─── /api/fs/browse ───────────────────────────────────────────────────────────

def test_fs_browse_home(client):
    resp = client.get("/api/fs/browse")
    assert resp.status_code == 200
    data = resp.json()
    assert "current" in data
    assert "dirs" in data
    assert isinstance(data["dirs"], list)

def test_fs_browse_specific_path(client, tmp_path):
    (tmp_path / "subdir").mkdir()
    resp = client.get("/api/fs/browse", params={"path": str(tmp_path)})
    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()["dirs"]]
    assert "subdir" in names

def test_fs_browse_hidden_dirs_excluded(client, tmp_path):
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "visible").mkdir()
    resp = client.get("/api/fs/browse", params={"path": str(tmp_path)})
    names = [d["name"] for d in resp.json()["dirs"]]
    assert ".hidden" not in names
    assert "visible" in names


# ─── /api/state ───────────────────────────────────────────────────────────────

def test_get_state_no_session(client):
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is False
    assert "default_output_dir" in data

def test_get_state_after_setup(client, setup_session):
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert "config" in data
    assert "session_dir" in data


# ─── /api/setup ───────────────────────────────────────────────────────────────

def test_setup_returns_ok(setup_session):
    assert setup_session["ok"] is True

def test_setup_returns_candidate_count(setup_session):
    assert setup_session["n_candidates"] > 0

def test_setup_returns_combos(setup_session):
    assert setup_session["n_combos"] == 3

def test_setup_creates_session_dir(setup_session):
    session_dir = Path(setup_session["session_dir"])
    assert session_dir.exists()
    assert (session_dir / "config.json").exists()
    assert (session_dir / "candidate_manifest.csv").exists()

def test_setup_creates_output_dirs(setup_session):
    session_dir = Path(setup_session["session_dir"])
    assert (session_dir / "camtrap_dp_verified").exists()
    assert (session_dir / "occupancy_inputs").exists()

def test_setup_missing_camtrap_dir(client, tmp_path):
    resp = client.post("/api/setup", json={
        "camtrap_dir":    str(tmp_path / "nonexistent"),
        "output_dir":     str(tmp_path / "out"),
        "target_species": ["Vulpes vulpes"],
        "study_start":    "2025-11-01",
        "study_end":      "2025-11-10",
        "occasion_days":  5,
        "total_iterations": 100_000,
        "gap_seconds":    60,
        "min_score":      0.5,
    })
    assert resp.status_code == 400


# ─── /api/species ─────────────────────────────────────────────────────────────

def test_list_species_no_session(client):
    resp = client.get("/api/species")
    assert resp.status_code == 400

def test_list_species_returns_one_species(client, setup_session):
    resp = client.get("/api/species")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["species_safe"] == "Vulpes_vulpes"

def test_list_species_has_thumbnails(client, setup_session):
    resp = client.get("/api/species")
    sp = resp.json()[0]
    assert "thumbnails" in sp
    assert isinstance(sp["thumbnails"], list)

def test_list_species_initial_progress(client, setup_session):
    resp = client.get("/api/species")
    sp = resp.json()[0]
    assert sp["n_total_combos"] == 3
    assert sp["n_confirmed_combos"] == 0
    assert sp["n_resolved"] == 0


# ─── /api/species/{species}/events ────────────────────────────────────────────

def test_get_events_no_session(client):
    resp = client.get("/api/species/Vulpes_vulpes/events")
    assert resp.status_code == 400

def test_get_events_round1(client, setup_session):
    resp = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1})
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 3

def test_get_events_unknown_species_returns_empty(client, setup_session):
    resp = client.get("/api/species/Panthera_leo/events", params={"iteration": 1})
    assert resp.status_code == 200
    assert resp.json() == []


# ─── /api/decisions ───────────────────────────────────────────────────────────

def test_get_decisions_empty(client, setup_session):
    resp = client.get("/api/decisions", params={"species": "Vulpes_vulpes", "iteration": 1})
    assert resp.status_code == 200
    assert resp.json() == {"confirmed": []}

def test_post_decisions_save_and_retrieve(client, setup_session):
    # Get events to find a valid observationID
    events = client.get(
        "/api/species/Vulpes_vulpes/events", params={"iteration": 1}
    ).json()
    rep_obs_id = events[0]["repObsId"]

    resp = client.post("/api/decisions", json={
        "species":   "Vulpes_vulpes",
        "iteration": 1,
        "confirmed": [rep_obs_id],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["saved"] == 1

def test_post_decisions_marks_species_progress(client, setup_session):
    events = client.get(
        "/api/species/Vulpes_vulpes/events", params={"iteration": 1}
    ).json()
    # Confirm all 3 cells at once
    confirmed_ids = [e["repObsId"] for e in events]
    client.post("/api/decisions", json={
        "species":   "Vulpes_vulpes",
        "iteration": 1,
        "confirmed": confirmed_ids,
    })
    sp = client.get("/api/species").json()[0]
    assert sp["n_confirmed_combos"] == 3

def test_post_decisions_done_when_all_confirmed(client, setup_session):
    events = client.get(
        "/api/species/Vulpes_vulpes/events", params={"iteration": 1}
    ).json()
    confirmed_ids = [e["repObsId"] for e in events]
    resp = client.post("/api/decisions", json={
        "species":   "Vulpes_vulpes",
        "iteration": 1,
        "confirmed": confirmed_ids,
    })
    assert resp.json()["done"] is True


# ─── /api/species/{species}/review ────────────────────────────────────────────

def test_get_review_no_session(client):
    resp = client.get("/api/species/Vulpes_vulpes/review")
    assert resp.status_code == 400

def test_get_review_after_completion(client, setup_session):
    events = client.get(
        "/api/species/Vulpes_vulpes/events", params={"iteration": 1}
    ).json()
    confirmed_ids = [e["repObsId"] for e in events]
    client.post("/api/decisions", json={
        "species":   "Vulpes_vulpes",
        "iteration": 1,
        "confirmed": confirmed_ids,
    })
    review = client.get("/api/species/Vulpes_vulpes/review").json()
    assert len(review) == 3
    statuses = {e["status"] for e in review}
    assert statuses == {"confirmed"}

def test_get_review_unknown_species_returns_empty(client, setup_session):
    resp = client.get("/api/species/Panthera_leo/review")
    assert resp.status_code == 200
    assert resp.json() == []


# ─── /api/species/{species}/decisions (PUT) ───────────────────────────────────

def test_put_decisions_updates_confirmed(client, setup_session):
    # Confirm all 3 via normal flow, then update to only 1
    events = client.get(
        "/api/species/Vulpes_vulpes/events", params={"iteration": 1}
    ).json()
    all_ids = [e["repObsId"] for e in events]
    client.post("/api/decisions", json={
        "species": "Vulpes_vulpes", "iteration": 1, "confirmed": all_ids,
    })

    # Now update: keep only 1 key confirmed
    one_key = events[0]["key"]
    resp = client.put("/api/species/Vulpes_vulpes/decisions", json={
        "confirmed_keys": [one_key],
    })
    assert resp.status_code == 200
    assert resp.json()["confirmed"] == 1

def test_put_decisions_regenerates_outputs(client, setup_session):
    events = client.get(
        "/api/species/Vulpes_vulpes/events", params={"iteration": 1}
    ).json()
    client.post("/api/decisions", json={
        "species": "Vulpes_vulpes", "iteration": 1,
        "confirmed": [e["repObsId"] for e in events],
    })
    resp = client.put("/api/species/Vulpes_vulpes/decisions", json={
        "confirmed_keys": [events[0]["key"]],
    })
    assert resp.status_code == 200
    # Check verified CamtrapDP was regenerated
    session_dir = Path(client.get("/api/state").json()["session_dir"])
    obs = pd.read_csv(session_dir / "camtrap_dp_verified" / "observations.csv", dtype=str)
    human_count = (obs["classificationMethod"] == "human").sum()
    assert human_count == 1


# ─── /api/rejected ────────────────────────────────────────────────────────────

def test_get_rejected_empty(client, setup_session):
    resp = client.get("/api/rejected")
    assert resp.status_code == 200
    assert resp.json() == {"rejected": []}

def test_post_reject_burst(client, setup_session):
    # m001 and m002 are in the same burst
    resp = client.post("/api/reject", json={"mediaId": "m001"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    removed = set(data["removed"])
    # Both frames of the burst should be removed
    assert "m001" in removed
    assert "m002" in removed

def test_post_reject_excludes_from_gallery(client, setup_session):
    client.post("/api/reject", json={"mediaId": "m004"})   # SITE_B occ1
    events = client.get(
        "/api/species/Vulpes_vulpes/events", params={"iteration": 1}
    ).json()
    keys = {e["key"] for e in events}
    assert "SITE_B_occ1_Vulpes_vulpes" not in keys

def test_post_unreject(client, setup_session):
    client.post("/api/reject", json={"mediaId": "m004"})
    client.post("/api/unreject", json={"media": ["m004"]})
    events = client.get(
        "/api/species/Vulpes_vulpes/events", params={"iteration": 1}
    ).json()
    keys = {e["key"] for e in events}
    assert "SITE_B_occ1_Vulpes_vulpes" in keys


# ─── /api/results ─────────────────────────────────────────────────────────────

def test_get_results_no_session(client):
    resp = client.get("/api/results")
    assert resp.status_code == 400

def test_get_results_initial_all_unverified(client, setup_session):
    resp = client.get("/api/results")
    assert resp.status_code == 200
    data = resp.json()
    assert data["confirmed"] == 0
    assert data["rejected"] == 0
    assert data["unverified"] == 3

def test_get_results_after_confirming(client, setup_session):
    events = client.get(
        "/api/species/Vulpes_vulpes/events", params={"iteration": 1}
    ).json()
    confirmed_ids = [e["repObsId"] for e in events]
    client.post("/api/decisions", json={
        "species": "Vulpes_vulpes", "iteration": 1, "confirmed": confirmed_ids,
    })
    data = client.get("/api/results").json()
    assert data["confirmed"] == 3
    assert data["unverified"] == 0

def test_get_results_sequence_stats_present(client, setup_session):
    data = client.get("/api/results").json()
    assert "seq_total" in data
    assert "seq_confirmed" in data
    assert "seq_rejected" in data
    assert "seq_unverified" in data
    assert "by_species_seqs" in data

def test_get_results_seq_total_matches_candidate_bursts(client, setup_session):
    # 4 unique bursts: SITE_A/occ1 burst0+burst1, SITE_A/occ2 burst0, SITE_B/occ1 burst0
    data = client.get("/api/results").json()
    assert data["seq_total"] == 4

def test_get_results_by_species_row(client, setup_session):
    data = client.get("/api/results").json()
    assert len(data["by_species"]) == 1
    sp = data["by_species"][0]
    assert sp["species"] == "Vulpes vulpes"
    assert "confirmed" in sp and "rejected" in sp and "unverified" in sp
