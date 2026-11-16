"""Integration tests for the FastAPI endpoints in main.py."""
import io
import json
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_state(monkeypatch, tmp_path):
    """Clear in-memory state and redirect session persistence to a temp dir."""
    import services.session_service as session_service
    monkeypatch.setattr(session_service, "_state", {})
    monkeypatch.setattr(session_service, "SESSION_FILE", tmp_path / "last_session.json")
    monkeypatch.setattr(session_service, "RECENT_SESSIONS_FILE", tmp_path / "recent_sessions.json")
    monkeypatch.setattr(session_service, "APP_DIR", tmp_path)


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

def test_fs_inspect_no_datapackage_json(client, camtrap_dir):
    """The fixture ships no datapackage.json — nothing to validate."""
    resp = client.get("/api/fs/inspect", params={"path": str(camtrap_dir)})
    assert resp.json()["datapackage_errors"] is None

def test_fs_inspect_valid_datapackage_json(client, camtrap_dir):
    (camtrap_dir / "datapackage.json").write_text(json.dumps({
        "name": "test-package",
        "resources": [{"name": "observations", "path": "observations.csv"}],
    }))
    resp = client.get("/api/fs/inspect", params={"path": str(camtrap_dir)})
    assert resp.status_code == 200
    assert resp.json()["datapackage_errors"] == []

def test_fs_inspect_invalid_datapackage_json_is_non_blocking(client, camtrap_dir):
    """A broken datapackage.json is surfaced as a warning, not a 400."""
    (camtrap_dir / "datapackage.json").write_text("{ not valid json")
    resp = client.get("/api/fs/inspect", params={"path": str(camtrap_dir)})
    assert resp.status_code == 200
    assert resp.json()["datapackage_errors"]


# ─── /api/fs/check-images ─────────────────────────────────────────────────────

def test_check_images_all_missing_by_default(client, camtrap_dir):
    """Without image_base_dir, relative filePaths resolve against camtrap_dir itself — none exist."""
    resp = client.get("/api/fs/check-images", params={"camtrap_dir": str(camtrap_dir)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert data["missing"] == 5
    assert len(data["examples"]) == 5

def test_check_images_reports_permission_denied_separately_from_missing(client, camtrap_dir, monkeypatch):
    """A PermissionError while checking a file must be counted as permission_denied,
    not lumped in with genuinely missing files."""
    img_dir = camtrap_dir / "img"
    img_dir.mkdir()
    for i in range(5):
        (img_dir / f"frame{i}.jpg").write_bytes(b"\xff\xd8\xff\xe0")

    real_exists = Path.exists

    def fake_exists(self):
        if self.name == "frame0.jpg":
            raise PermissionError("denied")
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    resp = client.get("/api/fs/check-images", params={
        "camtrap_dir": str(camtrap_dir), "image_base_dir": str(camtrap_dir),
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert data["permission_denied"] == 1
    assert data["missing"] == 0

def test_check_images_found_with_image_base_dir(client, camtrap_dir):
    img_dir = camtrap_dir / "img"
    img_dir.mkdir()
    for i in range(5):
        (img_dir / f"frame{i}.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    resp = client.get("/api/fs/check-images", params={
        "camtrap_dir": str(camtrap_dir), "image_base_dir": str(camtrap_dir),
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert data["missing"] == 0
    assert data["examples"] == []

def test_check_images_partial_missing(client, camtrap_dir):
    img_dir = camtrap_dir / "img"
    img_dir.mkdir()
    (img_dir / "frame0.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    (img_dir / "frame1.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    resp = client.get("/api/fs/check-images", params={
        "camtrap_dir": str(camtrap_dir), "image_base_dir": str(camtrap_dir),
    })
    data = resp.json()
    assert data["total"] == 5
    assert data["missing"] == 3

def test_check_images_missing_media_csv(client, tmp_path):
    resp = client.get("/api/fs/check-images", params={"camtrap_dir": str(tmp_path)})
    assert resp.status_code == 400

def test_check_images_skips_remote_urls(client, camtrap_dir):
    med = pd.read_csv(camtrap_dir / "media.csv", dtype=str)
    med.loc[len(med)] = {
        "mediaID": "m006", "deploymentID": "DEP1",
        "timestamp": "2025-11-02 13:00:00", "filePath": "https://example.com/frame.jpg",
    }
    med.to_csv(camtrap_dir / "media.csv", index=False)
    resp = client.get("/api/fs/check-images", params={"camtrap_dir": str(camtrap_dir)})
    data = resp.json()
    assert data["total"] == 5

def test_check_images_structured_deployment_filename_layout(client, camtrap_dir, tmp_path):
    """image_base_dir/deploymentID/fileName resolves even when filePath (img/frameN.jpg)
    does not match that layout at all."""
    img_root = tmp_path / "images"
    (img_root / "DEP1").mkdir(parents=True)
    (img_root / "DEP2").mkdir(parents=True)
    for name in ("frame0.jpg", "frame1.jpg", "frame2.jpg", "frame4.jpg"):
        (img_root / "DEP1" / name).write_bytes(b"\xff\xd8\xff\xe0")
    (img_root / "DEP2" / "frame3.jpg").write_bytes(b"\xff\xd8\xff\xe0")

    resp = client.get("/api/fs/check-images", params={
        "camtrap_dir": str(camtrap_dir), "image_base_dir": str(img_root),
    })
    data = resp.json()
    assert data["total"] == 5
    assert data["missing"] == 0

def test_check_images_flat_search_disabled_by_default(client, camtrap_dir, tmp_path):
    """Images loose in a folder (no deploymentID subfolder) stay missing unless flat_search=True."""
    img_root = tmp_path / "images"
    loose = img_root / "loose"
    loose.mkdir(parents=True)
    for name in ("frame0.jpg", "frame1.jpg", "frame2.jpg", "frame3.jpg", "frame4.jpg"):
        (loose / name).write_bytes(b"\xff\xd8\xff\xe0")

    resp = client.get("/api/fs/check-images", params={
        "camtrap_dir": str(camtrap_dir), "image_base_dir": str(img_root),
    })
    assert resp.json()["missing"] == 5

def test_check_images_flat_search_finds_loose_files(client, camtrap_dir, tmp_path):
    img_root = tmp_path / "images"
    loose = img_root / "loose"
    loose.mkdir(parents=True)
    for name in ("frame0.jpg", "frame1.jpg", "frame2.jpg", "frame3.jpg", "frame4.jpg"):
        (loose / name).write_bytes(b"\xff\xd8\xff\xe0")

    resp = client.get("/api/fs/check-images", params={
        "camtrap_dir": str(camtrap_dir), "image_base_dir": str(img_root), "flat_search": True,
    })
    assert resp.json()["missing"] == 0

def test_check_images_flat_search_reports_ambiguous(client, camtrap_dir, tmp_path):
    """frame0.jpg loose under two unrelated folders (neither named DEP1) is ambiguous."""
    img_root = tmp_path / "images"
    (img_root / "OTHER1").mkdir(parents=True)
    (img_root / "OTHER2").mkdir(parents=True)
    (img_root / "OTHER1" / "frame0.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    (img_root / "OTHER2" / "frame0.jpg").write_bytes(b"\xff\xd8\xff\xe0")

    resp = client.get("/api/fs/check-images", params={
        "camtrap_dir": str(camtrap_dir), "image_base_dir": str(img_root), "flat_search": True,
    })
    data = resp.json()
    assert len(data["ambiguous"]) == 1
    assert data["ambiguous"][0]["fileName"] == "frame0.jpg"

def test_check_images_no_ambiguous_key_without_flat_search(client, camtrap_dir, tmp_path):
    img_root = tmp_path / "images"
    (img_root / "OTHER1").mkdir(parents=True)
    (img_root / "OTHER2").mkdir(parents=True)
    (img_root / "OTHER1" / "frame0.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    (img_root / "OTHER2" / "frame0.jpg").write_bytes(b"\xff\xd8\xff\xe0")

    resp = client.get("/api/fs/check-images", params={
        "camtrap_dir": str(camtrap_dir), "image_base_dir": str(img_root),
    })
    assert resp.json()["ambiguous"] == []

def test_check_images_structured_takes_precedence_over_wrong_absolute_filepath(client, camtrap_dir, tmp_path):
    """A wrong absolute filePath must not stop the deploymentID/fileName lookup
    from finding the real file under image_base_dir."""
    med = pd.read_csv(camtrap_dir / "media.csv", dtype=str)
    med.loc[med["mediaID"] == "m001", "filePath"] = "/nonexistent/somewhere/frame0.jpg"
    med.to_csv(camtrap_dir / "media.csv", index=False)

    img_root = tmp_path / "images"
    (img_root / "DEP1").mkdir(parents=True)
    (img_root / "DEP1" / "frame0.jpg").write_bytes(b"\xff\xd8\xff\xe0")

    resp = client.get("/api/fs/check-images", params={
        "camtrap_dir": str(camtrap_dir), "image_base_dir": str(img_root),
    })
    data = resp.json()
    # m001 resolves via DEP1/frame0.jpg; the other 4 are still missing (not placed)
    assert data["missing"] == 4


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

def test_fs_browse_show_files_returns_files(client, tmp_path):
    (tmp_path / "data.csv").write_text("a,b\n1,2")
    resp = client.get("/api/fs/browse", params={"path": str(tmp_path), "show_files": "true"})
    assert resp.status_code == 200
    names = [f["name"] for f in resp.json()["files"]]
    assert "data.csv" in names

def test_fs_browse_show_files_false_no_files_key_empty(client, tmp_path):
    (tmp_path / "data.csv").write_text("a,b\n1,2")
    resp = client.get("/api/fs/browse", params={"path": str(tmp_path)})
    assert resp.status_code == 200
    assert resp.json()["files"] == []

def test_fs_browse_ext_filter_csv(client, tmp_path):
    (tmp_path / "results.csv").write_text("a,b")
    (tmp_path / "notes.txt").write_text("hello")
    resp = client.get("/api/fs/browse", params={"path": str(tmp_path), "show_files": "true", "ext": ".csv"})
    names = [f["name"] for f in resp.json()["files"]]
    assert "results.csv" in names
    assert "notes.txt" not in names

def test_fs_browse_hidden_files_excluded(client, tmp_path):
    (tmp_path / ".hidden.csv").write_text("secret")
    (tmp_path / "visible.csv").write_text("data")
    resp = client.get("/api/fs/browse", params={"path": str(tmp_path), "show_files": "true"})
    names = [f["name"] for f in resp.json()["files"]]
    assert ".hidden.csv" not in names
    assert "visible.csv" in names


# ─── /api/convert/deepfaune ───────────────────────────────────────────────────

def _write_deepfaune_csv(path, fmt="new"):
    if fmt == "new":
        pd.DataFrame({
            "filename": ["/imgs/SITE_A/f1.jpg", "/imgs/SITE_A/f2.jpg"],
            "date":     ["2025-11-02 10:00:00", "2025-11-02 10:00:30"],
            "top1":     ["red deer", "empty"],
            "score":    ["0.92", "0.10"],
            "site":     ["SITE_A", "SITE_A"],
        }).to_csv(path, index=False)
    elif fmt == "old":
        pd.DataFrame({
            "filename":       ["/imgs/SITE_A/f1.jpg"],
            "date":           ["2025-11-02 10:00:00"],
            "predictionbase": ["fox"],
            "scorebase":      ["0.88"],
            "site":           ["SITE_A"],
        }).to_csv(path, index=False)
    else:  # fmt == "both": both column sets present at once
        pd.DataFrame({
            "filename":       ["/imgs/SITE_A/f1.jpg"],
            "date":           ["2025-11-02 10:00:00"],
            "predictionbase": ["fox"],
            "scorebase":      ["0.88"],
            "top1":           ["red deer"],
            "score":          ["0.50"],
            "site":           ["SITE_A"],
        }).to_csv(path, index=False)

def test_convert_deepfaune_returns_camtrap_dir(client, tmp_path):
    csv = tmp_path / "results.csv"
    _write_deepfaune_csv(csv)
    resp = client.post("/api/convert/deepfaune", json={"csv_path": str(csv)})
    assert resp.status_code == 200
    assert "camtrap_dir" in resp.json()

def test_convert_deepfaune_filepath_not_resolved(client, tmp_path):
    """filePath in the generated media.csv is the raw filename column value
    -- locating the images is resolve_media_path()'s job at review time via
    image_base_dir, not this conversion's."""
    csv = tmp_path / "results.csv"
    _write_deepfaune_csv(csv)
    resp = client.post("/api/convert/deepfaune", json={"csv_path": str(csv)})
    out = Path(resp.json()["camtrap_dir"])
    med = pd.read_csv(out / "media.csv")
    assert med.iloc[0]["filePath"] == "/imgs/SITE_A/f1.jpg"
    assert med.iloc[0]["fileName"] == "f1.jpg"

def test_convert_deepfaune_creates_camtrapdp_files(client, tmp_path):
    csv = tmp_path / "results.csv"
    _write_deepfaune_csv(csv)
    resp = client.post("/api/convert/deepfaune", json={"csv_path": str(csv)})
    out = Path(resp.json()["camtrap_dir"])
    assert (out / "deployments.csv").exists()
    assert (out / "media.csv").exists()
    assert (out / "observations.csv").exists()

def test_convert_deepfaune_missing_file_400(client, tmp_path):
    resp = client.post("/api/convert/deepfaune", json={"csv_path": str(tmp_path / "nope.csv")})
    assert resp.status_code == 400

def test_convert_deepfaune_missing_columns_400(client, tmp_path):
    csv = tmp_path / "bad.csv"
    pd.DataFrame({"col_a": [1], "col_b": [2]}).to_csv(csv, index=False)
    resp = client.post("/api/convert/deepfaune", json={"csv_path": str(csv)})
    assert resp.status_code == 400

def test_convert_deepfaune_old_format_detected(client, tmp_path):
    csv = tmp_path / "old.csv"
    _write_deepfaune_csv(csv, fmt="old")
    resp = client.post("/api/convert/deepfaune", json={"csv_path": str(csv)})
    # Old format has predictionbase/scorebase and no top1 -> those are detected instead.
    assert resp.status_code == 200
    assert resp.json()["label_col"] == "predictionbase"
    assert resp.json()["score_col"] == "scorebase"

def test_convert_deepfaune_old_format_score_is_read_correctly(client, tmp_path):
    """The detected score_col (scorebase) must actually be used -- not silently
    dropped to NaN because deepfaune_to_camtrapdp() only ever looked at a
    hardcoded 'score' column."""
    csv = tmp_path / "old.csv"
    _write_deepfaune_csv(csv, fmt="old")
    resp = client.post("/api/convert/deepfaune", json={"csv_path": str(csv)})
    out = Path(resp.json()["camtrap_dir"])
    obs = pd.read_csv(out / "observations.csv")
    assert obs["classificationProbability"].iloc[0] == pytest.approx(0.88)

def test_convert_deepfaune_new_format_reports_detected_columns(client, tmp_path):
    csv = tmp_path / "results.csv"
    _write_deepfaune_csv(csv, fmt="new")
    resp = client.post("/api/convert/deepfaune", json={"csv_path": str(csv)})
    assert resp.status_code == 200
    assert resp.json()["label_col"] == "top1"
    assert resp.json()["score_col"] == "score"

def test_convert_deepfaune_predictionbase_takes_priority_over_top1(client, tmp_path):
    """predictionbase/scorebase (DeepFaune's per-image base classifier) must win
    over top1/score when both are present, matching the reference R tool."""
    csv = tmp_path / "both.csv"
    _write_deepfaune_csv(csv, fmt="both")
    resp = client.post("/api/convert/deepfaune", json={"csv_path": str(csv)})
    assert resp.status_code == 200
    assert resp.json()["label_col"] == "predictionbase"
    assert resp.json()["score_col"] == "scorebase"
    out = Path(resp.json()["camtrap_dir"])
    obs = pd.read_csv(out / "observations.csv")
    animal_row = obs[obs["observationType"] == "animal"]
    assert animal_row.iloc[0]["scientificName"] == "Vulpes vulpes"  # fox, not "red deer"
    assert animal_row.iloc[0]["classificationProbability"] == pytest.approx(0.88)

def test_convert_deepfaune_observations_have_correct_type(client, tmp_path):
    csv = tmp_path / "results.csv"
    _write_deepfaune_csv(csv)
    resp = client.post("/api/convert/deepfaune", json={"csv_path": str(csv)})
    out = Path(resp.json()["camtrap_dir"])
    obs = pd.read_csv(out / "observations.csv")
    types = set(obs["observationType"].dropna())
    assert types.issubset({"animal", "blank", "human", "unclassified"})


# ─── /api/convert/csv ──────────────────────────────────────────────────────────
# DeepFaune is really just a fixed-column-mapping case of this same converter
# -- same expectations apply: filePath unresolved, fileName written.

def _write_custom_csv(path):
    pd.DataFrame({
        "path":  ["relative/dir/f1.jpg", "relative/dir/f2.jpg"],
        "when":  ["2025-11-02 10:00:00", "2025-11-02 10:00:30"],
        "class": ["red deer", "empty"],
        "conf":  ["0.92", "0.10"],
        "loc":   ["SITE_A", "SITE_A"],
    }).to_csv(path, index=False)

def _custom_csv_body(csv_path, **overrides):
    body = {
        "csv_path": str(csv_path),
        "col_filename": "path",
        "col_datetime": "when",
        "col_label": "class",
        "col_score": "conf",
        "col_site": "loc",
        "species_map": {"red deer": "Cervus elaphus"},
    }
    body.update(overrides)
    return body

def test_convert_csv_returns_camtrap_dir(client, tmp_path):
    csv = tmp_path / "results.csv"
    _write_custom_csv(csv)
    resp = client.post("/api/convert/csv", json=_custom_csv_body(csv))
    assert resp.status_code == 200
    assert "camtrap_dir" in resp.json()

def test_convert_csv_creates_camtrapdp_files(client, tmp_path):
    csv = tmp_path / "results.csv"
    _write_custom_csv(csv)
    resp = client.post("/api/convert/csv", json=_custom_csv_body(csv))
    out = Path(resp.json()["camtrap_dir"])
    assert (out / "deployments.csv").exists()
    assert (out / "media.csv").exists()
    assert (out / "observations.csv").exists()

def test_convert_csv_missing_file_400(client, tmp_path):
    resp = client.post("/api/convert/csv", json=_custom_csv_body(tmp_path / "nope.csv"))
    assert resp.status_code == 400

def test_convert_csv_missing_columns_400(client, tmp_path):
    csv = tmp_path / "bad.csv"
    pd.DataFrame({"col_a": [1], "col_b": [2]}).to_csv(csv, index=False)
    resp = client.post("/api/convert/csv", json=_custom_csv_body(csv))
    assert resp.status_code == 400

def test_convert_csv_filepath_not_resolved(client, tmp_path):
    """filePath in the generated media.csv is the raw col_filename value --
    locating the images is resolve_media_path()'s job at review time via
    image_base_dir, not this conversion's."""
    csv = tmp_path / "results.csv"
    _write_custom_csv(csv)
    resp = client.post("/api/convert/csv", json=_custom_csv_body(csv))
    out = Path(resp.json()["camtrap_dir"])
    med = pd.read_csv(out / "media.csv")
    assert med.iloc[0]["filePath"] == "relative/dir/f1.jpg"
    assert med.iloc[0]["fileName"] == "f1.jpg"

def test_convert_csv_maps_species_via_species_map(client, tmp_path):
    csv = tmp_path / "results.csv"
    _write_custom_csv(csv)
    resp = client.post("/api/convert/csv", json=_custom_csv_body(csv))
    out = Path(resp.json()["camtrap_dir"])
    obs = pd.read_csv(out / "observations.csv")
    animal_row = obs[obs["observationType"] == "animal"]
    assert animal_row.iloc[0]["scientificName"] == "Cervus elaphus"


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

def test_setup_min_score_filters_low_confidence_events(client, camtrap_dir, tmp_path):
    """min_score from the setup wizard must actually reach build_candidates and
    drop events whose best frame doesn't meet the threshold (SITE_A occ2's only
    burst tops out at 0.7)."""
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
        "min_score":        0.75,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["n_combos"] == 2
    session_dir = Path(data["session_dir"])
    manifest = pd.read_csv(session_dir / "candidate_manifest.csv")
    assert "m003" not in set(manifest["mediaID"])
    assert "m005" not in set(manifest["mediaID"])

def test_setup_clears_stale_flat_search_cache_on_new_session(client, camtrap_dir, tmp_path):
    """A second /api/setup reusing the same image_base_dir must not keep resolving
    files to a stale flat-search index built by a previous session. The
    in-process lru_cache never invalidates on its own, so if a photo is moved
    to a new subfolder under the same image_base_dir between sessions (without
    restarting the backend), a stale index would still point at the old,
    now-missing location and wrongly 404 it -- even though the file exists at
    its new location and a fresh scan would find it there."""
    imgs = tmp_path / "images"
    loose = imgs / "loose"
    loose.mkdir(parents=True)
    for i in range(5):
        (loose / f"frame{i}.jpg").write_bytes(b"\xff\xd8\xff\xe0")

    out = tmp_path / "out"
    setup_body = {
        "camtrap_dir":      str(camtrap_dir),
        "output_dir":       str(out),
        "target_species":   ["Vulpes vulpes"],
        "study_start":      "2025-11-01",
        "study_end":        "2025-11-10",
        "occasion_days":    5,
        "total_iterations": 100_000,
        "gap_seconds":      60,
        "min_score":        0.5,
        "image_base_dir":   str(imgs),
        "flat_search":      True,
    }
    resp = client.post("/api/setup", json=setup_body)
    assert resp.status_code == 200
    resp = client.get("/api/image/m001")
    assert resp.status_code == 200

    # Simulate moving the photo to a new subfolder of the same image_base_dir
    # between sessions (no backend restart in between).
    moved = imgs / "moved"
    moved.mkdir()
    (loose / "frame0.jpg").rename(moved / "frame0.jpg")

    resp = client.post("/api/setup", json=setup_body)
    assert resp.status_code == 200
    resp = client.get("/api/image/m001")
    assert resp.status_code == 200

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
    assert resp.json() == {"confirmed": [], "unsure": [], "corrections": {}}

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

def test_get_results_flags_generated_datapackage(client, setup_session):
    """The camtrap_dir fixture ships no datapackage.json, so a default is generated."""
    data = client.get("/api/results").json()
    assert data["datapackage_generated"] is True
    assert "spatial" in data["datapackage_fabricated_fields"]

def test_get_results_no_warning_when_source_has_datapackage(client, camtrap_dir, tmp_path):
    (camtrap_dir / "datapackage.json").write_text('{"name": "test"}')
    resp = client.post("/api/setup", json={
        "camtrap_dir":      str(camtrap_dir),
        "output_dir":       str(tmp_path / "out"),
        "target_species":   ["Vulpes vulpes"],
        "study_start":      "2025-11-01",
        "study_end":        "2025-11-10",
        "occasion_days":    5,
        "total_iterations": 100_000,
        "gap_seconds":      60,
        "min_score":        0.5,
    })
    assert resp.status_code == 200
    data = client.get("/api/results").json()
    assert data["datapackage_generated"] is False
    assert data["datapackage_fabricated_fields"] == []
    sp = data["by_species"][0]
    assert sp["species"] == "Vulpes vulpes"
    assert "confirmed" in sp and "rejected" in sp and "unverified" in sp


# ─── /api/version ─────────────────────────────────────────────────────────────

def test_version_dev_skips_github(client):
    with patch("api.routers.health._current_version", return_value="dev"):
        resp = client.get("/api/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == "dev"
    assert data["update_available"] is False
    assert data["latest"] is None

def test_version_update_available(client):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "tag_name": "v9.9.9",
        "html_url": "https://github.com/example/releases/tag/v9.9.9",
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("api.routers.health._current_version", return_value="0.1.0"), \
         patch("api.routers.health.httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == "0.1.0"
    assert data["latest"] == "9.9.9"
    assert data["update_available"] is True

def test_version_no_update(client):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "tag_name": "v0.1.0",
        "html_url": "https://github.com/example/releases/tag/v0.1.0",
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("api.routers.health._current_version", return_value="0.1.0"), \
         patch("api.routers.health.httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    assert resp.json()["update_available"] is False

def test_version_github_unreachable(client):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("network error"))

    with patch("api.routers.health._current_version", return_value="0.1.0"), \
         patch("api.routers.health.httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    data = resp.json()
    assert data["update_available"] is False
    assert data["latest"] is None


# ─── /api/session/load ────────────────────────────────────────────────────────

def test_load_session_valid(client, setup_session):
    session_dir = setup_session["session_dir"]
    resp = client.post("/api/session/load", json={"session_dir": session_dir})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["session_dir"] == session_dir
    assert data["config"] is not None

def test_load_session_nonexistent_dir(client):
    resp = client.post("/api/session/load", json={"session_dir": "/nonexistent/path"})
    assert resp.status_code == 400

def test_load_session_invalid_dir(client, tmp_path):
    resp = client.post("/api/session/load", json={"session_dir": str(tmp_path)})
    assert resp.status_code == 400


# ─── /api/session/recent ───────────────────────────────────────────────────────

def test_recent_sessions_empty_initially(client):
    resp = client.get("/api/session/recent")
    assert resp.status_code == 200
    assert resp.json() == []

def test_recent_sessions_includes_new_session(client, setup_session):
    resp = client.get("/api/session/recent")
    entries = resp.json()
    assert len(entries) == 1
    assert entries[0]["session_dir"] == setup_session["session_dir"]
    assert entries[0]["target_species"] == ["Vulpes vulpes"]

def test_recent_sessions_most_recent_first(client, camtrap_dir, tmp_path):
    def do_setup(out_subdir: str) -> str:
        resp = client.post("/api/setup", json={
            "camtrap_dir":      str(camtrap_dir),
            "output_dir":       str(tmp_path / out_subdir),
            "target_species":   ["Vulpes vulpes"],
            "study_start":      "2025-11-01",
            "study_end":        "2025-11-10",
            "occasion_days":    5,
            "total_iterations": 100_000,
            "gap_seconds":      60,
            "min_score":        0.5,
        })
        assert resp.status_code == 200
        return resp.json()["session_dir"]

    first = do_setup("out1")
    second = do_setup("out2")

    entries = client.get("/api/session/recent").json()
    assert [e["session_dir"] for e in entries] == [second, first]

def test_recent_sessions_reload_moves_to_front_without_duplicating(client, setup_session):
    client.post("/api/session/load", json={"session_dir": setup_session["session_dir"]})
    entries = client.get("/api/session/recent").json()
    assert len(entries) == 1
    assert entries[0]["session_dir"] == setup_session["session_dir"]

def test_recent_sessions_prunes_deleted_sessions(client, setup_session):
    (Path(setup_session["session_dir"]) / "config.json").unlink()
    entries = client.get("/api/session/recent").json()
    assert entries == []


# ─── /api/results/download ────────────────────────────────────────────────────

def test_download_no_session(client):
    resp = client.get("/api/results/download")
    assert resp.status_code == 400

def test_download_returns_zip(client, setup_session):
    resp = client.get("/api/results/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

def test_download_content_disposition_has_prefix(client, setup_session):
    resp = client.get("/api/results/download")
    cd = resp.headers.get("content-disposition", "")
    assert "wildintel-camtrap-verify-" in cd

def test_download_zip_contains_config(client, setup_session):
    resp = client.get("/api/results/download")
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert any(n == "config.json" or n.endswith("/config.json") for n in names)

def test_download_zip_contains_candidates(client, setup_session):
    resp = client.get("/api/results/download")
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert any("candidate_manifest.csv" in n for n in names)

def test_download_cleans_up_temp_file(client, setup_session):
    """The zip is staged on disk (not in memory) and removed after the response is sent."""
    import tempfile
    before = set(Path(tempfile.gettempdir()).glob("*.zip"))
    resp = client.get("/api/results/download")
    assert resp.status_code == 200
    after = set(Path(tempfile.gettempdir()).glob("*.zip"))
    assert after == before


# ─── /api/open-folder ─────────────────────────────────────────────────────────

def test_open_folder_no_session(client):
    resp = client.post("/api/open-folder")
    assert resp.status_code == 400

def test_open_folder_uses_platform_command(client, setup_session):
    import api.routers.results as results_router
    with patch.object(results_router.sys, "platform", "darwin"), \
         patch.object(results_router.subprocess, "Popen") as mock_popen:
        resp = client.post("/api/open-folder")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    args, _ = mock_popen.call_args
    assert args[0][0] == "open"

def test_open_folder_missing_binary_returns_ok_false(client, setup_session):
    import api.routers.results as results_router
    with patch.object(results_router.subprocess, "Popen", side_effect=FileNotFoundError):
        resp = client.post("/api/open-folder")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


# ─── /api/setup with flat_search ambiguity ───────────────────────────────────

def test_setup_blocked_on_ambiguous_flat_search(client, camtrap_dir, tmp_path):
    """Setup must abort (not silently proceed) when flat_search finds an
    ambiguous match, mirroring R's resolve_media_files() abort condition."""
    img_root = tmp_path / "images"
    (img_root / "OTHER1").mkdir(parents=True)
    (img_root / "OTHER2").mkdir(parents=True)
    (img_root / "OTHER1" / "frame0.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    (img_root / "OTHER2" / "frame0.jpg").write_bytes(b"\xff\xd8\xff\xe0")

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
        "image_base_dir":   str(img_root),
        "flat_search":      True,
    })
    assert resp.status_code == 400
    assert "frame0.jpg" in resp.json()["detail"]
    # no session must have been created
    assert client.get("/api/state").json()["ready"] is False


# ─── /api/image (image_base_dir) ─────────────────────────────────────────────

@pytest.fixture
def setup_session_with_image_base_dir(client, camtrap_dir, tmp_path):
    """Setup session where media.csv uses relative paths and image_base_dir is set."""
    imgs = tmp_path / "images"
    img_sub = imgs / "img"
    img_sub.mkdir(parents=True)
    # Write a tiny placeholder image matching the fixture's relative filePath (img/frameN.jpg)
    for i in range(5):
        (img_sub / f"frame{i}.jpg").write_bytes(b"\xff\xd8\xff\xe0")  # JPEG magic bytes

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
        "image_base_dir":   str(imgs),
    })
    assert resp.status_code == 200
    return imgs

def test_setup_stores_image_base_dir_in_config(client, setup_session_with_image_base_dir):
    state = client.get("/api/state").json()
    assert state["config"]["image_base_dir"] != ""

def test_serve_image_uses_image_base_dir(client, setup_session_with_image_base_dir):
    """When image_base_dir is set, serve_image resolves the relative filePath against it."""
    resp = client.get("/api/image/m001")
    assert resp.status_code == 200

def test_serve_image_fallback_to_camtrap_dir_itself(client, setup_session, camtrap_dir):
    """When image_base_dir is empty, relative paths resolve against camtrap_dir itself."""
    imgs = camtrap_dir / "img"
    imgs.mkdir(exist_ok=True)
    (imgs / "frame0.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    resp = client.get("/api/image/m001")
    assert resp.status_code == 200

def test_serve_image_unknown_media_id_returns_404(client, setup_session):
    """Unknown mediaID returns 404."""
    resp = client.get("/api/image/nonexistent_id")
    assert resp.status_code == 404

def test_serve_image_sets_no_store_cache_control(client, setup_session_with_image_base_dir):
    """Images must never be cached by the browser: the same mediaID URL is reused
    across sessions, so a stale browser cache could keep showing a file that has
    since been moved or deleted even though the backend would now 404 it."""
    resp = client.get("/api/image/m001")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"

def test_serve_image_permission_denied_returns_403(client, setup_session_with_image_base_dir, monkeypatch):
    """A PermissionError reading the resolved file returns 403, not a generic 500 or 404."""
    real_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        if self.name == "frame0.jpg":
            raise PermissionError("denied")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)
    resp = client.get("/api/image/m001")
    assert resp.status_code == 403

def test_serve_image_structured_precedence_over_wrong_absolute_filepath(client, camtrap_dir, tmp_path):
    """image_base_dir/deploymentID/fileName must win even when filePath is an
    absolute path that does not exist on disk."""
    med = pd.read_csv(camtrap_dir / "media.csv", dtype=str)
    med.loc[med["mediaID"] == "m001", "filePath"] = "/nonexistent/somewhere/frame0.jpg"
    med.to_csv(camtrap_dir / "media.csv", index=False)

    img_root = tmp_path / "images"
    (img_root / "DEP1").mkdir(parents=True)
    (img_root / "DEP1" / "frame0.jpg").write_bytes(b"\xff\xd8\xff\xe0")

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
        "image_base_dir":   str(img_root),
    })
    assert resp.status_code == 200

    resp = client.get("/api/image/m001")
    assert resp.status_code == 200


# ─── effort report ↔ results consistency ──────────────────────────────────────

def _effort_csv(setup_session):
    import pandas as pd
    from pathlib import Path
    return pd.read_csv(Path(setup_session["session_dir"]) / "occupancy_inputs" / "effort_report.csv")

def test_effort_report_total_matches_results_on_partial_session(client, setup_session):
    events = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    client.post("/api/decisions", json={
        "species": "Vulpes_vulpes", "iteration": 1, "confirmed": [events[0]["repObsId"]],
    })
    csv_total = _effort_csv(setup_session).iloc[-1]       # written on save, before Results
    data = client.get("/api/results").json()
    tot = next(r for r in data["effort_by_species"] if r["species"] == "TOTAL")
    assert csv_total["cells_detection"] == tot["cells_detection"] == data["confirmed"]
    assert csv_total["cells_non_detection"] == tot["cells_non_detection"] == data["rejected"]
    assert csv_total["cells_unverified"] == tot["cells_unverified"] == data["unverified"]

def test_effort_report_total_matches_results_when_finished(client, setup_session):
    client.post("/api/decisions", json={
        "species": "Vulpes_vulpes", "iteration": 1, "confirmed": [],
    })
    client.post("/api/decisions", json={
        "species": "Vulpes_vulpes", "iteration": 2, "confirmed": [],
    })
    data = client.get("/api/results").json()
    tot = next(r for r in data["effort_by_species"] if r["species"] == "TOTAL")
    assert tot["cells_detection"] == data["confirmed"]
    assert tot["cells_non_detection"] == data["rejected"]
    assert tot["cells_unverified"] == data["unverified"]


# ─── min_score exclusions ─────────────────────────────────────────────────────

def _setup_with_min_score(client, camtrap_dir, tmp_path, min_score):
    resp = client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"),
        "target_species": ["Vulpes vulpes"], "study_start": "2025-11-01",
        "study_end": "2025-11-10", "occasion_days": 5, "total_iterations": 100_000,
        "gap_seconds": 60, "min_score": min_score,
    })
    assert resp.status_code == 200
    return resp.json()

def test_results_report_exclusions_with_active_cutoff(client, camtrap_dir, tmp_path):
    _setup_with_min_score(client, camtrap_dir, tmp_path, 0.75)
    data = client.get("/api/results").json()
    assert data["min_score"] == 0.75
    tot = next(r for r in data["effort_by_species"] if r["species"] == "TOTAL")
    assert tot["excluded_photos"] == 2 and tot["excluded_cells"] == 1

def test_results_exclusions_zero_without_cutoff(client, camtrap_dir, tmp_path):
    _setup_with_min_score(client, camtrap_dir, tmp_path, 0.0)
    data = client.get("/api/results").json()
    assert data["min_score"] == 0
    tot = next(r for r in data["effort_by_species"] if r["species"] == "TOTAL")
    assert (tot["excluded_photos"], tot["excluded_events"], tot["excluded_cells"]) == (0, 0, 0)


# ─── unsure decisions ──────────────────────────────────────────────────────

def test_post_decisions_without_unsure_still_works(client, setup_session):
    """Older clients (and existing sessions) never send the field."""
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    r = client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1,
                                            "confirmed": [ev[0]["repObsId"]]})
    assert r.status_code == 200
    got = client.get("/api/decisions", params={"species": "Vulpes_vulpes", "iteration": 1}).json()
    assert got["unsure"] == []

def test_unsure_roundtrip_counts_as_rejection_and_is_reported(client, setup_session):
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    unc, conf = [e["repObsId"] for e in ev[1:]], [ev[0]["repObsId"]]
    r = client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1,
                                            "confirmed": conf, "unsure": unc + conf})
    assert r.status_code == 200
    got = client.get("/api/decisions", params={"species": "Vulpes_vulpes", "iteration": 1}).json()
    assert got["confirmed"] == conf and sorted(got["unsure"]) == sorted(unc)  # confirm wins
    data = client.get("/api/results").json()
    tot = next(x for x in data["effort_by_species"] if x["species"] == "TOTAL")
    assert tot["unsure_events"] == len(unc)
    assert data["confirmed"] == 1                                               # unsure != confirmed


# ─── rejection corrections ("actual species") ─────────────────────────────────

def _setup_corr(client, camtrap_dir, tmp_path, on):
    r = client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"),
        "target_species": ["Vulpes vulpes"], "study_start": "2025-11-01", "study_end": "2025-11-10",
        "occasion_days": 5, "total_iterations": 100_000, "gap_seconds": 60, "min_score": 0.5,
        "record_rejection_species": on})
    assert r.status_code == 200
    return r.json()

def test_corrections_ignored_when_option_off(client, camtrap_dir, tmp_path):
    info = _setup_corr(client, camtrap_dir, tmp_path, False)
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [],
                                        "corrections": {ev[0]["repObsId"]: "Dama dama"}})
    from pathlib import Path
    assert not (Path(info["session_dir"]) / "rejection_corrections.csv").exists()
    data = client.get("/api/results").json()
    assert data["record_rejection_species"] is False and data["false_positive_sources"] == []

def test_corrections_roundtrip_and_false_positive_table(client, camtrap_dir, tmp_path):
    _setup_corr(client, camtrap_dir, tmp_path, True)
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    conf, rest = ev[0]["repObsId"], [e["repObsId"] for e in ev[1:]]
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [conf],
                                        "corrections": {rest[0]: "Dama dama", conf: "Homo sapiens"}})
    got = client.get("/api/decisions", params={"species": "Vulpes_vulpes", "iteration": 1}).json()
    assert got["corrections"] == {rest[0]: "Dama dama"}                 # the confirmed one is dropped
    data = client.get("/api/results").json()
    assert data["record_rejection_species"] is True
    row = next(r for r in data["false_positive_sources"] if r["actual_species"] == "Dama dama")
    assert row["species"] == "Vulpes vulpes" and row["rejected_events"] == 1

def test_taxa_endpoint_lists_dataset_species_and_extras(client, setup_session):
    data = client.get("/api/taxa").json()
    assert "Vulpes vulpes" in data["taxa"]
    assert "Homo sapiens" in data["extra"] and "No animal / empty" in data["extra"]


# ─── review time ──────────────────────────────────────────────────────────────

def test_decision_times_give_active_review_time_in_results(client, setup_session):
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    ids = [e["repObsId"] for e in ev]
    t0 = 1_767_261_600_000
    times = {oid: t0 + 40_000 * i for i, oid in enumerate(ids)}                    # 40 s apart
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1,
                                        "confirmed": [ids[0]], "decision_times": times})
    data = client.get("/api/results").json()
    tot = next(r for r in data["effort_by_species"] if r["species"] == "TOTAL")
    assert tot["review_active_seconds"] == 40 * (len(ids) - 1)
    assert tot["review_decisions_timed"] == len(ids) and data["review_idle_seconds"] == 120

def test_results_review_time_is_none_without_timestamps(client, setup_session):
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1,
                                        "confirmed": [ev[0]["repObsId"]]})       # older client: no times
    tot = next(r for r in client.get("/api/results").json()["effort_by_species"] if r["species"] == "TOTAL")
    assert tot["review_active_seconds"] is None and tot["review_est_saved_seconds"] is None

def test_idle_threshold_comes_from_setup(client, camtrap_dir, tmp_path):
    client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"),
        "target_species": ["Vulpes vulpes"], "study_start": "2025-11-01", "study_end": "2025-11-10",
        "occasion_days": 5, "total_iterations": 100_000, "gap_seconds": 60, "min_score": 0.5,
        "review_idle_seconds": 30})
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    ids = [e["repObsId"] for e in ev]
    t0 = 1_767_261_600_000
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [],
                                        "decision_times": {oid: t0 + 40_000 * i for i, oid in enumerate(ids)}})
    data = client.get("/api/results").json()
    tot = next(r for r in data["effort_by_species"] if r["species"] == "TOTAL")
    assert data["review_idle_seconds"] == 30 and tot["review_active_seconds"] == 0   # every 40 s gap is idle


# ─── random seed ──────────────────────────────────────────────────────────────

def test_random_seed_is_stored_in_the_session_config(client, camtrap_dir, tmp_path):
    for seed in (42, 7):
        r = client.post("/api/setup", json={
            "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / f"o{seed}"),
            "target_species": ["Vulpes vulpes"], "study_start": "2025-11-01", "study_end": "2025-11-10",
            "occasion_days": 5, "total_iterations": 100_000, "gap_seconds": 60, "min_score": 0.5,
            "random_seed": seed})
        assert r.status_code == 200
        assert client.get("/api/state").json()["config"]["random_seed"] == seed


# ─── bounding boxes on served images ──────────────────────────────────────────

@pytest.fixture
def boxed_session(client, camtrap_dir, tmp_path):
    """The minimal dataset with real image files and a box on o001 only."""
    from PIL import Image
    (camtrap_dir / "img").mkdir(exist_ok=True)
    media = pd.read_csv(camtrap_dir / "media.csv")
    for fp in media["filePath"]:
        Image.new("RGB", (160, 100), (80, 80, 80)).save(camtrap_dir / fp, quality=95)
    obs = pd.read_csv(camtrap_dir / "observations.csv")
    for c in ("bboxX", "bboxY", "bboxWidth", "bboxHeight"):
        obs[c] = None
    obs.loc[obs["observationID"] == "o001", ["bboxX", "bboxY", "bboxWidth", "bboxHeight"]] = [0.2, 0.2, 0.5, 0.5]
    obs.to_csv(camtrap_dir / "observations.csv", index=False)
    r = client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"), "target_species": ["Vulpes vulpes"],
        "study_start": "2025-11-01", "study_end": "2025-11-10", "occasion_days": 5,
        "total_iterations": 100_000, "gap_seconds": 60, "min_score": 0.5})
    assert r.status_code == 200
    return camtrap_dir


def _pixels(resp):
    from PIL import Image
    import io
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def test_image_is_served_untouched_by_default(client, boxed_session):
    plain = client.get("/api/image/m001")
    assert plain.status_code == 200 and plain.content == (boxed_session / "img" / "frame0.jpg").read_bytes()
    assert plain.content == client.get("/api/image/m001", params={"boxes": "false", "obs": "o001"}).content


def test_boxes_are_drawn_for_the_requested_observation(client, boxed_session):
    plain = _pixels(client.get("/api/image/m001"))
    boxed = client.get("/api/image/m001", params={"boxes": "true", "obs": "o001"})
    assert boxed.status_code == 200 and boxed.headers["content-type"] == "image/jpeg"
    img = _pixels(boxed)
    assert img.size == plain.size == (160, 100)
    x0, y0 = round(0.2 * 160), round(0.2 * 100)
    r, g, b = img.getpixel((x0, y0 + 20))
    assert r > 200 and b < 80 and (r, g, b) != plain.getpixel((x0, y0 + 20))      # the amber edge
    assert img.getpixel((5, 90)) == pytest.approx(plain.getpixel((5, 90)), abs=6)   # elsewhere unchanged (JPEG noise)


def test_observation_without_a_box_gets_the_original_file(client, boxed_session):
    orig = (boxed_session / "img" / "frame3.jpg").read_bytes()
    assert client.get("/api/image/m004", params={"boxes": "true", "obs": "o004"}).content == orig
    assert client.get("/api/image/m001", params={"boxes": "true", "obs": "does-not-exist"}).content \
        == (boxed_session / "img" / "frame0.jpg").read_bytes()
    assert client.get("/api/image/m001", params={"boxes": "true"}).content \
        == (boxed_session / "img" / "frame0.jpg").read_bytes()                  # no obs given


def test_event_frames_report_how_many_boxes_they_have(client, boxed_session):
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    boxes = {f["obsId"]: f["boxes"] for e in ev for f in e["frames"]}
    assert boxes["o001"] == 1 and all(v == 0 for k, v in boxes.items() if k != "o001")


# ─── occasions shorter than a day ─────────────────────────────────────────────

def _hourly_setup(client, camtrap_dir, tmp_path, hours):
    return client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"), "target_species": ["Vulpes vulpes"],
        "study_start": "2025-11-02", "study_end": "2025-11-03", "occasion_days": 1, "occasion_hours": hours,
        "total_iterations": 100_000, "gap_seconds": 60, "min_score": 0.0})


def test_one_hour_session_also_fits_the_occupancy_model_but_reports_the_hours(client, camtrap_dir, tmp_path):
    r = _hourly_setup(client, camtrap_dir, tmp_path, 1)
    assert r.status_code == 200
    from pathlib import Path
    occ = Path(r.json()["session_dir"]) / "occupancy_inputs"
    assert (occ / "dethist_naive_Vulpes_vulpes.csv").exists()                       # histories are written
    assert (occ / "occupancy_fit.csv").exists()                                     # and the model is fitted, as in the fork
    assert client.get("/api/results/occupancy").status_code == 200
    assert client.get("/api/results").json()["occasion_hours"] == 1                 # so the page can caution about it


def test_day_session_still_fits_the_model_and_reports_no_hours(client, setup_session):
    data = client.get("/api/results").json()
    assert data["occasion_hours"] == 0


def test_negative_occasion_hours_is_rejected(client, camtrap_dir, tmp_path):
    assert _hourly_setup(client, camtrap_dir, tmp_path, -1).status_code == 422


# ─── completed species: confirmed event, rounds kept when editing ─────────────
# Fixture: A/occ1 has two events (rank 1 = o001/o002, rank 2 = o005); A/occ2 and B/occ1 have one.

@pytest.fixture
def finished_in_two_rounds(client, setup_session):
    """Round 1 confirms A/occ2 and B/occ1 and rejects A/occ1; round 2 confirms A/occ1's second event (o005)."""
    ev1 = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    keep = [e["repObsId"] for e in ev1 if e["key"] != "SITE_A_occ1_Vulpes_vulpes"]
    r1 = client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": keep}).json()
    assert r1["done"] is False and r1["next_iteration"] == 2
    ev2 = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 2}).json()
    assert [e["repObsId"] for e in ev2] == ["o005"]
    r2 = client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": ["o005"]}).json()
    assert r2["done"] is True
    return client


def _species_stats(client):
    return next(s for s in client.get("/api/species").json() if s["species_safe"] == "Vulpes_vulpes")


def test_review_shows_the_event_that_was_confirmed_not_the_rank_1_event(finished_in_two_rounds):
    review = {e["key"]: e for e in finished_in_two_rounds.get("/api/species/Vulpes_vulpes/review").json()}
    a1 = review["SITE_A_occ1_Vulpes_vulpes"]
    assert a1["status"] == "confirmed" and a1["rank"] == 2 and a1["repObsId"] == "o005"
    assert [f["obsId"] for f in a1["frames"]] == ["o005"]                       # not the rank-1 frames o001/o002
    assert review["SITE_A_occ2_Vulpes_vulpes"]["rank"] == 1                     # confirmed in round 1: unchanged


def test_unconfirmed_cells_still_show_their_rank_1_event_in_the_review(finished_in_two_rounds):
    client = finished_in_two_rounds
    client.put("/api/species/Vulpes_vulpes/decisions", json={"confirmed_keys": ["SITE_A_occ2_Vulpes_vulpes"]})
    a1 = next(e for e in client.get("/api/species/Vulpes_vulpes/review").json() if e["key"] == "SITE_A_occ1_Vulpes_vulpes")
    assert a1["status"] == "not_confirmed" and a1["rank"] == 1 and a1["repObsId"] == "o001"


def test_update_decisions_keeps_the_confirmed_event(finished_in_two_rounds):
    client = finished_in_two_rounds
    keys = [e["key"] for e in client.get("/api/species/Vulpes_vulpes/review").json()]
    client.put("/api/species/Vulpes_vulpes/decisions", json={"confirmed_keys": keys})          # confirm all again
    got = client.get("/api/decisions", params={"species": "Vulpes_vulpes", "iteration": 1}).json()["confirmed"]
    assert "o005" in got and "o001" not in got                                  # the event confirmed in round 2 survives
    a1 = next(e for e in client.get("/api/species/Vulpes_vulpes/review").json() if e["key"] == "SITE_A_occ1_Vulpes_vulpes")
    assert a1["rank"] == 2 and a1["repObsId"] == "o005"


def test_update_decisions_keeps_the_number_of_rounds_done(finished_in_two_rounds):
    client = finished_in_two_rounds
    before = _species_stats(client)
    assert before["current_iteration"] == 3 and before["n_resolved"] == before["n_total_combos"]
    # Leave A/occ1 (two events) unconfirmed: it must stay settled as "not detected", not re-open
    client.put("/api/species/Vulpes_vulpes/decisions",
               json={"confirmed_keys": ["SITE_A_occ2_Vulpes_vulpes", "SITE_B_occ1_Vulpes_vulpes"]})
    after = _species_stats(client)
    assert after["current_iteration"] == 3                                      # rounds done unchanged
    assert after["n_resolved"] == after["n_total_combos"]                        # nothing re-opened for review
    assert after["n_confirmed_combos"] == 2


def test_update_decisions_with_nothing_confirmed_keeps_the_rounds(finished_in_two_rounds):
    client = finished_in_two_rounds
    client.put("/api/species/Vulpes_vulpes/decisions", json={"confirmed_keys": []})
    stats = _species_stats(client)
    assert stats["current_iteration"] == 3 and stats["n_resolved"] == stats["n_total_combos"]
    assert client.get("/api/results").json()["unverified"] == 0


def test_effort_report_uses_the_real_rank_of_the_confirmed_event_after_an_edit(finished_in_two_rounds):
    client = finished_in_two_rounds
    keys = [e["key"] for e in client.get("/api/species/Vulpes_vulpes/review").json()]
    client.put("/api/species/Vulpes_vulpes/decisions", json={"confirmed_keys": keys})
    tot = next(r for r in client.get("/api/results").json()["effort_by_species"] if r["species"] == "TOTAL")
    assert tot["cells_detection"] == 3 and tot["events_inspected"] == 4          # A/occ1 needed 2 events, the others 1


# ─── Trapper-style export: web addresses in filePath, photos in deployment folders ───

@pytest.fixture
def trapper_style(client, camtrap_dir, tmp_path):
    """filePath is a URL with no file name, fileName says .JPEG and the photos are images/<group>/<deployment>/*.jpg."""
    from PIL import Image
    media = pd.read_csv(camtrap_dir / "media.csv")
    media["fileName"] = [f"frame{i}.JPEG" for i in range(len(media))]
    media["filePath"] = [f"https://trap.example/storage/resource/media/{i}/file/" for i in range(len(media))]
    media.to_csv(camtrap_dir / "media.csv", index=False)
    images = tmp_path / "images"
    for _, r in media.iterrows():
        d = images / "group1" / r["deploymentID"]
        d.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 40), (70, 70, 70)).save(d / r["fileName"].replace(".JPEG", ".jpg"))
    return camtrap_dir, images


def test_check_images_counts_trapper_style_photos_as_found(client, trapper_style):
    data, images = trapper_style
    without = client.get("/api/fs/check-images", params={"camtrap_dir": str(data)}).json()
    with_dir = client.get("/api/fs/check-images", params={"camtrap_dir": str(data), "image_base_dir": str(images)}).json()
    assert without["total"] == 0                                    # remote paths are skipped without an images folder
    assert with_dir["total"] == 5 and with_dir["missing"] == 0


def test_gallery_and_image_route_serve_trapper_style_photos_locally(client, trapper_style, tmp_path):
    data, images = trapper_style
    r = client.post("/api/setup", json={
        "camtrap_dir": str(data), "image_base_dir": str(images), "output_dir": str(tmp_path / "out"),
        "target_species": ["Vulpes vulpes"], "study_start": "2025-11-01", "study_end": "2025-11-10",
        "occasion_days": 5, "total_iterations": 100_000, "gap_seconds": 60, "min_score": 0.5})
    assert r.status_code == 200
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    imgs = {f["img"] for e in ev for f in e["frames"]}
    assert imgs and all(u.startswith("/api/image/") for u in imgs)          # none through the network proxy
    first = next(iter(imgs))
    resp = client.get(first)
    assert resp.status_code == 200 and resp.content[:3] == b"\xff\xd8\xff"   # a real JPEG from the deployment folder


def test_images_folder_one_level_too_deep_is_checked_through_the_data_folder(client, camtrap_dir):
    from PIL import Image
    media = pd.read_csv(camtrap_dir / "media.csv")                  # filePath: img/frame0.jpg ...
    (camtrap_dir / "img").mkdir(exist_ok=True)
    for fp in media["filePath"]:
        Image.new("RGB", (8, 8)).save(camtrap_dir / fp)
    too_deep = camtrap_dir / "img"                                  # the user picked img/ as the Images directory
    res = client.get("/api/fs/check-images", params={"camtrap_dir": str(camtrap_dir), "image_base_dir": str(too_deep)}).json()
    assert res["total"] == 5 and res["missing"] == 0


# ─── minimum score per species ────────────────────────────────────────────────
# Fixture scores for Vulpes vulpes: m001=0.9 m002=0.8 m005=0.6 m003=0.7 m004=0.85

def _setup_cutoffs(client, camtrap_dir, tmp_path, general, by_species):
    r = client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"), "target_species": ["Vulpes vulpes"],
        "study_start": "2025-11-01", "study_end": "2025-11-10", "occasion_days": 5, "total_iterations": 100_000,
        "gap_seconds": 60, "min_score": general, "min_score_by_species": by_species})
    assert r.status_code == 200
    return r.json()


def test_species_cutoff_replaces_the_general_one_in_the_report(client, camtrap_dir, tmp_path):
    _setup_cutoffs(client, camtrap_dir, tmp_path, 0.5, {"Vulpes vulpes": 0.7})
    data = client.get("/api/results").json()
    assert data["min_score"] == 0.5 and data["min_score_by_species"] == {"Vulpes vulpes": 0.7}
    row = next(r for r in data["effort_by_species"] if r["species"] == "Vulpes vulpes")
    assert row["min_score"] == 0.7
    assert row["excluded_photos"] == 1                   # m005 (0.6) is below 0.7; m003 (0.7) equals it and is kept


def test_general_only_sessions_report_no_species_cutoffs(client, setup_session):
    data = client.get("/api/results").json()
    assert data["min_score_by_species"] == {}
    row = next(r for r in data["effort_by_species"] if r["species"] == "Vulpes vulpes")
    assert row["min_score"] == 0.5 and row["excluded_photos"] == 0


def test_species_cutoff_is_stored_in_the_session_config(client, camtrap_dir, tmp_path):
    info = _setup_cutoffs(client, camtrap_dir, tmp_path, 0.5, {"Vulpes vulpes": 0.8})
    import json
    from pathlib import Path
    cfg = json.loads((Path(info["session_dir"]) / "config.json").read_text())
    assert cfg["min_score_by_species"] == {"Vulpes vulpes": 0.8}
    assert info["n_candidates"] == 3                      # 0.9, 0.8 (kept: equal) and 0.85; 0.7 and 0.6 are below 0.8


def test_a_cutoff_that_leaves_nothing_to_review_is_a_clear_error_not_a_crash(client, camtrap_dir, tmp_path):
    r = client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"), "target_species": ["Vulpes vulpes"],
        "study_start": "2025-11-01", "study_end": "2025-11-10", "occasion_days": 5, "total_iterations": 100_000,
        "gap_seconds": 60, "min_score": 0.5, "min_score_by_species": {"Vulpes vulpes": 0.95}})
    assert r.status_code == 400 and "puntuación mínima" in r.json()["detail"]


def test_one_species_losing_all_its_photos_does_not_break_the_session(client, camtrap_dir, tmp_path):
    """Two target species; the cut-off of one removes everything of it, the other still has candidates."""
    import pandas as pd
    obs = pd.read_csv(camtrap_dir / "observations.csv")
    extra = obs.iloc[:2].copy()
    extra["observationID"] = ["z1", "z2"]
    extra["scientificName"] = "Sus scrofa"
    extra["classificationProbability"] = [0.55, 0.6]
    pd.concat([obs, extra]).to_csv(camtrap_dir / "observations.csv", index=False)
    r = client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"),
        "target_species": ["Vulpes vulpes", "Sus scrofa"], "study_start": "2025-11-01", "study_end": "2025-11-10",
        "occasion_days": 5, "total_iterations": 100_000, "gap_seconds": 60, "min_score": 0.5,
        "min_score_by_species": {"Sus scrofa": 0.9}})
    assert r.status_code == 200
    data = client.get("/api/results").json()
    assert data["min_score_by_species"] == {"Sus scrofa": 0.9}
    rows = {x["species"]: x for x in data["effort_by_species"]}
    sus = rows["Sus scrofa"]                               # still reported, not silently dropped
    assert sus["candidate_events"] == 0 and sus["excluded_photos"] == 2 and sus["min_score"] == 0.9
    assert rows["Vulpes vulpes"]["candidate_events"] == 4 and rows["TOTAL"]["excluded_photos"] == 2
    assert [x["species"] for x in data["effort_by_species"]] == ["Sus scrofa", "Vulpes vulpes", "TOTAL"]   # alphabetical, TOTAL last
    assert [s["species_safe"] for s in client.get("/api/species").json()] == ["Vulpes_vulpes"]   # nothing of Sus to review
    assert client.get("/api/results/occupancy").status_code == 200


def test_sessions_saved_before_the_option_existed_still_report(client, setup_session):
    """A config.json without min_score_by_species (an older session) must not break Results."""
    from services import session_service
    cfg = session_service.get_config()
    cfg.pop("min_score_by_species", None)
    assert client.get("/api/results").json()["min_score_by_species"] == {}


# ─── session names (ported from the community fork) ───────────────────────────

def _setup_named(client, camtrap_dir, tmp_path, name, out="out"):
    r = client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / out), "target_species": ["Vulpes vulpes"],
        "study_start": "2025-11-01", "study_end": "2025-11-10", "occasion_days": 5, "total_iterations": 100_000,
        "gap_seconds": 60, "min_score": 0.5, "session_name": name})
    assert r.status_code == 200
    return r.json()["session_dir"]


def test_setup_stores_a_cleaned_session_name_and_lists_it(client, camtrap_dir, tmp_path):
    sd = _setup_named(client, camtrap_dir, tmp_path, "  Doñana   spring 2023 ")
    assert client.get("/api/state").json()["config"]["session_name"] == "Doñana spring 2023"
    recent = client.get("/api/session/recent").json()
    assert recent[0]["session_dir"] == sd and recent[0]["session_name"] == "Doñana spring 2023"


def test_sessions_without_a_name_have_an_empty_one(client, setup_session):
    assert client.get("/api/session/recent").json()[0]["session_name"] == ""


def test_rename_the_active_session(client, setup_session):
    r = client.put("/api/session/name", json={"name": "Spring"})
    assert r.status_code == 200 and r.json()["session_name"] == "Spring"
    assert client.get("/api/state").json()["config"]["session_name"] == "Spring"
    assert client.get("/api/session/recent").json()[0]["session_name"] == "Spring"


def test_rename_writes_config_json_whole_and_leaves_no_temp_file(client, setup_session):
    import json
    from pathlib import Path
    sd = Path(setup_session["session_dir"])
    client.put("/api/session/name", json={"name": "A name"})
    assert json.loads((sd / "config.json").read_text())["session_name"] == "A name"
    assert not list(sd.glob("*.tmp"))


def test_an_empty_name_clears_it(client, camtrap_dir, tmp_path):
    _setup_named(client, camtrap_dir, tmp_path, "Old name")
    assert client.put("/api/session/name", json={"name": "   "}).json()["session_name"] == ""
    assert client.get("/api/session/recent").json()[0]["session_name"] == ""


def test_rename_a_recent_session_that_is_not_the_active_one(client, camtrap_dir, tmp_path):
    first = _setup_named(client, camtrap_dir, tmp_path, "", out="o1")
    import time
    time.sleep(1.1)                                           # session folders are named by the second
    second = _setup_named(client, camtrap_dir, tmp_path, "Second", out="o2")
    assert first != second
    r = client.put("/api/session/name", json={"session_dir": first, "name": "First one"})
    assert r.status_code == 200
    names = {s["session_dir"]: s["session_name"] for s in client.get("/api/session/recent").json()}
    assert names == {first: "First one", second: "Second"}
    assert client.get("/api/state").json()["config"]["session_name"] == "Second"      # the active one is untouched


def test_rename_refuses_a_folder_that_is_not_a_known_session(client, setup_session, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "config.json").write_text('{"keep": "me"}')
    r = client.put("/api/session/name", json={"session_dir": str(other), "name": "Hacked"})
    assert r.status_code == 400
    assert (other / "config.json").read_text() == '{"keep": "me"}'                    # nothing written


def test_rename_without_any_session_is_a_clear_error(client):
    assert client.put("/api/session/name", json={"name": "x"}).status_code == 400


def test_a_name_longer_than_120_characters_is_rejected(client, setup_session):
    assert client.put("/api/session/name", json={"name": "x" * 121}).status_code == 422
    assert client.put("/api/session/name", json={"name": "x" * 120}).status_code == 200


def test_sessions_saved_before_names_existed_still_list(client, setup_session):
    import json
    from pathlib import Path
    cfg = Path(setup_session["session_dir"]) / "config.json"
    data = json.loads(cfg.read_text())
    data.pop("session_name", None)
    cfg.write_text(json.dumps(data))
    assert client.get("/api/session/recent").json()[0]["session_name"] == ""


# ─── Session export / import / relink ─────────────────────────────────────────

@pytest.fixture
def import_root(monkeypatch, tmp_path):
    import services.session_service as ss
    root = tmp_path / "imports"
    root.mkdir()
    monkeypatch.setattr(ss, "DEFAULT_OUTPUT_DIR", root)
    return root


@pytest.fixture(autouse=False)
def photos(camtrap_dir):
    """The fixture's photos (img/frameN.jpg next to the CamtrapDP), so image links resolve."""
    (camtrap_dir / "img").mkdir(exist_ok=True)
    for i in range(5):
        (camtrap_dir / "img" / f"frame{i}.jpg").write_bytes(b"\xff\xd8\xff\xe0")


def _export_to(client, tmp_path, name="exp.zip"):
    r = client.get("/api/session/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    zp = tmp_path / name
    zp.write_bytes(r.content)
    return zp


def test_setup_stores_the_dataset_fingerprint(client, setup_session):
    fp = client.get("/api/state").json()["config"]["dataset_fingerprint"]
    assert isinstance(fp, str) and len(fp) == 40


def test_export_contains_only_review_state(client, setup_session, tmp_path):
    import zipfile
    sd = __import__("pathlib").Path(setup_session["session_dir"])
    (sd / "decisions").mkdir(exist_ok=True)
    (sd / "decisions" / "decisions_x_iter1.csv").write_text("a\n1\n")
    (sd / "secret.txt").write_text("no")
    names = set(zipfile.ZipFile(_export_to(client, tmp_path)).namelist())
    assert {"config.json", "candidate_manifest.csv", "decisions/decisions_x_iter1.csv"} <= names
    assert "secret.txt" not in names


def test_export_without_session_is_an_error(client):
    assert client.get("/api/session/export").status_code == 400


def test_import_opens_the_session_in_a_new_folder(client, setup_session, tmp_path, import_root):
    from pathlib import Path
    sd = Path(setup_session["session_dir"])
    (sd / "decisions").mkdir(exist_ok=True)
    (sd / "decisions" / "decisions_x_iter1.csv").write_text("a\n1\n")
    zp = _export_to(client, tmp_path)
    r = client.post("/api/session/import", json={"zip_path": str(zp)})
    assert r.status_code == 200
    dest = Path(r.json()["session_dir"])
    assert dest.parent == import_root and dest != sd
    assert (dest / "decisions" / "decisions_x_iter1.csv").read_text() == "a\n1\n"
    cfg = r.json()["config"]
    assert cfg["session_dir"] == str(dest) and cfg["output_dir"] == str(dest / "camtrap_dp_verified")
    assert client.get("/api/state").json()["session_dir"] == str(dest)


def test_import_ignores_unsafe_members(client, tmp_path, import_root):
    import zipfile
    zp = tmp_path / "evil.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("config.json", "{}")
        zf.writestr("candidate_manifest.csv", "mediaID\n")
        zf.writestr("../escape.csv", "x")
        zf.writestr("/abs.json", "x")
        zf.writestr("decisions/../../up.csv", "x")
        zf.writestr("C:/win.json", "x")
        zf.writestr("other.txt", "x")
    from services import session_transfer
    dest = session_transfer.import_zip(str(zp))
    assert sorted(p.name for p in dest.rglob("*") if p.is_file()) == ["candidate_manifest.csv", "config.json"]
    assert not (import_root.parent / "escape.csv").exists()


def test_import_rejects_non_sessions(client, tmp_path, import_root):
    import zipfile
    bad = tmp_path / "bad.zip"
    bad.write_text("not a zip")
    assert client.post("/api/session/import", json={"zip_path": str(bad)}).status_code == 400
    nocfg = tmp_path / "nocfg.zip"
    with zipfile.ZipFile(nocfg, "w") as zf:
        zf.writestr("review_log.csv", "x")
    assert client.post("/api/session/import", json={"zip_path": str(nocfg)}).status_code == 400
    assert client.post("/api/session/import", json={"zip_path": str(tmp_path / "missing.zip")}).status_code == 400


def _break_link(sd, new_dir):
    import json
    cfg = sd / "config.json"
    data = json.loads(cfg.read_text())
    data["camtrap_dir"] = str(new_dir)
    cfg.write_text(json.dumps(data))


def test_state_reports_relink_ok_for_a_healthy_session(client, setup_session, photos):
    rl = client.get("/api/state").json()["relink"]
    assert rl["camtrap_dir_ok"] and not rl["needs_relink"]


def test_relink_needed_when_data_folder_is_missing(client, setup_session, tmp_path):
    from pathlib import Path
    _break_link(Path(setup_session["session_dir"]), tmp_path / "gone")
    client.post("/api/session/load", json={"session_dir": setup_session["session_dir"]})
    assert client.get("/api/state").json()["relink"]["needs_relink"] is True


def test_relink_endpoint_repoints_the_session(client, setup_session, camtrap_dir, tmp_path, photos):
    from pathlib import Path
    sd = Path(setup_session["session_dir"])
    _break_link(sd, tmp_path / "gone")
    client.post("/api/session/load", json={"session_dir": str(sd)})
    r = client.post("/api/session/relink", json={"camtrap_dir": str(camtrap_dir)})
    assert r.status_code == 200 and r.json()["relink"]["needs_relink"] is False
    import json
    assert json.loads((sd / "config.json").read_text())["camtrap_dir"] == str(camtrap_dir)


def test_relink_refuses_a_different_dataset(client, setup_session, camtrap_dir, tmp_path):
    import shutil
    other = tmp_path / "other"
    shutil.copytree(camtrap_dir, other)
    dep = next(other.glob("deployments*"))
    dep.write_text(dep.read_text() + "\n")
    r = client.post("/api/session/relink", json={"camtrap_dir": str(other)})
    assert r.status_code == 400
    assert client.post("/api/session/relink", json={"camtrap_dir": str(tmp_path / "nope")}).status_code == 400


def test_import_auto_relinks_when_the_dataset_is_known_locally(client, setup_session, tmp_path, import_root, photos):
    import json
    from pathlib import Path
    zp = _export_to(client, tmp_path)
    # Simulate another computer: the exported config points to a path that does not exist here.
    import zipfile
    moved = tmp_path / "moved.zip"
    with zipfile.ZipFile(zp) as zin, zipfile.ZipFile(moved, "w") as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n == "config.json":
                cfg = json.loads(data)
                cfg["camtrap_dir"] = "/other/computer/data"
                data = json.dumps(cfg).encode()
            zout.writestr(n, data)
    r = client.post("/api/session/import", json={"zip_path": str(moved)})
    assert r.status_code == 200
    assert r.json()["relink"]["needs_relink"] is False
    assert r.json()["config"]["camtrap_dir"] == json.loads((Path(setup_session["session_dir"]) / "config.json").read_text())["camtrap_dir"]


# ─── Progress of an unfinished round / reopening the previous round ───────────

def _setup_recording(client, camtrap_dir, tmp_path):
    r = client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"),
        "target_species": ["Vulpes vulpes"], "study_start": "2025-11-01", "study_end": "2025-11-10",
        "occasion_days": 5, "total_iterations": 100_000, "gap_seconds": 60, "min_score": 0.5,
        "record_rejection_species": True,
    })
    assert r.status_code == 200
    return Path(r.json()["session_dir"])


def _round1_events(client):
    return client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()


def _key(e):
    return e["key"]


def _progress(client, **params):
    return client.get("/api/species/Vulpes_vulpes/progress", params=params).json()["progress"]


def _put(client, body):
    return client.put("/api/species/Vulpes_vulpes/progress", json={"mode": "rounds", **body})


def test_no_progress_by_default(client, setup_session):
    assert client.get("/api/species/Vulpes_vulpes/progress", params={"mode": "rounds", "iteration": 1}).json() == {"progress": None}
    assert _progress(client) is None                                           # nor "the latest saved one"


def test_progress_is_saved_and_read_back(client, setup_session):
    ev = _round1_events(client)
    body = {"iteration": 1,
            "decisions": {_key(ev[0]): "confirmed", _key(ev[1]): "unsure", _key(ev[2]): "rejected"},
            "corrections": {_key(ev[2]): " Canis lupus "},
            "decision_times": {_key(ev[0]): 1700000000000}}
    r = _put(client, body)
    assert r.status_code == 200 and r.json()["n"] == 3
    got = _progress(client, mode="rounds", iteration=1)
    assert got["mode"] == "rounds" and got["iteration"] == 1
    assert got["decisions"] == body["decisions"]
    assert got["corrections"] == {_key(ev[2]): "Canis lupus"}
    assert got["decision_times"] == {_key(ev[0]): 1700000000000}
    assert got["saved_at"]


def test_the_latest_saved_progress_is_returned_without_parameters(client, setup_session):
    ev = _round1_events(client)
    _put(client, {"iteration": 1, "decisions": {_key(ev[0]): "confirmed"}})
    assert _progress(client)["decisions"] == {_key(ev[0]): "confirmed"}


def test_progress_is_one_file_per_species(client, setup_session):
    from pathlib import Path
    ev = _round1_events(client)
    _put(client, {"iteration": 1, "decisions": {_key(ev[0]): "confirmed"}})
    client.put("/api/species/Vulpes_vulpes/progress", json={"mode": "pending", "iteration": 0, "decisions": {_key(ev[1]): "rejected"}})
    files = list((Path(setup_session["session_dir"]) / "decisions").glob("progress_*.csv"))
    assert [f.name for f in files] == ["progress_Vulpes_vulpes.csv"]
    assert _progress(client, mode="pending", iteration=0)["decisions"] == {_key(ev[1]): "rejected"}
    assert _progress(client, mode="rounds", iteration=1)["decisions"] == {_key(ev[0]): "confirmed"}   # the other piece of work is kept


def test_progress_changes_no_result(client, setup_session):
    ev = _round1_events(client)
    before = client.get("/api/species").json()
    _put(client, {"iteration": 1, "decisions": {_key(ev[0]): "confirmed"}})
    assert client.get("/api/species").json() == before


def test_progress_ignores_unknown_values_and_empty_removes_it(client, setup_session):
    ev = _round1_events(client)
    r = _put(client, {"iteration": 1, "decisions": {_key(ev[0]): "confirmed", _key(ev[1]): "maybe"}})
    assert r.status_code == 200
    assert list(_progress(client, mode="rounds", iteration=1)["decisions"]) == [_key(ev[0])]
    _put(client, {"iteration": 1, "decisions": {}})
    assert _progress(client, mode="rounds", iteration=1) is None


def test_an_invalid_mode_is_refused(client, setup_session):
    assert client.put("/api/species/Vulpes_vulpes/progress", json={"mode": "later", "iteration": 1, "decisions": {}}).status_code == 400


def test_finishing_the_round_removes_its_progress(client, setup_session):
    ev = _round1_events(client)
    _put(client, {"iteration": 1, "decisions": {_key(ev[0]): "confirmed"}})
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [ev[0]["repObsId"]]})
    assert _progress(client, mode="rounds", iteration=1) is None


def test_progress_of_a_finished_round_is_refused(client, setup_session):
    ev = _round1_events(client)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [ev[0]["repObsId"]]})
    assert _put(client, {"iteration": 1, "decisions": {_key(ev[0]): "confirmed"}}).status_code == 400


def test_progress_travels_in_the_session_export(client, setup_session, tmp_path, import_root):
    ev = _round1_events(client)
    _put(client, {"iteration": 1, "decisions": {_key(ev[0]): "confirmed"}})
    zp = _export_to(client, tmp_path)
    assert "decisions/progress_Vulpes_vulpes.csv" in zipfile.ZipFile(zp).namelist()
    client.post("/api/session/import", json={"zip_path": str(zp)})
    assert _progress(client, mode="rounds", iteration=1)["decisions"] == {_key(ev[0]): "confirmed"}


def test_pending_progress_keeps_the_event_being_looked_at(client, camtrap_dir, tmp_path):
    _round1_with_two_unsure(client, camtrap_dir, tmp_path)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": []})
    pend = client.get("/api/species/Vulpes_vulpes/pending").json()
    key, rep = pend[0]["key"], pend[0]["frames"][0]["burstRepObsId"]
    r = client.put("/api/species/Vulpes_vulpes/progress", json={"mode": "pending", "iteration": 0,
                                                                "decisions": {key: "confirmed"}, "chosen_rep": {key: rep}})
    assert r.status_code == 200
    got = _progress(client, mode="pending", iteration=0)
    assert got["decisions"] == {key: "confirmed"} and got["chosen_rep"] == {key: rep}
    client.post("/api/species/Vulpes_vulpes/pending", json={"confirmed": [rep], "rejected_keys": []})
    assert _progress(client, mode="pending", iteration=0) is None              # settling it removes it


def _finish_round1(client, ev, times=None):
    return client.post("/api/decisions", json={
        "species": "Vulpes_vulpes", "iteration": 1,
        "confirmed": [ev[0]["repObsId"]], "unsure": [ev[1]["repObsId"]],
        "corrections": {ev[2]["repObsId"]: "Canis lupus"},
        "decision_times": times or {e["repObsId"]: 1700000000000 + 1000 * i for i, e in enumerate(ev)},
    })


def _session_files(sd):
    """Every file of the session except the backups and the CamtrapDP export, which carries
    wall-clock stamps (``generatedAt``, classification timestamp) that differ between runs."""
    return {f.relative_to(sd).as_posix(): f.read_bytes()
            for f in sorted(sd.rglob("*"))
            if f.is_file() and "reopened" not in f.parts and "camtrap_dp_verified" not in f.parts}


def test_reopen_restores_every_decision_flag_and_correction(client, camtrap_dir, tmp_path):
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    ev = _round1_events(client)
    _finish_round1(client, ev)
    r = client.post("/api/species/Vulpes_vulpes/reopen")
    assert r.status_code == 200 and r.json()["iteration"] == 1 and r.json()["restored"] == 3
    got = _progress(client, mode="rounds", iteration=1)
    assert got["decisions"] == {_key(ev[0]): "confirmed", _key(ev[1]): "unsure", _key(ev[2]): "rejected"}
    assert got["corrections"] == {_key(ev[2]): "Canis lupus"}
    assert len(got["decision_times"]) == 3
    assert not list((sd / "decisions").glob("decisions_Vulpes_vulpes_iter1.csv"))
    assert list((sd / "decisions" / "reopened").glob("decisions_Vulpes_vulpes_iter1.*.bak"))
    assert client.get("/api/species").json()[0]["n_confirmed_combos"] == 0        # nothing counts while it is open


def test_reopen_and_finish_again_gives_the_same_files(client, camtrap_dir, tmp_path):
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    ev = _round1_events(client)
    _finish_round1(client, ev)
    before = _session_files(sd)
    client.post("/api/species/Vulpes_vulpes/reopen")
    p = _progress(client, mode="rounds", iteration=1)
    rep = {e["key"]: e["repObsId"] for e in ev}                                   # progress is by cell; the round is saved by event
    r = client.post("/api/decisions", json={
        "species": "Vulpes_vulpes", "iteration": 1,
        "confirmed": [rep[k] for k, v in p["decisions"].items() if v == "confirmed"],
        "unsure": [rep[k] for k, v in p["decisions"].items() if v == "unsure"],
        "corrections": {rep[k]: t for k, t in p["corrections"].items()},
        "decision_times": {rep[k]: t for k, t in p["decision_times"].items()},
    })
    assert r.status_code == 200
    assert _session_files(sd) == before


def test_reopen_keeps_the_progress_of_the_later_round(client, camtrap_dir, tmp_path):
    _setup_recording(client, camtrap_dir, tmp_path)
    ev = _round1_events(client)
    _finish_round1(client, ev)
    _put(client, {"iteration": 2, "decisions": {_key(ev[0]): "rejected"}})
    client.post("/api/species/Vulpes_vulpes/reopen")
    assert _progress(client, mode="rounds", iteration=2) is not None


def test_cannot_reopen_without_a_finished_round(client, setup_session):
    assert client.post("/api/species/Vulpes_vulpes/reopen").status_code == 400


def test_cannot_reopen_after_the_species_was_edited(client, setup_session):
    ev = _round1_events(client)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [e["repObsId"] for e in ev]})
    keys = [e["key"] for e in ev]
    client.put("/api/species/Vulpes_vulpes/decisions", json={"confirmed_keys": keys[:1]})
    assert client.post("/api/species/Vulpes_vulpes/reopen").status_code == 400


# ─── Review order by time and time-to-detection outputs ───────────────────────

def _earlier_low_score_event(camtrap_dir):
    """SITE_A occ1: a low-score event (m005) at 08:00 on day 1, before the high-score one (10:00 on day 2)."""
    f = camtrap_dir / "media.csv"
    df = pd.read_csv(f, dtype=str)
    df.loc[df["mediaID"] == "m001", "timestamp"] = "2025-11-02 10:00:00"
    df.loc[df["mediaID"] == "m002", "timestamp"] = "2025-11-02 10:00:30"
    df.loc[df["mediaID"] == "m005", "timestamp"] = "2025-11-01 08:00:00"
    df.to_csv(f, index=False)


def _setup_order(client, camtrap_dir, tmp_path, order, **extra):
    body = {"camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / f"out_{order}"), "target_species": ["Vulpes vulpes"],
            "study_start": "2025-11-01", "study_end": "2025-11-10", "occasion_days": 5, "total_iterations": 100_000,
            "gap_seconds": 60, "min_score": 0.5, "review_order": order, **extra}
    r = client.post("/api/setup", json=body)
    assert r.status_code == 200, r.text
    return Path(r.json()["session_dir"])


def _ttd(sd, kind):
    return pd.read_csv(sd / "occupancy_inputs" / f"ttd_{kind}_Vulpes_vulpes.csv", dtype=str).fillna("").set_index("siteID")


def test_review_order_defaults_to_score_and_is_kept_in_the_config(client, camtrap_dir, tmp_path):
    _setup_order(client, camtrap_dir, tmp_path, "score")
    assert client.get("/api/state").json()["config"]["review_order"] == "score"
    assert client.post("/api/setup", json={"camtrap_dir": str(camtrap_dir), "target_species": ["Vulpes vulpes"], "study_start": "2025-11-01",
                                           "study_end": "2025-11-10", "review_order": "random"}).status_code == 422


def test_by_score_shows_the_most_confident_event_first(client, camtrap_dir, tmp_path):
    _earlier_low_score_event(camtrap_dir)
    _setup_order(client, camtrap_dir, tmp_path, "score")
    first = {e["key"]: e for e in _round1_events(client)}["SITE_A_occ1_Vulpes_vulpes"]
    assert {f["mediaId"] for f in first["frames"]} == {"m001", "m002"}                      # 0.9 beats the earlier 0.6


def test_by_time_shows_the_earliest_event_first(client, camtrap_dir, tmp_path):
    _earlier_low_score_event(camtrap_dir)
    _setup_order(client, camtrap_dir, tmp_path, "time")
    first = {e["key"]: e for e in _round1_events(client)}["SITE_A_occ1_Vulpes_vulpes"]
    assert {f["mediaId"] for f in first["frames"]} == {"m005"}
    ev2 = {e["key"]: e for e in client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 2}).json()}
    assert {f["mediaId"] for f in ev2["SITE_A_occ1_Vulpes_vulpes"]["frames"]} == {"m001", "m002"}


def test_detection_histories_are_the_same_in_either_order(client, camtrap_dir, tmp_path):
    _earlier_low_score_event(camtrap_dir)
    results = {}
    for order in ("score", "time"):
        sd = _setup_order(client, camtrap_dir, tmp_path, order)
        true_media = {"m001", "m002", "m003"}                      # the "truth": review every round to the end
        for it in range(1, 4):
            ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": it}).json()
            if not ev:
                break
            conf = [e["repObsId"] for e in ev if {f["mediaId"] for f in e["frames"]} & true_media]
            client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": it, "confirmed": conf})
        results[order] = {k: (sd / "occupancy_inputs" / f"dethist_{k}_Vulpes_vulpes.csv").read_text() for k in ("naive", "verified")}
    assert results["score"] == results["time"]


def test_ttd_files_for_day_occasions_with_censoring_and_na(client, camtrap_dir, tmp_path):
    _earlier_low_score_event(camtrap_dir)
    dep = camtrap_dir / "deployments.csv"
    d = pd.read_csv(dep, dtype=str)
    d.loc[d["deploymentID"] == "DEP2", "deploymentEnd"] = "2025-11-05"             # SITE_B off in occasion 2
    d.to_csv(dep, index=False)
    sd = _setup_order(client, camtrap_dir, tmp_path, "time")
    naive = _ttd(sd, "naive")
    assert naive.loc["SITE_A", "occ1"] == "8.0"                                    # m005, 08:00 on day 1
    assert naive.loc["SITE_A", "occ2"] == "38.0"                                   # m003, 14:00 on day 7 -> 38 h after 6 Nov 00:00
    assert naive.loc["SITE_B", "occ1"] == "57.0"                                   # m004
    assert naive.loc["SITE_B", "occ2"] == ""                                       # camera off: NA
    verified = _ttd(sd, "verified")
    assert (verified == "").all().all()                                            # nothing decided yet: every cell with events is pending, SITE_B occ2 is off
    assert verified.loc["SITE_B", "occ2"] == ""
    # round 1 (by time): reject SITE_A occ1's earliest event, confirm the rest
    ev = _round1_events(client)
    conf = [e["repObsId"] for e in ev if e["key"] != "SITE_A_occ1_Vulpes_vulpes"]
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": conf})
    ev2 = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 2}).json()
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": [e["repObsId"] for e in ev2]})
    verified = _ttd(sd, "verified")
    assert verified.loc["SITE_A", "occ1"] == "34.0"                                # the confirmed event: 02 Nov 10:00
    assert verified.loc["SITE_A", "occ2"] == "38.0"
    assert verified.loc["SITE_B", "occ1"] == "57.0"
    assert verified.loc["SITE_B", "occ2"] == ""                                    # camera off stays NA


def test_ttd_verified_is_censored_for_a_cell_whose_events_were_all_rejected(client, camtrap_dir, tmp_path):
    sd = _setup_order(client, camtrap_dir, tmp_path, "time")
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": []})
    ev2 = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 2}).json()
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": []})
    v = _ttd(sd, "verified")
    assert v.loc["SITE_B", "occ1"] == "120.0"                                      # rejected: censored at the 5-day occasion
    assert v.loc["SITE_B", "occ2"] == "120.0"                                      # no candidate at all: censored too
    assert v.loc["SITE_A", "occ2"] == "120.0"
    assert ev2                                                                     # (round 2 existed for SITE_A occ1)


def test_ttd_for_occasions_in_hours(client, camtrap_dir, tmp_path):
    _earlier_low_score_event(camtrap_dir)
    sd = _setup_order(client, camtrap_dir, tmp_path, "time", occasion_hours=7)
    naive = _ttd(sd, "naive")
    # 07:00-wide windows from 1 Nov 00:00: 1 Nov 08:00 -> window 2 (7-14 h), 1 h in
    assert naive.loc["SITE_A", "occ2"] == "1.0"
    assert naive.loc["SITE_A", "occ1"] == "7.0"                                    # no detection: censored at 7 h
    last = naive.columns[-1]
    assert naive.loc["SITE_B", last] == "2.0"                                      # 240 h = 34 x 7 + 2: the last occasion is 2 h long

# ─── observationTags in the verified CamtrapDP ────────────────────────────────

def _verified_observations(sd):
    return pd.read_csv(Path(sd) / "camtrap_dp_verified" / "observations.csv", dtype=str).fillna("")


def _tags_by_media(sd):
    obs = _verified_observations(sd)
    return {m: t for m, t in zip(obs["mediaID"], obs["observationTags"])}


def _review_round1(client, camtrap_dir, tmp_path):
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    ev = _round1_events(client)
    client.post("/api/decisions", json={
        "species": "Vulpes_vulpes", "iteration": 1,
        "confirmed": [ev[0]["repObsId"]], "unsure": [ev[1]["repObsId"]],
        "corrections": {ev[2]["repObsId"]: "Canis lupus"},
    })
    return sd, ev


def _media_of(ev, i):
    """Media of the photo that represents event ``i`` (the one the review decides on)."""
    return {f["mediaId"] for f in ev[i]["frames"] if f["obsId"] == ev[i]["repObsId"]}


def test_confirmed_rejected_and_unsure_events_carry_their_tag(client, camtrap_dir, tmp_path):
    sd, ev = _review_round1(client, camtrap_dir, tmp_path)
    client.get("/api/results")                                        # brings the verified CamtrapDP up to date
    tags = _tags_by_media(sd)
    assert all("camtrapverify:confirmed" in tags[m].split("|") for m in _media_of(ev, 0))
    rep = {f["mediaId"] for f in ev[1]["frames"] if f["obsId"] == ev[1]["repObsId"]}
    assert all(tags[m].split("|") == ["camtrapverify:unsure"] for m in rep)
    rep = {f["mediaId"] for f in ev[2]["frames"] if f["obsId"] == ev[2]["repObsId"]}
    assert all(tags[m].split("|") == ["camtrapverify:rejected", "camtrapverify-actual-species:Canis lupus"] for m in rep)


def test_confirmed_observations_are_not_also_tagged_rejected(client, camtrap_dir, tmp_path):
    sd, ev = _review_round1(client, camtrap_dir, tmp_path)
    client.get("/api/results")
    for m in _media_of(ev, 0):
        assert "rejected" not in _tags_by_media(sd)[m]


def test_events_never_inspected_get_no_tag(client, camtrap_dir, tmp_path):
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    client.get("/api/results")
    obs = _verified_observations(sd)
    assert "observationTags" not in obs.columns or set(obs["observationTags"]) == {""}      # nothing reviewed: no tags


def test_an_earlier_rejected_event_of_a_confirmed_cell_is_tagged_rejected(client, camtrap_dir, tmp_path):
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    ev1 = _round1_events(client)
    # round 1: reject everything; round 2: confirm the second-ranked event of the cell that has one
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": []})
    ev2 = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 2}).json()
    assert ev2
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": [ev2[0]["repObsId"]]})
    client.get("/api/results")
    tags = _tags_by_media(sd)
    cell = ev2[0]["key"]
    first = next(e for e in ev1 if e["key"] == cell)
    rep = {f["mediaId"] for f in first["frames"] if f["obsId"] == first["repObsId"]}
    assert all(tags[m] == "camtrapverify:rejected" for m in rep)                   # rejected in round 1
    assert all("camtrapverify:confirmed" in tags[m] for m in _media_of(ev2, 0))    # confirmed in round 2


def test_existing_observation_tags_are_kept(client, camtrap_dir, tmp_path):
    obs_file = camtrap_dir / "observations.csv"
    df = pd.read_csv(obs_file, dtype=str)
    df["observationTags"] = "travelDirection:left"
    df.to_csv(obs_file, index=False)
    sd, ev = _review_round1(client, camtrap_dir, tmp_path)
    client.get("/api/results")
    tags = _tags_by_media(sd)
    m = next(iter(_media_of(ev, 0)))
    assert tags[m].split("|") == ["travelDirection:left", "camtrapverify:confirmed"]


def test_tags_follow_the_pipe_separated_key_value_format(client, camtrap_dir, tmp_path):
    sd, _ = _review_round1(client, camtrap_dir, tmp_path)
    client.get("/api/results")
    for cell in _verified_observations(sd)["observationTags"]:
        for tag in filter(None, cell.split("|")):
            assert tag.count(":") >= 1 and not tag.startswith(":") and not tag.endswith(":")


def test_tags_are_not_repeated_by_a_second_export(client, camtrap_dir, tmp_path):
    sd, ev = _review_round1(client, camtrap_dir, tmp_path)
    client.get("/api/results")
    first = _verified_observations(sd)["observationTags"].tolist()
    client.put("/api/species/Vulpes_vulpes/progress", json={"mode": "rounds", "iteration": 2, "decisions": {}})      # any other save
    from services import workflow_service
    workflow_service.write_verified_export() if hasattr(workflow_service, "write_verified_export") else workflow_service.rebuild_outputs()
    assert _verified_observations(sd)["observationTags"].tolist() == first


def test_extended_confirmation_tags_every_photo_of_the_confirmed_event(client, camtrap_dir, tmp_path):
    r = client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"), "target_species": ["Vulpes vulpes"],
        "study_start": "2025-11-01", "study_end": "2025-11-10", "occasion_days": 5, "total_iterations": 100_000,
        "gap_seconds": 60, "min_score": 0.5, "extended_confirmation": True,
    })
    ev = _round1_events(client)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [ev[0]["repObsId"]]})
    client.get("/api/results")
    tags = _tags_by_media(Path(r.json()["session_dir"]))
    assert all("camtrapverify:confirmed" in tags[f["mediaId"]] for f in ev[0]["frames"])

# ─── Large archives: image index, cacheable URLs ──────────────────────────────

def test_gallery_image_urls_carry_the_session_token(client, setup_session):
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    imgs = [f["img"] for e in ev for f in e["frames"]]
    assert imgs and all(i.startswith("/api/image/") and "?v=" in i for i in imgs)
    assert len({i.split("?v=")[1] for i in imgs}) == 1


def test_image_with_token_is_cacheable_and_bare_url_is_not(client, camtrap_dir, photos, tmp_path):
    client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"), "target_species": ["Vulpes vulpes"],
        "study_start": "2025-11-01", "study_end": "2025-11-10", "occasion_days": 5, "total_iterations": 100_000,
        "gap_seconds": 60, "min_score": 0.5,
    })
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    url = ev[0]["frames"][0]["img"]
    assert client.get(url).headers["cache-control"] == "private, max-age=86400"
    bare = url.split("?")[0]
    r = client.get(bare)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"


def test_image_lookup_uses_the_index_and_still_404s_unknown_media(client, setup_session):
    assert client.get("/api/image/does-not-exist").status_code == 404


def test_media_index_is_rebuilt_for_a_new_session(client, camtrap_dir, tmp_path):
    from services import session_service
    for n in ("a", "b"):
        client.post("/api/setup", json={
            "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / n), "target_species": ["Vulpes vulpes"],
            "study_start": "2025-11-01", "study_end": "2025-11-10", "occasion_days": 5, "total_iterations": 100_000,
            "gap_seconds": 60, "min_score": 0.5,
        })
        assert session_service.media_lookup("m001")["filePath"].endswith("frame0.jpg")
        first = session_service._state["_media_index"][0]
        assert first is session_service.get_candidates()


def test_image_token_changes_when_the_photos_are_relinked(client, setup_session, camtrap_dir):
    from services import session_service
    before = session_service.image_token()
    session_service.update_paths(str(camtrap_dir), "/somewhere/else", False)
    assert session_service.image_token() != before


# ─── Datasets made by "Classifiers and reference" ─────────────────────────────

def _tag_filtered(camtrap_dir, media_id="m005"):
    f = camtrap_dir / "observations.csv"
    df = pd.read_csv(f, dtype=str)
    df["observationTags"] = ""
    df.loc[df["mediaID"] == media_id, "observationTags"] = "camtrapverify:filtered"
    df.to_csv(f, index=False)


def test_events_removed_by_the_classifier_combination_are_not_reviewed(client, camtrap_dir, tmp_path):
    _tag_filtered(camtrap_dir)                                         # m005 is SITE_A occ1's second event
    _setup_recording(client, camtrap_dir, tmp_path)
    media = {f["mediaId"] for it in (1, 2) for e in client.get("/api/species/Vulpes_vulpes/events", params={"iteration": it}).json() for f in e["frames"]}
    assert "m005" not in media and "m001" in media
    assert client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 2}).json() == []     # no second event left


def test_filtered_and_review_tags_live_together_in_the_verified_camtrapdp(client, camtrap_dir, tmp_path):
    _tag_filtered(camtrap_dir)
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    ev = _round1_events(client)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [ev[0]["repObsId"]]})
    client.get("/api/results")
    tags = _tags_by_media(sd)
    assert tags["m005"] == "camtrapverify:filtered"                    # kept, never reviewed
    assert "camtrapverify:confirmed" in tags[next(iter(_media_of(ev, 0)))].split("|")


def test_the_verified_camtrapdp_keeps_every_column_of_the_source(client, camtrap_dir, tmp_path):
    """Sessions read only the columns they need, but the export is written from a full read."""
    f = camtrap_dir / "observations.csv"
    df = pd.read_csv(f, dtype=str)
    df["observationComments"], df["lifeStage"] = "keep me", "adult"
    df.to_csv(f, index=False)
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    ev = _round1_events(client)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [ev[0]["repObsId"]]})
    client.get("/api/results")
    v = _verified_observations(sd)
    assert {"observationComments", "lifeStage"} <= set(v.columns)
    assert (v["observationComments"] == "keep me").all() and (v["lifeStage"] == "adult").all()


# ─── Unsure decisions and pending expert review ───────────────────────────────

def _round1_with_two_unsure(client, camtrap_dir, tmp_path):
    """Round 1: confirm SITE_A occ1's event is NOT done; mark SITE_A occ2 and SITE_B occ1 unsure, reject occ1."""
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    ev = {e["key"]: e for e in _round1_events(client)}
    unsure = [ev["SITE_A_occ2_Vulpes_vulpes"]["repObsId"], ev["SITE_B_occ1_Vulpes_vulpes"]["repObsId"]]
    r = client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [], "unsure": unsure})
    assert r.status_code == 200
    return sd, ev


def test_cells_with_an_unsure_event_and_no_events_left_become_pending(client, camtrap_dir, tmp_path):
    _round1_with_two_unsure(client, camtrap_dir, tmp_path)
    sp = client.get("/api/species").json()[0]
    assert sp["n_pending"] == 2 and sp["phase"] == "rounds"                    # SITE_A occ1 still has a second event
    ev2 = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 2}).json()
    assert [e["key"] for e in ev2] == ["SITE_A_occ1_Vulpes_vulpes"]            # unsure counts as "not confirmed": next event shown
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": []})
    sp = client.get("/api/species").json()[0]
    assert sp["phase"] == "pending" and sp["n_pending"] == 2
    assert sp["n_resolved"] < sp["n_total_combos"]                            # not complete while pending


def test_pending_cells_list_their_unsure_events_and_can_be_settled(client, camtrap_dir, tmp_path):
    sd, ev = _round1_with_two_unsure(client, camtrap_dir, tmp_path)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": []})
    pend = client.get("/api/species/Vulpes_vulpes/pending").json()
    assert [e["key"] for e in pend] == ["SITE_A_occ2_Vulpes_vulpes", "SITE_B_occ1_Vulpes_vulpes"]
    assert all(e["status"] == "pending" and all("burstRepObsId" in f for f in e["frames"]) for e in pend)
    keep = pend[0]["frames"][0]["burstRepObsId"]
    r = client.post("/api/species/Vulpes_vulpes/pending", json={"confirmed": [keep], "rejected_keys": ["SITE_B_occ1_Vulpes_vulpes"]})
    assert r.json() == {"success": True, "confirmed": 1, "rejected": 1}
    assert client.get("/api/species/Vulpes_vulpes/pending").json() == []
    sp = client.get("/api/species").json()[0]
    assert sp["n_pending"] == 0 and sp["phase"] == "complete" and sp["n_confirmed_combos"] == 1


def test_results_report_the_pending_cells_and_the_histories_leave_them_na(client, camtrap_dir, tmp_path):
    sd, _ = _round1_with_two_unsure(client, camtrap_dir, tmp_path)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": []})
    res = client.get("/api/results").json()
    assert res["pending"] == 2 and res["by_species"][0]["pending"] == 2
    assert res["effort_by_species"][0]["cells_pending"] == 2
    v = pd.read_csv(sd / "occupancy_inputs" / "dethist_verified_Vulpes_vulpes.csv", dtype=str).fillna("").set_index("siteID")
    assert v.loc["SITE_A", "occ2"] == "" and v.loc["SITE_B", "occ1"] == "" and v.loc["SITE_A", "occ1"] == "0"
    status = pd.read_csv(sd / "occupancy_inputs" / "cell_status_Vulpes_vulpes.csv", dtype=str).fillna("").set_index("siteID")
    assert status.loc["SITE_A", "occ2"] == "pending"


def test_tags_follow_the_pending_review(client, camtrap_dir, tmp_path):
    sd, ev = _round1_with_two_unsure(client, camtrap_dir, tmp_path)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": []})
    client.get("/api/results")
    tags = _tags_by_media(sd)
    a2 = next(f["mediaId"] for f in ev["SITE_A_occ2_Vulpes_vulpes"]["frames"] if f["obsId"] == ev["SITE_A_occ2_Vulpes_vulpes"]["repObsId"])
    assert tags[a2] == "camtrapverify:unsure"                                  # still waiting for an expert
    client.post("/api/species/Vulpes_vulpes/pending", json={"confirmed": [], "rejected_keys": ["SITE_A_occ2_Vulpes_vulpes"]})
    client.get("/api/results")
    assert _tags_by_media(sd)[a2] == "camtrapverify:rejected"                  # settled as not detected


def test_cannot_reopen_a_round_after_pending_cells_were_settled(client, camtrap_dir, tmp_path):
    _round1_with_two_unsure(client, camtrap_dir, tmp_path)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": []})
    client.post("/api/species/Vulpes_vulpes/pending", json={"confirmed": [], "rejected_keys": ["SITE_B_occ1_Vulpes_vulpes"]})
    assert client.post("/api/species/Vulpes_vulpes/reopen").status_code == 400


def test_editing_a_species_settles_its_pending_cells(client, camtrap_dir, tmp_path):
    _round1_with_two_unsure(client, camtrap_dir, tmp_path)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": []})
    assert client.get("/api/species").json()[0]["n_pending"] == 2
    client.put("/api/species/Vulpes_vulpes/decisions", json={"confirmed_keys": ["SITE_A_occ2_Vulpes_vulpes"]})
    sp = client.get("/api/species").json()[0]
    assert sp["n_pending"] == 0 and sp["n_confirmed_combos"] == 1 and sp["phase"] == "complete"


# ─── Another species in the photo (cross-species confirmation) ────────────────

def _two_species_session(client, camtrap_dir, tmp_path):
    """m004 (SITE_B occ1) becomes a wild boar, so there are two target species."""
    f = camtrap_dir / "observations.csv"
    df = pd.read_csv(f, dtype=str)
    df.loc[df["mediaID"] == "m004", "scientificName"] = "Sus scrofa"
    df.to_csv(f, index=False)
    r = client.post("/api/setup", json={
        "camtrap_dir": str(camtrap_dir), "output_dir": str(tmp_path / "out"), "target_species": ["Vulpes vulpes", "Sus scrofa"],
        "study_start": "2025-11-01", "study_end": "2025-11-10", "occasion_days": 5, "gap_seconds": 60, "min_score": 0.5,
        "record_rejection_species": True,
    })
    assert r.status_code == 200, r.text
    return Path(r.json()["session_dir"])


def _cross(client, species="Sus scrofa", site="SITE_A", occ=1, media="m001", obs="o001", source="Vulpes vulpes"):
    return client.post("/api/cross", json={"species": species, "site_id": site, "occasion": occ, "media_id": media,
                                           "observation_id": obs, "source_species": source})


def test_every_target_species_is_listed_for_a_cell(client, camtrap_dir, tmp_path):
    _two_species_session(client, camtrap_dir, tmp_path)
    r = client.get("/api/cross", params={"site_id": "SITE_A", "occasion": 1}).json()["species"]
    assert {s["scientificName"]: s["status"] for s in r} == {"Vulpes vulpes": "none", "Sus scrofa": "none"}


def test_confirming_a_species_the_classifier_missed_is_a_detection_and_a_false_negative(client, camtrap_dir, tmp_path):
    sd = _two_species_session(client, camtrap_dir, tmp_path)
    assert _cross(client).json()["success"] is True
    st = {s["scientificName"]: s for s in client.get("/api/cross", params={"site_id": "SITE_A", "occasion": 1}).json()["species"]}
    assert st["Sus scrofa"]["status"] == "cross" and st["Sus scrofa"]["mediaID"] == "m001"
    client.get("/api/results")                                            # opening Results rebuilds the stale outputs
    v = pd.read_csv(sd / "occupancy_inputs" / "dethist_verified_Sus_scrofa.csv", dtype=str).fillna("").set_index("siteID")
    n = pd.read_csv(sd / "occupancy_inputs" / "dethist_naive_Sus_scrofa.csv", dtype=str).fillna("").set_index("siteID")
    assert v.loc["SITE_A", "occ1"] == "1" and n.loc["SITE_A", "occ1"] == "0"
    summary = pd.read_csv(sd / "occupancy_inputs" / "verification_summary.csv").set_index("species")
    assert summary.loc["Sus scrofa", "false_negative_cells"] == 1
    obs = _verified_observations(sd)
    added = obs[(obs["mediaID"] == "m001") & (obs["scientificName"] == "Sus scrofa")]
    assert len(added) == 1 and added.iloc[0]["classificationMethod"] == "human"
    assert added.iloc[0]["observationTags"] == "camtrapverify:confirmed" and added.iloc[0]["observationID"] == "m001_Sus_scrofa_expert"


def test_a_cell_confirmed_from_another_photo_leaves_that_species_rounds(client, camtrap_dir, tmp_path):
    sd = _two_species_session(client, camtrap_dir, tmp_path)
    assert [e["key"] for e in client.get("/api/species/Sus_scrofa/events", params={"iteration": 1}).json()] == ["SITE_B_occ1_Sus_scrofa"]
    _cross(client, site="SITE_B", occ=1, media="m001", obs="o001")
    assert client.get("/api/species/Sus_scrofa/events", params={"iteration": 1}).json() == []      # no event to inspect
    sp = {s["species_safe"]: s for s in client.get("/api/species").json()}
    assert sp["Sus_scrofa"]["n_confirmed_combos"] == 1 and sp["Sus_scrofa"]["n_resolved"] == sp["Sus_scrofa"]["n_total_combos"]
    res = client.get("/api/results").json()
    row = next(r for r in res["effort_by_species"] if r["species"] == "Sus scrofa")
    assert row["cells_detection"] == 1 and row["events_inspected"] == 0                         # it cost no events


def test_undoing_it_leaves_no_trace(client, camtrap_dir, tmp_path):
    sd = _two_species_session(client, camtrap_dir, tmp_path)
    client.get("/api/results")
    before = {f.name: f.read_bytes() for f in sorted((sd / "occupancy_inputs").glob("*.csv")) if f.name not in ("review_effort.csv",)}
    obs_before = _verified_observations(sd).drop(columns=["classificationTimestamp"]).to_dict("records")
    _cross(client)
    r = client.delete("/api/cross", params={"species": "Sus scrofa", "site_id": "SITE_A", "occasion": 1})
    assert r.json()["removed"] == 1
    client.get("/api/results")
    assert not list((sd / "decisions").glob("cross_*.csv"))
    after = {f.name: f.read_bytes() for f in sorted((sd / "occupancy_inputs").glob("*.csv")) if f.name not in ("review_effort.csv",)}
    assert after == before
    assert _verified_observations(sd).drop(columns=["classificationTimestamp"]).to_dict("records") == obs_before


def test_a_cross_confirmation_is_validated(client, camtrap_dir, tmp_path):
    _two_species_session(client, camtrap_dir, tmp_path)
    assert _cross(client, species="Canis lupus").status_code == 400                # not a target species
    assert _cross(client, species="Vulpes vulpes", source="Vulpes vulpes").status_code == 400   # use Confirmed for that one


def test_confirming_from_another_photo_marks_an_existing_observation_of_the_species(client, camtrap_dir, tmp_path):
    sd = _two_species_session(client, camtrap_dir, tmp_path)
    _cross(client, site="SITE_B", occ=1, media="m004", obs="o004", source="Vulpes vulpes")   # m004 already has a Sus observation
    client.get("/api/results")
    obs = _verified_observations(sd)
    boar = obs[(obs["mediaID"] == "m004") & (obs["scientificName"] == "Sus scrofa")]
    assert len(boar) == 1 and boar.iloc[0]["classificationMethod"] == "human" and boar.iloc[0]["observationID"] == "o004"


def test_editing_a_species_drops_the_cross_confirmations_it_leaves_unconfirmed(client, camtrap_dir, tmp_path):
    _two_species_session(client, camtrap_dir, tmp_path)
    ev = client.get("/api/species/Sus_scrofa/events", params={"iteration": 1}).json()
    client.post("/api/decisions", json={"species": "Sus_scrofa", "iteration": 1, "confirmed": []})
    _cross(client, site="SITE_B", occ=1, media="m001", obs="o001")
    assert client.get("/api/species").json()  # sanity
    client.put("/api/species/Sus_scrofa/decisions", json={"confirmed_keys": []})
    st = {s["scientificName"]: s["status"] for s in client.get("/api/cross", params={"site_id": "SITE_B", "occasion": 1}).json()["species"]}
    assert st["Sus scrofa"] == "none" and ev


def test_setup_stores_the_archive_stats_and_older_sessions_get_them_once(client, setup_session):
    import json
    from pathlib import Path
    cfg_file = Path(setup_session["session_dir"]) / "config.json"
    assert json.loads(cfg_file.read_text())["archive_stats"] == {"total_observations": 5, "target_assigned": 5}
    # a session made before they were stored: the first save computes and stores them
    data = json.loads(cfg_file.read_text())
    del data["archive_stats"]
    cfg_file.write_text(json.dumps(data))
    client.post("/api/session/load", json={"session_dir": str(cfg_file.parent)})
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [ev[0]["repObsId"]]})
    assert json.loads(cfg_file.read_text())["archive_stats"] == {"total_observations": 5, "target_assigned": 5}
    row = pd.read_csv(cfg_file.parent / "occupancy_inputs" / "review_effort.csv").iloc[0]
    assert row["total_classified_images"] == 5


def test_ttd_verified_is_only_written_when_the_review_was_by_time(client, camtrap_dir, tmp_path):
    by_score = _setup_order(client, camtrap_dir, tmp_path, "score")
    files = {f.name for f in (by_score / "occupancy_inputs").glob("ttd_*.csv")}
    assert files == {"ttd_naive_Vulpes_vulpes.csv"}                         # the naive one does not depend on the review
    by_time = _setup_order(client, camtrap_dir, tmp_path, "time")
    assert {f.name for f in (by_time / "occupancy_inputs").glob("ttd_*.csv")} == {"ttd_naive_Vulpes_vulpes.csv", "ttd_verified_Vulpes_vulpes.csv"}


def test_a_stale_verified_ttd_file_is_removed_in_score_order(client, camtrap_dir, tmp_path):
    sd = _setup_order(client, camtrap_dir, tmp_path, "score")
    stale = sd / "occupancy_inputs" / "ttd_verified_Vulpes_vulpes.csv"
    stale.write_text("siteID,occ1\nSITE_A,1\n")                              # left by an earlier version
    ev = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json()
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [ev[0]["repObsId"]]})
    assert not stale.exists()


def test_the_naive_ttd_is_the_same_in_either_order(client, camtrap_dir, tmp_path):
    a = _setup_order(client, camtrap_dir, tmp_path, "score")
    b = _setup_order(client, camtrap_dir, tmp_path, "time")
    assert (a / "occupancy_inputs" / "ttd_naive_Vulpes_vulpes.csv").read_text() == (b / "occupancy_inputs" / "ttd_naive_Vulpes_vulpes.csv").read_text()


# ─── Tags on every photo of a rejected or unsure event ────────────────────────

def _event_media(ev):
    return {f["mediaId"] for f in ev["frames"] if not f["isContext"]}


def test_every_photo_of_a_rejected_event_carries_the_tag_and_the_actual_species(client, camtrap_dir, tmp_path):
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    ev = {e["key"]: e for e in _round1_events(client)}
    a1 = ev["SITE_A_occ1_Vulpes_vulpes"]
    assert _event_media(a1) == {"m001", "m002"}                            # a two-photo event
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [],
                                        "corrections": {a1["repObsId"]: "Canis lupus"}})
    client.get("/api/results")
    tags = _tags_by_media(sd)
    for m in ("m001", "m002"):
        assert tags[m].split("|") == ["camtrapverify:rejected", "camtrapverify-actual-species:Canis lupus"], m
    assert tags["m005"] == ""                                              # second event of the cell: not inspected yet


def test_every_photo_of_an_unsure_event_carries_the_unsure_tag(client, camtrap_dir, tmp_path):
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    a1 = {e["key"]: e for e in _round1_events(client)}["SITE_A_occ1_Vulpes_vulpes"]
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [], "unsure": [a1["repObsId"]]})
    client.get("/api/results")
    tags = _tags_by_media(sd)
    assert tags["m001"] == tags["m002"] == "camtrapverify:unsure"


def test_the_earlier_rejected_event_of_a_confirmed_cell_is_tagged_on_all_its_photos(client, camtrap_dir, tmp_path):
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": []})
    ev2 = client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 2}).json()
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": [ev2[0]["repObsId"]]})
    client.get("/api/results")
    tags = _tags_by_media(sd)
    assert tags["m001"] == tags["m002"] == "camtrapverify:rejected"          # round 1, both photos
    assert tags["m005"] == "camtrapverify:confirmed"                        # round 2


def test_the_actual_species_goes_only_on_rejected_events(client, camtrap_dir, tmp_path):
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    ev = {e["key"]: e for e in _round1_events(client)}
    a1, a2 = ev["SITE_A_occ1_Vulpes_vulpes"], ev["SITE_A_occ2_Vulpes_vulpes"]
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [a2["repObsId"]],
                                        "corrections": {a1["repObsId"]: "Canis lupus", a2["repObsId"]: "Sus scrofa"}})
    client.get("/api/results")
    tags = _tags_by_media(sd)
    assert "actual-species" not in tags["m003"]                              # confirmed: the typed species is ignored
    assert "camtrapverify-actual-species:Canis lupus" in tags["m001"].split("|")


def test_verifying_a_package_that_already_has_review_tags_does_not_duplicate_them(client, camtrap_dir, tmp_path):
    import pandas as pd
    from pathlib import Path
    obs_file = camtrap_dir / "observations.csv"
    obs = pd.read_csv(obs_file, dtype=str)
    obs["observationTags"] = "travelDirection:left"
    obs.loc[obs["mediaID"] == "m001", "observationTags"] = "camtrapverify:confirmed|camtrapverify:rejected|camtrapverify-actual-species:Sus scrofa|travelDirection:left"
    obs.to_csv(obs_file, index=False)
    sd = _setup_recording(client, camtrap_dir, tmp_path)
    a1 = {e["key"]: e for e in _round1_events(client)}["SITE_A_occ1_Vulpes_vulpes"]
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 1, "confirmed": [a1["repObsId"]]})
    client.get("/api/results")
    tags = _tags_by_media(sd)["m001"].split("|")
    assert tags.count("camtrapverify:confirmed") == 1
    assert "camtrapverify:rejected" not in tags and not any(t.startswith("camtrapverify-actual-species") for t in tags)
    assert "travelDirection:left" in tags


def test_a_cell_confirmed_in_the_pending_review_reaches_the_verified_camtrapdp(client, camtrap_dir, tmp_path):
    import pandas as pd
    sd, ev = _round1_with_two_unsure(client, camtrap_dir, tmp_path)
    client.post("/api/decisions", json={"species": "Vulpes_vulpes", "iteration": 2, "confirmed": []})
    pend = {e["key"]: e for e in client.get("/api/species/Vulpes_vulpes/pending").json()}
    rep = pend["SITE_A_occ2_Vulpes_vulpes"]["frames"][0]["burstRepObsId"]
    client.post("/api/species/Vulpes_vulpes/pending", json={"confirmed": [rep], "rejected_keys": []})
    assert client.get("/api/results").json()["confirmed"] >= 1
    obs = pd.read_csv(sd / "camtrap_dp_verified" / "observations.csv", dtype=str)
    row = obs[obs["observationID"] == rep].iloc[0]
    assert row["classificationMethod"] == "human"                              # the expert's verdict is in the export
    assert row["observationTags"].split("|").count("camtrapverify:confirmed") == 1
