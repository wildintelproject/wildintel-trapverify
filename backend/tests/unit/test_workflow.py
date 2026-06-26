"""Unit tests for camtrap_workflow.py."""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from camtrap_workflow import (
    _occasion_windows,
    build_candidates,
    build_occupancy_inputs,
    build_review_effort,
    confirmed_keys_set,
    detect_site_col,
    export_verified_camtrapdp,
    get_events,
    get_review_events,
    load_all_decisions,
    load_camtrapdp,
    normalise_ts,
    sanitize,
    save_decisions,
    species_stats,
)


# ─── sanitize ─────────────────────────────────────────────────────────────────

def test_sanitize_spaces():
    assert sanitize("Vulpes vulpes") == "Vulpes_vulpes"

def test_sanitize_special_chars():
    assert sanitize("Sus scrofa (wild)") == "Sus_scrofa__wild_"

def test_sanitize_already_clean():
    assert sanitize("Cervus_elaphus") == "Cervus_elaphus"

def test_sanitize_numbers_preserved():
    assert sanitize("Species2B") == "Species2B"


# ─── normalise_ts ─────────────────────────────────────────────────────────────

def test_normalise_ts_exif():
    assert normalise_ts("2025:11:02 14:30:00") == "2025-11-02 14:30:00"

def test_normalise_ts_iso_passthrough():
    assert normalise_ts("2025-11-02 14:30:00") == "2025-11-02 14:30:00"

def test_normalise_ts_iso_with_T():
    assert normalise_ts("2025-11-02T14:30:00") == "2025-11-02T14:30:00"


# ─── detect_site_col ──────────────────────────────────────────────────────────

def test_detect_site_col_prefers_location_id():
    dep = pd.DataFrame({"deploymentID": ["d1"], "locationID": ["loc1"]})
    assert detect_site_col(dep) == "locationID"

def test_detect_site_col_skips_empty_location_id():
    dep = pd.DataFrame({"deploymentID": ["d1"], "locationID": [""]})
    assert detect_site_col(dep) == "deploymentID"

def test_detect_site_col_skips_null_location_id():
    dep = pd.DataFrame({"deploymentID": ["d1"], "locationID": [None]})
    assert detect_site_col(dep) == "deploymentID"

def test_detect_site_col_no_location_id_column():
    dep = pd.DataFrame({"deploymentID": ["d1"]})
    assert detect_site_col(dep) == "deploymentID"


# ─── load_camtrapdp ───────────────────────────────────────────────────────────

def test_load_camtrapdp_returns_three_dataframes(camtrap_dir):
    dep, med, obs = load_camtrapdp(camtrap_dir)
    assert isinstance(dep, pd.DataFrame)
    assert isinstance(med, pd.DataFrame)
    assert isinstance(obs, pd.DataFrame)

def test_load_camtrapdp_all_string_columns(camtrap_dir):
    dep, med, obs = load_camtrapdp(camtrap_dir)
    assert pd.api.types.is_string_dtype(dep["deploymentID"])
    assert pd.api.types.is_string_dtype(med["mediaID"])
    assert pd.api.types.is_string_dtype(obs["observationID"])

def test_load_camtrapdp_row_counts(camtrap_dir):
    dep, med, obs = load_camtrapdp(camtrap_dir)
    assert len(dep) == 2
    assert len(med) == 5
    assert len(obs) == 5


# ─── build_candidates ─────────────────────────────────────────────────────────

def test_build_candidates_required_columns(candidates):
    expected = {
        "site_occasion_key", "rank", "burst_id", "burst_seq",
        "observationID", "mediaID", "siteID", "occasion",
        "species_safe", "ts", "timestamp_display",
    }
    assert expected.issubset(set(candidates.columns))

def test_build_candidates_unique_site_occasion_keys(candidates):
    # 3 unique cells: SITE_A/occ1, SITE_A/occ2, SITE_B/occ1
    keys = candidates["site_occasion_key"].unique()
    assert len(keys) == 3

def test_build_candidates_species_safe(candidates):
    assert (candidates["species_safe"] == "Vulpes_vulpes").all()

def test_build_candidates_rank1_is_highest_prob(candidates):
    # For SITE_A occ1: burst0 (max=0.9) should be rank 1
    key = "SITE_A_occ1_Vulpes_vulpes"
    cell = candidates[candidates["site_occasion_key"] == key]
    rank1_prob = pd.to_numeric(
        cell[cell["rank"] == 1]["classificationProbability"], errors="coerce"
    ).max()
    rank2_prob = pd.to_numeric(
        cell[cell["rank"] == 2]["classificationProbability"], errors="coerce"
    ).max()
    assert rank1_prob > rank2_prob

def test_build_candidates_two_ranks_for_site_a_occ1(candidates):
    key = "SITE_A_occ1_Vulpes_vulpes"
    ranks = candidates[candidates["site_occasion_key"] == key]["rank"].unique()
    assert set(ranks) == {1, 2}

def test_build_candidates_burst_grouping(candidates):
    # m001 and m002 are 30 s apart → same burst
    key = "SITE_A_occ1_Vulpes_vulpes"
    cell = candidates[candidates["site_occasion_key"] == key]
    burst_of_m001 = cell[cell["mediaID"] == "m001"]["burst_id"].iloc[0]
    burst_of_m002 = cell[cell["mediaID"] == "m002"]["burst_id"].iloc[0]
    burst_of_m005 = cell[cell["mediaID"] == "m005"]["burst_id"].iloc[0]
    assert burst_of_m001 == burst_of_m002
    assert burst_of_m005 != burst_of_m001

def test_build_candidates_occasion_assignment(candidates):
    # m003 at 2025-11-07 must be in occ2 (days 6-10)
    occ = candidates[candidates["mediaID"] == "m003"]["occasion"].iloc[0]
    assert occ == 2

def test_build_candidates_no_match_returns_empty(camtrap_dir):
    dep, med, obs = load_camtrapdp(camtrap_dir)
    result = build_candidates(
        dep, med, obs,
        target_species=["Panthera leo"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
    )
    assert result.empty

def test_build_candidates_outside_period_excluded(camtrap_dir):
    dep, med, obs = load_camtrapdp(camtrap_dir)
    # study_start=2025-11-06 includes only m003 (2025-11-07); m001/m002/m005 are before
    result = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 6),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
    )
    assert set(result["mediaID"].unique()) == {"m003"}


# ─── _occasion_windows ────────────────────────────────────────────────────────

def test_occasion_windows_count():
    windows = _occasion_windows(date(2025, 11, 1), date(2025, 11, 10), 5)
    assert len(windows) == 2

def test_occasion_windows_first_window():
    windows = _occasion_windows(date(2025, 11, 1), date(2025, 11, 10), 5)
    assert windows[0] == (date(2025, 11, 1), date(2025, 11, 5))

def test_occasion_windows_last_clipped():
    windows = _occasion_windows(date(2025, 11, 1), date(2025, 11, 10), 5)
    assert windows[-1][1] == date(2025, 11, 10)

def test_occasion_windows_exact_multiple():
    windows = _occasion_windows(date(2025, 11, 1), date(2025, 11, 15), 5)
    assert len(windows) == 3


# ─── load_all_decisions ───────────────────────────────────────────────────────

def test_load_all_decisions_empty_dir(tmp_path):
    df = load_all_decisions(tmp_path)
    assert df.empty
    assert "observationID" in df.columns

def test_load_all_decisions_concatenates(tmp_path, candidates):
    d = tmp_path / "decisions"
    d.mkdir()
    save_decisions(d, candidates, "Vulpes_vulpes", 1, ["o001"])
    save_decisions(d, candidates, "Vulpes_vulpes", 2, ["o003"])
    df = load_all_decisions(d)
    assert set(df["observationID"]) == {"o001", "o003"}


# ─── confirmed_keys_set ───────────────────────────────────────────────────────

def test_confirmed_keys_set_empty(tmp_path):
    assert confirmed_keys_set(tmp_path) == set()

def test_confirmed_keys_set_returns_correct_keys(tmp_path, candidates):
    save_decisions(tmp_path, candidates, "Vulpes_vulpes", 1, ["o001"])
    keys = confirmed_keys_set(tmp_path)
    assert "SITE_A_occ1_Vulpes_vulpes" in keys


# ─── save_decisions ───────────────────────────────────────────────────────────

def test_save_decisions_writes_file(tmp_path, candidates):
    save_decisions(tmp_path, candidates, "Vulpes_vulpes", 1, ["o001"])
    assert (tmp_path / "decisions_Vulpes_vulpes_iter1.csv").exists()

def test_save_decisions_empty_writes_empty_file(tmp_path, candidates):
    df = save_decisions(tmp_path, candidates, "Vulpes_vulpes", 1, [])
    assert df.empty
    assert (tmp_path / "decisions_Vulpes_vulpes_iter1.csv").exists()

def test_save_decisions_correct_row(tmp_path, candidates):
    save_decisions(tmp_path, candidates, "Vulpes_vulpes", 1, ["o001"])
    df = pd.read_csv(tmp_path / "decisions_Vulpes_vulpes_iter1.csv", dtype=str)
    assert "o001" in df["observationID"].values
    assert "site_occasion_key" in df.columns


# ─── species_stats ────────────────────────────────────────────────────────────

def test_species_stats_no_decisions(tmp_path, candidates):
    d = tmp_path / "decisions"
    d.mkdir()
    stats = species_stats(candidates, d, 100_000)
    assert len(stats) == 1
    sp = stats[0]
    assert sp["species_safe"] == "Vulpes_vulpes"
    assert sp["n_total_combos"] == 3
    assert sp["n_confirmed_combos"] == 0
    assert sp["n_resolved"] == 0

def test_species_stats_with_confirmed(decisions_dir, candidates):
    stats = species_stats(candidates, decisions_dir, 100_000)
    sp = stats[0]
    assert sp["n_confirmed_combos"] == 1
    # After round 1: SITE_A/occ1 confirmed + SITE_A/occ2 and SITE_B/occ1 exhausted
    # (both have max_rank=1 <= rounds_done=1)
    assert sp["n_resolved"] == 3

def test_species_stats_resolved_includes_exhausted(tmp_path, candidates):
    # After 2 rounds, SITE_A/occ1 has max_rank=2 → resolved (exhausted)
    save_decisions(tmp_path, candidates, "Vulpes_vulpes", 1, [])   # round 1, none confirmed
    save_decisions(tmp_path, candidates, "Vulpes_vulpes", 2, [])   # round 2, none confirmed
    stats = species_stats(candidates, tmp_path, 100_000)
    sp = stats[0]
    # SITE_A/occ1 exhausted (max_rank=2, rounds=2), SITE_A/occ2 and SITE_B/occ1 exhausted (max_rank=1, rounds=2)
    assert sp["n_resolved"] == 3


# ─── get_events ───────────────────────────────────────────────────────────────

def test_get_events_round1_returns_three_events(tmp_path, candidates):
    d = tmp_path / "decisions"
    d.mkdir()
    events = get_events(candidates, d, set(), "Vulpes_vulpes", 1)
    assert len(events) == 3

def test_get_events_keys_present(tmp_path, candidates):
    d = tmp_path / "decisions"
    d.mkdir()
    events = get_events(candidates, d, set(), "Vulpes_vulpes", 1)
    keys = {e["key"] for e in events}
    assert "SITE_A_occ1_Vulpes_vulpes" in keys
    assert "SITE_B_occ1_Vulpes_vulpes" in keys

def test_get_events_excludes_confirmed_key(decisions_dir, candidates):
    events = get_events(candidates, decisions_dir, set(), "Vulpes_vulpes", 1)
    keys = {e["key"] for e in events}
    assert "SITE_A_occ1_Vulpes_vulpes" not in keys

def test_get_events_excludes_rejected_media(tmp_path, candidates):
    d = tmp_path / "decisions"
    d.mkdir()
    rejected = {"m004"}   # SITE_B occ1
    events = get_events(candidates, d, rejected, "Vulpes_vulpes", 1)
    keys = {e["key"] for e in events}
    assert "SITE_B_occ1_Vulpes_vulpes" not in keys

def test_get_events_round2_returns_only_rank2(decisions_dir, candidates):
    # After confirming SITE_A/occ1, round 2 should have nothing
    # (remaining cells only have rank 1)
    events = get_events(candidates, decisions_dir, set(), "Vulpes_vulpes", 2)
    assert len(events) == 0

def test_get_events_event_structure(tmp_path, candidates):
    d = tmp_path / "decisions"
    d.mkdir()
    events = get_events(candidates, d, set(), "Vulpes_vulpes", 1)
    ev = events[0]
    for field in ("key", "siteId", "occasion", "rank", "totalSeqs", "repObsId", "maxProb", "frames"):
        assert field in ev
    assert ev["rank"] == 1
    assert len(ev["frames"]) > 0
    frame = ev["frames"][0]
    for field in ("obsId", "mediaId", "img", "ts", "prob"):
        assert field in frame

def test_get_events_total_seqs_correct(tmp_path, candidates):
    d = tmp_path / "decisions"
    d.mkdir()
    events = get_events(candidates, d, set(), "Vulpes_vulpes", 1)
    ev_a1 = next(e for e in events if e["key"] == "SITE_A_occ1_Vulpes_vulpes")
    assert ev_a1["totalSeqs"] == 2   # 2 bursts in this cell


# ─── get_review_events ────────────────────────────────────────────────────────

def test_get_review_events_returns_all_cells(decisions_dir, candidates):
    sp_cands = candidates[candidates["species_safe"] == "Vulpes_vulpes"]
    events = get_review_events(sp_cands, decisions_dir)
    assert len(events) == 3

def test_get_review_events_status_confirmed(decisions_dir, candidates):
    sp_cands = candidates[candidates["species_safe"] == "Vulpes_vulpes"]
    events = get_review_events(sp_cands, decisions_dir)
    ev = next(e for e in events if e["key"] == "SITE_A_occ1_Vulpes_vulpes")
    assert ev["status"] == "confirmed"

def test_get_review_events_status_not_confirmed(decisions_dir, candidates):
    sp_cands = candidates[candidates["species_safe"] == "Vulpes_vulpes"]
    events = get_review_events(sp_cands, decisions_dir)
    ev = next(e for e in events if e["key"] == "SITE_B_occ1_Vulpes_vulpes")
    assert ev["status"] == "not_confirmed"

def test_get_review_events_sorted_by_site_occasion(decisions_dir, candidates):
    sp_cands = candidates[candidates["species_safe"] == "Vulpes_vulpes"]
    events = get_review_events(sp_cands, decisions_dir)
    sites = [e["siteId"] for e in events]
    occasions = [e["occasion"] for e in events]
    assert sites == sorted(sites) or occasions == sorted(occasions)


# ─── export_verified_camtrapdp ────────────────────────────────────────────────

def test_export_copies_deployments_and_media(camtrap_dir, tmp_path, decisions_dir):
    out = tmp_path / "verified"
    export_verified_camtrapdp(camtrap_dir, out, decisions_dir, set())
    assert (out / "deployments.csv").exists()
    assert (out / "media.csv").exists()
    assert (out / "observations.csv").exists()

def test_export_marks_confirmed_as_human(camtrap_dir, tmp_path, decisions_dir, candidates):
    out = tmp_path / "verified"
    export_verified_camtrapdp(camtrap_dir, out, decisions_dir, set())
    obs = pd.read_csv(out / "observations.csv", dtype=str)
    # The confirmed observationID should have classificationMethod='human'
    conf_df = pd.read_csv(decisions_dir / "decisions_Vulpes_vulpes_iter1.csv", dtype=str)
    conf_id = conf_df["observationID"].iloc[0]
    row = obs[obs["observationID"] == conf_id].iloc[0]
    assert row["classificationMethod"] == "human"
    assert row["classificationProbability"] == "1.0"

def test_export_unconfirmed_unchanged(camtrap_dir, tmp_path, decisions_dir):
    out = tmp_path / "verified"
    export_verified_camtrapdp(camtrap_dir, out, decisions_dir, set())
    obs = pd.read_csv(out / "observations.csv", dtype=str)
    # o004 (SITE_B, never confirmed) should keep original method
    row = obs[obs["observationID"] == "o004"].iloc[0]
    assert row["classificationMethod"] == "machine"

def test_export_no_decisions_all_unchanged(camtrap_dir, tmp_path):
    d = tmp_path / "empty_decisions"
    d.mkdir()
    out = tmp_path / "verified"
    export_verified_camtrapdp(camtrap_dir, out, d, set())
    obs_orig = pd.read_csv(camtrap_dir / "observations.csv", dtype=str)
    obs_new  = pd.read_csv(out / "observations.csv", dtype=str)
    assert obs_orig["classificationMethod"].tolist() == obs_new["classificationMethod"].tolist()


# ─── build_occupancy_inputs ───────────────────────────────────────────────────

def test_build_occupancy_inputs_creates_files(candidates, decisions_dir, session_config, tmp_path):
    out = tmp_path / "occ"
    build_occupancy_inputs(candidates, decisions_dir, session_config, out)
    assert (out / "camera_operation.csv").exists()
    assert (out / "dethist_naive_Vulpes_vulpes.csv").exists()
    assert (out / "dethist_verified_Vulpes_vulpes.csv").exists()
    assert (out / "verification_summary.csv").exists()

def test_build_occupancy_inputs_camera_operation_shape(candidates, decisions_dir, session_config, tmp_path):
    out = tmp_path / "occ"
    build_occupancy_inputs(candidates, decisions_dir, session_config, out)
    op = pd.read_csv(out / "camera_operation.csv")
    # 2 sites, 2 occasions → shape (2, 3) including siteID column
    assert op.shape == (2, 3)
    assert "siteID" in op.columns

def test_build_occupancy_inputs_naive_has_detections(candidates, decisions_dir, session_config, tmp_path):
    out = tmp_path / "occ"
    build_occupancy_inputs(candidates, decisions_dir, session_config, out)
    naive = pd.read_csv(out / "dethist_naive_Vulpes_vulpes.csv")
    # All cells have naive detections
    occ_cols = [c for c in naive.columns if c.startswith("occ")]
    values = naive[occ_cols].values.flatten()
    assert 1 in values

def test_build_occupancy_inputs_verified_only_confirmed(candidates, decisions_dir, session_config, tmp_path):
    out = tmp_path / "occ"
    build_occupancy_inputs(candidates, decisions_dir, session_config, out)
    verified = pd.read_csv(out / "dethist_verified_Vulpes_vulpes.csv")
    # Only SITE_A occ1 is confirmed → exactly 1 cell with detection
    occ_cols = [c for c in verified.columns if c.startswith("occ")]
    total_confirmed = (verified[occ_cols] == 1).sum().sum()
    assert total_confirmed == 1


# ─── build_review_effort ──────────────────────────────────────────────────────

def test_build_review_effort_creates_file(candidates, decisions_dir, session_config, tmp_path):
    out = tmp_path / "occ"
    build_review_effort(candidates, decisions_dir, session_config, out)
    assert (out / "review_effort.csv").exists()

def test_build_review_effort_confirmed_count(candidates, decisions_dir, session_config, tmp_path):
    out = tmp_path / "occ"
    build_review_effort(candidates, decisions_dir, session_config, out)
    df = pd.read_csv(out / "review_effort.csv")
    assert int(df["confirmed_cells"].iloc[0]) == 1

def test_build_review_effort_total_cells(candidates, decisions_dir, session_config, tmp_path):
    out = tmp_path / "occ"
    build_review_effort(candidates, decisions_dir, session_config, out)
    df = pd.read_csv(out / "review_effort.csv")
    assert int(df["candidate_cells"].iloc[0]) == 3
