"""Shared pytest fixtures and path setup for the backend test suite."""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

# Make backend/src/ importable without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ─── Minimal CamtrapDP dataset ────────────────────────────────────────────────

@pytest.fixture
def camtrap_dir(tmp_path: Path) -> Path:
    """Write a minimal CamtrapDP directory to a temp path.

    Layout
    ------
    Sites:   SITE_A (DEP1), SITE_B (DEP2)
    Species: Vulpes vulpes
    Period:  2025-11-01 → 2025-11-10, occasion_days=5

    Occasions:
      occ1 = 2025-11-01 … 2025-11-05
      occ2 = 2025-11-06 … 2025-11-10

    Media / bursts:
      m001, m002 → SITE_A occ1, burst 0 (gap 30 s, same burst)
      m005       → SITE_A occ1, burst 1 (gap 2 h from m002)
      m003       → SITE_A occ2, burst 0
      m004       → SITE_B occ1, burst 0

    Probabilities: m001=0.9, m002=0.8, m005=0.6, m003=0.7, m004=0.85
    Expected ranks for SITE_A occ1: burst0 (max=0.9) → rank 1,
                                     burst1 (max=0.6) → rank 2
    """
    dep = pd.DataFrame({
        "deploymentID":    ["DEP1", "DEP2"],
        "locationID":      ["SITE_A", "SITE_B"],
        "locationName":    ["Site A", "Site B"],
        "deploymentStart": ["2025-11-01", "2025-11-01"],
        "deploymentEnd":   ["2025-11-10", "2025-11-10"],
    })
    med = pd.DataFrame({
        "mediaID":      ["m001", "m002", "m003", "m004", "m005"],
        "deploymentID": ["DEP1", "DEP1", "DEP1", "DEP2", "DEP1"],
        "timestamp": [
            "2025-11-02 10:00:00",   # SITE_A occ1 burst0
            "2025-11-02 10:00:30",   # SITE_A occ1 burst0 (30 s gap)
            "2025-11-07 14:00:00",   # SITE_A occ2 burst0
            "2025-11-03 09:00:00",   # SITE_B occ1 burst0
            "2025-11-02 12:00:00",   # SITE_A occ1 burst1 (2 h gap)
        ],
        "filePath": [f"img/frame{i}.jpg" for i in range(5)],
    })
    obs = pd.DataFrame({
        "observationID":              ["o001", "o002", "o003", "o004", "o005"],
        "deploymentID":               ["DEP1", "DEP1", "DEP1", "DEP2", "DEP1"],
        "mediaID":                    ["m001", "m002", "m003", "m004", "m005"],
        "observationLevel":           ["media"] * 5,
        "observationType":            ["animal"] * 5,
        "scientificName":             ["Vulpes vulpes"] * 5,
        "classificationProbability":  ["0.9", "0.8", "0.7", "0.85", "0.6"],
        "classificationMethod":       ["machine"] * 5,
        "classifiedBy":               ["DeepFaune"] * 5,
        "classificationTimestamp":    [None] * 5,
    })
    dep.to_csv(tmp_path / "deployments.csv", index=False)
    med.to_csv(tmp_path / "media.csv", index=False)
    obs.to_csv(tmp_path / "observations.csv", index=False)
    return tmp_path


@pytest.fixture
def candidates(camtrap_dir: Path) -> pd.DataFrame:
    """Full candidate manifest built from the minimal camtrap_dir fixture."""
    from camtrap_workflow import build_candidates, load_camtrapdp
    dep, med, obs = load_camtrapdp(camtrap_dir)
    return build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
    )


@pytest.fixture
def decisions_dir(tmp_path: Path, candidates: pd.DataFrame) -> Path:
    """Decisions directory with one confirmed key (SITE_A occ1)."""
    from camtrap_workflow import save_decisions
    d = tmp_path / "decisions"
    d.mkdir()
    # Confirm the rank-1 observation for SITE_A_occ1_Vulpes_vulpes
    rank1 = candidates[candidates["rank"] == 1]
    key_a1 = "SITE_A_occ1_Vulpes_vulpes"
    obs_id = rank1[rank1["site_occasion_key"] == key_a1].iloc[0]["observationID"]
    save_decisions(d, candidates, "Vulpes_vulpes", 1, [obs_id])
    return d


@pytest.fixture
def camtrap_dir_with_context(camtrap_dir: Path) -> Path:
    """Extend the minimal CamtrapDP fixture with one media-only entry.

    m006 (DEP1, 2025-11-02 10:00:15) has no observation, so it is not a
    candidate for Vulpes vulpes.  It falls between the two detections of
    burst-0 (m001 at 10:00:00, m002 at 10:00:30), so with
    include_burst_context=True it should appear as a context frame showing
    all frames of the event regardless of species label.
    """
    med = pd.read_csv(camtrap_dir / "media.csv", dtype=str)
    extra = pd.DataFrame({
        "mediaID":      ["m006"],
        "deploymentID": ["DEP1"],
        "timestamp":    ["2025-11-02 10:00:15"],
        "filePath":     ["img/frame_ctx.jpg"],
    })
    pd.concat([med, extra], ignore_index=True).to_csv(
        camtrap_dir / "media.csv", index=False
    )
    return camtrap_dir


@pytest.fixture
def session_config(camtrap_dir: Path, tmp_path: Path) -> dict:
    """Minimal session config dict compatible with build_occupancy_inputs."""
    return {
        "camtrap_dir":    str(camtrap_dir),
        "study_start":    "2025-11-01",
        "study_end":      "2025-11-10",
        "occasion_days":  5,
        "target_species": ["Vulpes vulpes"],
    }
