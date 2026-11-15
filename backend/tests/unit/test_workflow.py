"""Unit tests for camtrap_workflow.py."""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from camtrap_workflow import (
    DEEPFAUNE_LABEL_MAP,
    _occasion_windows,
    build_candidates,
    build_occupancy_inputs,
    build_review_effort,
    clear_media_caches,
    confirmed_keys_set,
    deepfaune_to_camtrapdp,
    detect_site_col,
    export_verified_camtrapdp,
    find_datapackage,
    find_flat_search_ambiguities,
    generic_csv_to_camtrapdp,
    get_events,
    get_review_events,
    load_all_decisions,
    load_camtrapdp,
    normalise_ts,
    resolve_camtrapdp_resource,
    resolve_media_path,
    sanitize,
    generate_default_datapackage,
    save_decisions,
    species_stats,
    validate_camtrapdp_datapackage,
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

def test_normalise_ts_strips_colon_utc_offset():
    assert normalise_ts("2025-11-02T14:30:00+01:00") == "2025-11-02T14:30:00"

def test_normalise_ts_strips_compact_utc_offset():
    assert normalise_ts("2025-11-02T14:30:00+0000") == "2025-11-02T14:30:00"

def test_normalise_ts_strips_negative_utc_offset():
    assert normalise_ts("2025-11-02T14:30:00-05:00") == "2025-11-02T14:30:00"

def test_normalise_ts_strips_z_suffix():
    assert normalise_ts("2025-11-02T14:30:00Z") == "2025-11-02T14:30:00"

def test_normalise_ts_exif_with_utc_offset():
    assert normalise_ts("2025:11:02 14:30:00+02:00") == "2025-11-02 14:30:00"

def test_normalise_ts_mixed_offsets_do_not_crash_to_datetime():
    """Regression: a media.csv timestamp column mixing tz-aware and
    tz-naive strings used to crash pandas' to_datetime with "Mixed
    timezones detected" once normalise_ts stopped removing the offset."""
    raw = pd.Series([
        "2025-11-02T14:30:00+01:00",
        "2025-11-02T15:00:00",
        "2025-11-02T15:30:00Z",
        "2025-11-02T16:00:00-03:00",
    ])
    ts = pd.to_datetime(raw.apply(normalise_ts), errors="coerce", utc=False)
    assert ts.notna().all()
    assert ts.dt.tz is None
    assert list(ts.dt.hour) == [14, 15, 15, 16]


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

def test_load_camtrapdp_derives_filename_when_missing(camtrap_dir):
    """The fixture's media.csv has no fileName column; it must be derived
    from the basename of filePath."""
    dep, med, obs = load_camtrapdp(camtrap_dir)
    assert "fileName" in med.columns
    row = med[med["mediaID"] == "m001"].iloc[0]
    assert row["fileName"] == "frame0.jpg"

def test_load_camtrapdp_keeps_existing_filename_column(camtrap_dir):
    med = pd.read_csv(camtrap_dir / "media.csv", dtype=str)
    med["fileName"] = "custom_name.jpg"
    med.to_csv(camtrap_dir / "media.csv", index=False)
    dep, med2, obs = load_camtrapdp(camtrap_dir)
    assert (med2["fileName"] == "custom_name.jpg").all()


# ─── resolve_camtrapdp_resource / find_datapackage ────────────────────────────

def test_resolve_camtrapdp_resource_uses_datapackage_path(tmp_path):
    """A non-conventional resource path declared in datapackage.json (here,
    gzip-compressed under an unrelated file name) wins over the
    ``{name}.csv``/``{name}.csv.gz`` naming convention."""
    pd.DataFrame({"mediaID": ["m1"]}).to_csv(
        tmp_path / "medias_export.csv.gz", index=False, compression="gzip"
    )
    (tmp_path / "datapackage.json").write_text(json.dumps(
        {"resources": [{"name": "media", "path": "medias_export.csv.gz"}]}
    ))
    resolved = resolve_camtrapdp_resource(tmp_path, "media")
    assert resolved == (tmp_path / "medias_export.csv.gz").resolve()

def test_resolve_camtrapdp_resource_relative_to_datapackage_dir(tmp_path):
    """A relative ``path`` in datapackage.json resolves against the
    datapackage.json's own directory, not the ``camtrap_dir`` passed in --
    matters when the package lives one subdir down (Trapper ZIP layout)."""
    sub = tmp_path / "trapper_export"
    (sub / "data").mkdir(parents=True)
    pd.DataFrame({"mediaID": ["m1"]}).to_csv(sub / "data" / "media.csv", index=False)
    (sub / "datapackage.json").write_text(json.dumps(
        {"resources": [{"name": "media", "path": "data/media.csv"}]}
    ))
    resolved = resolve_camtrapdp_resource(tmp_path, "media")
    assert resolved == (sub / "data" / "media.csv").resolve()

def test_resolve_camtrapdp_resource_falls_back_without_datapackage(camtrap_dir):
    resolved = resolve_camtrapdp_resource(camtrap_dir, "media")
    assert resolved == (camtrap_dir / "media.csv").resolve()

def test_resolve_camtrapdp_resource_falls_back_when_declared_path_missing(tmp_path):
    (tmp_path / "datapackage.json").write_text(json.dumps(
        {"resources": [{"name": "media", "path": "does_not_exist.csv"}]}
    ))
    pd.DataFrame({"mediaID": ["m1"]}).to_csv(tmp_path / "media.csv", index=False)
    resolved = resolve_camtrapdp_resource(tmp_path, "media")
    assert resolved == (tmp_path / "media.csv").resolve()

def test_resolve_camtrapdp_resource_missing_entirely_returns_none(tmp_path):
    assert resolve_camtrapdp_resource(tmp_path, "media") is None

def test_find_datapackage_one_subdir_down(tmp_path):
    sub = tmp_path / "trapper_export"
    sub.mkdir()
    (sub / "datapackage.json").write_text("{}")
    assert find_datapackage(tmp_path) == sub / "datapackage.json"

def test_load_camtrapdp_reads_gzip_tables_named_via_datapackage(tmp_path):
    """Regression: a package shipping only .csv.gz tables under non-standard
    names, resolved purely through datapackage.json's resource paths."""
    pd.DataFrame({"deploymentID": ["DEP1"], "locationID": ["SITE_A"]}).to_csv(
        tmp_path / "deployments.csv.gz", index=False, compression="gzip"
    )
    pd.DataFrame({
        "mediaID": ["m1"], "deploymentID": ["DEP1"], "filePath": ["img/f1.jpg"],
    }).to_csv(tmp_path / "medias.csv.gz", index=False, compression="gzip")
    pd.DataFrame({
        "observationID": ["o1"], "mediaID": ["m1"], "scientificName": ["Vulpes vulpes"],
    }).to_csv(tmp_path / "observations.csv.gz", index=False, compression="gzip")
    (tmp_path / "datapackage.json").write_text(json.dumps({"resources": [
        {"name": "deployments", "path": "deployments.csv.gz"},
        {"name": "media", "path": "medias.csv.gz"},
        {"name": "observations", "path": "observations.csv.gz"},
    ]}))
    dep, med, obs = load_camtrapdp(tmp_path)
    assert len(dep) == 1
    assert len(med) == 1
    assert len(obs) == 1


# ─── resolve_media_path ───────────────────────────────────────────────────────

def test_resolve_media_path_structured_takes_precedence(tmp_path):
    (tmp_path / "DEP1").mkdir()
    (tmp_path / "DEP1" / "frame0.jpg").write_bytes(b"x")
    result = resolve_media_path(
        "/nonexistent/frame0.jpg", "DEP1", "frame0.jpg",
        str(tmp_path), tmp_path,
    )
    assert result == tmp_path / "DEP1" / "frame0.jpg"

def test_resolve_media_path_falls_back_when_structured_missing(tmp_path):
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "frame0.jpg").write_bytes(b"x")
    result = resolve_media_path(
        "img/frame0.jpg", "DEP1", "frame0.jpg",
        str(tmp_path), tmp_path,
    )
    assert result == tmp_path / "img" / "frame0.jpg"

def test_resolve_media_path_no_image_base_dir_uses_fallback_base(tmp_path):
    fallback = tmp_path / "elsewhere"
    fallback.mkdir()
    result = resolve_media_path("img/frame0.jpg", "DEP1", "frame0.jpg", "", fallback)
    assert result == (fallback / "img" / "frame0.jpg").resolve()

def test_resolve_media_path_absolute_filepath_without_image_base_dir(tmp_path):
    result = resolve_media_path("/abs/frame0.jpg", "DEP1", "frame0.jpg", "", tmp_path)
    assert result == Path("/abs/frame0.jpg")

def test_resolve_media_path_flat_search_disabled_by_default(tmp_path):
    """Without flat_search, a loose file (no deploymentID subfolder) is not found."""
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "frame0.jpg").write_bytes(b"x")
    result = resolve_media_path(
        "img/frame0.jpg", "DEP1", "frame0.jpg", str(tmp_path), tmp_path,
    )
    assert result != loose / "frame0.jpg"
    assert not result.exists()

def test_resolve_media_path_flat_search_finds_loose_file(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "frame0.jpg").write_bytes(b"x")
    result = resolve_media_path(
        "img/frame0.jpg", "DEP1", "frame0.jpg", str(tmp_path), tmp_path,
        flat_search=True,
    )
    assert result == loose / "frame0.jpg"

def test_resolve_media_path_flat_search_case_insensitive(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "Frame0.JPG").write_bytes(b"x")
    result = resolve_media_path(
        "img/frame0.jpg", "DEP1", "frame0.jpg", str(tmp_path), tmp_path,
        flat_search=True,
    )
    assert result == loose / "Frame0.JPG"

def test_resolve_media_path_flat_search_disambiguates_by_deployment_id(tmp_path):
    (tmp_path / "DEP1").mkdir()
    (tmp_path / "DEP2").mkdir()
    (tmp_path / "DEP1" / "frame0.jpg").write_bytes(b"x")
    (tmp_path / "DEP2" / "frame0.jpg").write_bytes(b"x")
    result = resolve_media_path(
        "img/frame0.jpg", "DEP2", "frame0.jpg", str(tmp_path), tmp_path,
        flat_search=True,
    )
    assert result == tmp_path / "DEP2" / "frame0.jpg"

def test_resolve_media_path_structured_permission_denied_is_treated_as_found(tmp_path, monkeypatch, caplog):
    """A PermissionError while checking the structured path must not be treated as
    "missing": the path is returned as-is, so the real error surfaces later when
    the caller actually tries to read the file."""
    import pathlib
    real_exists = pathlib.Path.exists

    def fake_exists(self):
        if self.name == "frame0.jpg":
            raise PermissionError("denied")
        return real_exists(self)

    monkeypatch.setattr(pathlib.Path, "exists", fake_exists)
    result = resolve_media_path(
        "/nonexistent/frame0.jpg", "DEP1", "frame0.jpg",
        str(tmp_path), tmp_path,
    )
    assert result == tmp_path / "DEP1" / "frame0.jpg"
    assert "Permission denied" in caplog.text


def test_resolve_media_path_flat_search_stale_until_cache_cleared(tmp_path):
    """The flat-search index is cached per image_base_dir and never invalidates
    on its own, so a file added after the first scan won't be found until
    clear_media_caches() runs -- reproducing the "new session, same folder,
    changed files" staleness bug."""
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "frame0.jpg").write_bytes(b"x")
    # Prime the cache with the initial listing.
    resolve_media_path(
        "img/frame0.jpg", "DEP1", "frame0.jpg", str(tmp_path), tmp_path, flat_search=True,
    )
    # A file is added after the index was built -- not yet visible.
    (loose / "frame_new.jpg").write_bytes(b"x")
    result = resolve_media_path(
        "img/frame_new.jpg", "DEP1", "frame_new.jpg", str(tmp_path), tmp_path, flat_search=True,
    )
    assert result != loose / "frame_new.jpg"

    clear_media_caches()
    result = resolve_media_path(
        "img/frame_new.jpg", "DEP1", "frame_new.jpg", str(tmp_path), tmp_path, flat_search=True,
    )
    assert result == loose / "frame_new.jpg"

def test_resolve_media_path_flat_search_still_ambiguous_falls_through(tmp_path, caplog):
    """Same fileName under two folders, neither matching deploymentID: ambiguous,
    logged, and resolution falls through to the fallback rule instead of
    picking one at random."""
    (tmp_path / "OTHER1").mkdir()
    (tmp_path / "OTHER2").mkdir()
    (tmp_path / "OTHER1" / "frame0.jpg").write_bytes(b"x")
    (tmp_path / "OTHER2" / "frame0.jpg").write_bytes(b"x")
    result = resolve_media_path(
        "img/frame0.jpg", "DEP1", "frame0.jpg", str(tmp_path), tmp_path,
        flat_search=True,
    )
    assert result == (tmp_path / "img" / "frame0.jpg").resolve()
    assert "Ambiguous" in caplog.text


# ─── find_flat_search_ambiguities ─────────────────────────────────────────────

def test_find_flat_search_ambiguities_no_image_base_dir_returns_empty():
    med = pd.DataFrame({"mediaID": ["m1"], "deploymentID": ["DEP1"], "fileName": ["frame0.jpg"]})
    assert find_flat_search_ambiguities(med, "") == []

def test_find_flat_search_ambiguities_none_when_structured_resolves(tmp_path):
    (tmp_path / "DEP1").mkdir()
    (tmp_path / "DEP1" / "frame0.jpg").write_bytes(b"x")
    med = pd.DataFrame({"mediaID": ["m1"], "deploymentID": ["DEP1"], "fileName": ["frame0.jpg"]})
    assert find_flat_search_ambiguities(med, str(tmp_path)) == []

def test_find_flat_search_ambiguities_none_when_deployment_disambiguates(tmp_path):
    (tmp_path / "DEP1").mkdir()
    (tmp_path / "DEP2").mkdir()
    (tmp_path / "DEP1" / "frame0.jpg").write_bytes(b"x")
    (tmp_path / "DEP2" / "frame0.jpg").write_bytes(b"x")
    med = pd.DataFrame({"mediaID": ["m1"], "deploymentID": ["DEP2"], "fileName": ["frame0.jpg"]})
    assert find_flat_search_ambiguities(med, str(tmp_path)) == []

def test_find_flat_search_ambiguities_reports_true_ambiguity(tmp_path):
    """Same fileName under two folders, neither matching deploymentID."""
    (tmp_path / "OTHER1").mkdir()
    (tmp_path / "OTHER2").mkdir()
    (tmp_path / "OTHER1" / "frame0.jpg").write_bytes(b"x")
    (tmp_path / "OTHER2" / "frame0.jpg").write_bytes(b"x")
    med = pd.DataFrame({"mediaID": ["m1"], "deploymentID": ["DEP1"], "fileName": ["frame0.jpg"]})
    result = find_flat_search_ambiguities(med, str(tmp_path))
    assert len(result) == 1
    assert result[0]["mediaID"] == "m1"
    assert result[0]["fileName"] == "frame0.jpg"
    assert len(result[0]["candidates"]) == 2


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

def test_build_candidates_same_timestamp_frames_ordered_by_capture_seq(tmp_path):
    """When two frames of the same burst share the exact same timestamp (e.g.
    second-resolution timestamps from some exports), a trailing numeric
    suffix in the file name breaks the tie in true capture order, matching
    the reference R tool -- not the arbitrary order rows happen to appear in
    the source tables."""
    dep = pd.DataFrame({"deploymentID": ["DEP1"], "locationID": ["SITE_A"]})
    med = pd.DataFrame({
        "mediaID":      ["m002", "m001"],  # deliberately fed out of capture order
        "deploymentID": ["DEP1", "DEP1"],
        "timestamp":    ["2025-11-02 10:00:00", "2025-11-02 10:00:00"],
        "filePath":     ["img/frame_2.jpg", "img/frame_1.jpg"],
    })
    obs = pd.DataFrame({
        "observationID":             ["o002", "o001"],
        "deploymentID":              ["DEP1", "DEP1"],
        "mediaID":                   ["m002", "m001"],
        "observationLevel":          ["media", "media"],
        "observationType":           ["animal", "animal"],
        "scientificName":            ["Vulpes vulpes", "Vulpes vulpes"],
        "classificationProbability": [0.9, 0.5],
    })
    result = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
    )
    ordered = result.sort_values("burst_seq")
    assert list(ordered["mediaID"]) == ["m001", "m002"]

def test_build_candidates_occasion_assignment(candidates):
    # m003 at 2025-11-07 must be in occ2 (days 6-10)
    occ = candidates[candidates["mediaID"] == "m003"]["occasion"].iloc[0]
    assert occ == 2

def test_build_candidates_collapses_duplicate_bounding_boxes(camtrap_dir):
    """Two observation rows for the same (mediaID, scientificName) -- e.g. two
    bounding boxes for the same species in one frame -- must collapse to a
    single candidate keeping the highest-probability observationID."""
    obs = pd.read_csv(camtrap_dir / "observations.csv", dtype=str)
    dup = obs[obs["mediaID"] == "m001"].copy()
    dup["observationID"] = "o001b"
    dup["classificationProbability"] = "0.3"  # lower than o001's 0.9
    pd.concat([obs, dup], ignore_index=True).to_csv(
        camtrap_dir / "observations.csv", index=False
    )

    dep, med, obs2 = load_camtrapdp(camtrap_dir)
    result = build_candidates(
        dep, med, obs2,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
    )
    m001_rows = result[result["mediaID"] == "m001"]
    assert len(m001_rows) == 1
    assert m001_rows.iloc[0]["observationID"] == "o001"  # the higher-probability one

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

def test_build_candidates_min_score_drops_low_confidence_frames(camtrap_dir):
    """Frames whose own classification probability is below min_score are
    demoted (excluded), mirroring to_camtrapdp()'s per-frame threshold."""
    dep, med, obs = load_camtrapdp(camtrap_dir)
    result = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        min_score=0.75,
    )
    # m005 (0.6) and m003 (0.7) individually fall below 0.75
    assert "m005" not in set(result["mediaID"])
    assert "m003" not in set(result["mediaID"])
    # m001 (0.9), m002 (0.8) and m004 (0.85) individually meet the threshold
    assert {"m001", "m002", "m004"} <= set(result["mediaID"])

def test_build_candidates_min_score_demotes_frame_even_within_qualifying_burst(camtrap_dir):
    """The threshold applies per frame, not per burst: a frame below min_score
    is demoted even when another frame in the same burst clears it."""
    dep, med, obs = load_camtrapdp(camtrap_dir)
    result = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        min_score=0.85,
    )
    # burst0: m001=0.9 clears 0.85 and stays; m002=0.8 does not and is demoted,
    # even though both frames belong to the same burst.
    assert "m001" in set(result["mediaID"])
    assert "m002" not in set(result["mediaID"])

def test_build_candidates_min_score_never_demotes_unscored_frames(tmp_path):
    """A frame with no classification score at all must not be demoted, even
    with min_score set -- only a known low score excludes it (mirrors
    to_camtrapdp()'s `!is.na(scores) &` guard)."""
    dep = pd.DataFrame({"deploymentID": ["DEP1"], "locationID": ["SITE_A"]})
    med = pd.DataFrame({
        "mediaID": ["m001"], "deploymentID": ["DEP1"],
        "timestamp": ["2025-11-02 10:00:00"], "filePath": ["img/frame0.jpg"],
    })
    obs = pd.DataFrame({
        "observationID": ["o001"], "deploymentID": ["DEP1"], "mediaID": ["m001"],
        "observationLevel": ["media"], "observationType": ["animal"],
        "scientificName": ["Vulpes vulpes"], "classificationProbability": [None],
    })
    result = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        min_score=0.95,
    )
    assert "m001" in set(result["mediaID"])

def test_build_candidates_min_score_all_below_returns_empty(camtrap_dir):
    dep, med, obs = load_camtrapdp(camtrap_dir)
    result = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        min_score=0.99,
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


# ─── validate_camtrapdp_datapackage ───────────────────────────────────────────

def _write_datapackage(tmp_path: Path, deployments_required: bool) -> Path:
    (tmp_path / "deployments.csv").write_text(
        "deploymentID,latitude\nDEP1,40.5\n" if deployments_required else "deploymentID,latitude\nDEP1,\n"
    )
    schema = {
        "fields": [
            {"name": "deploymentID", "type": "string", "constraints": {"required": True}},
            {"name": "latitude", "type": "number", "constraints": {"required": True}},
        ]
    }
    dp_path = tmp_path / "datapackage.json"
    dp_path.write_text(json.dumps({
        "name": "test-package",
        "resources": [
            {"name": "deployments", "path": "deployments.csv", "profile": "tabular-data-resource", "schema": schema},
        ],
    }))
    return dp_path

def test_validate_camtrapdp_datapackage_valid(tmp_path):
    dp_path = _write_datapackage(tmp_path, deployments_required=True)
    assert validate_camtrapdp_datapackage(dp_path) == []

def test_validate_camtrapdp_datapackage_reports_errors(tmp_path):
    dp_path = _write_datapackage(tmp_path, deployments_required=False)
    errors = validate_camtrapdp_datapackage(dp_path)
    assert errors
    assert any("latitude" in e for e in errors)

def test_validate_camtrapdp_datapackage_malformed_json(tmp_path):
    dp_path = tmp_path / "datapackage.json"
    dp_path.write_text("{ not valid json")
    errors = validate_camtrapdp_datapackage(dp_path)
    assert errors


# ─── generate_default_datapackage ─────────────────────────────────────────────

def test_generate_default_datapackage_derives_taxonomic_and_temporal(camtrap_dir):
    dep, med, obs = load_camtrapdp(camtrap_dir)
    dp = generate_default_datapackage(dep, med, obs)
    assert dp["taxonomic"] == [{"scientificName": "Vulpes vulpes"}]
    assert dp["temporal"]["start"] and dp["temporal"]["end"]
    fabricated = dp["wildintelGenerated"]["fabricatedFields"]
    assert "taxonomic" not in fabricated
    assert "temporal" not in fabricated

def test_generate_default_datapackage_derives_observation_level(camtrap_dir):
    """The fixture's observations.csv uses a single 'media' value throughout."""
    dep, med, obs = load_camtrapdp(camtrap_dir)
    dp = generate_default_datapackage(dep, med, obs)
    assert dp["project"]["observationLevel"] == ["media"]
    assert "project.observationLevel" not in dp["wildintelGenerated"]["fabricatedFields"]

def test_generate_default_datapackage_fabricates_spatial_without_coordinates(camtrap_dir):
    """The fixture's deployments.csv has no latitude/longitude columns."""
    dep, med, obs = load_camtrapdp(camtrap_dir)
    dp = generate_default_datapackage(dep, med, obs)
    assert "spatial" in dp["wildintelGenerated"]["fabricatedFields"]

def test_generate_default_datapackage_derives_spatial_with_coordinates(camtrap_dir):
    dep, med, obs = load_camtrapdp(camtrap_dir)
    dep["latitude"] = ["40.0", "41.0"]
    dep["longitude"] = ["-3.0", "-2.0"]
    dp = generate_default_datapackage(dep, med, obs)
    assert "spatial" not in dp["wildintelGenerated"]["fabricatedFields"]
    assert dp["spatial"]["type"] == "Polygon"

def test_generate_default_datapackage_always_fabricates_project_metadata(camtrap_dir):
    dep, med, obs = load_camtrapdp(camtrap_dir)
    fabricated = generate_default_datapackage(dep, med, obs)["wildintelGenerated"]["fabricatedFields"]
    for key in ("contributors", "project.title", "project.samplingDesign",
                "project.captureMethod", "project.individualAnimals"):
        assert key in fabricated


# ─── export_verified_camtrapdp ────────────────────────────────────────────────

def test_export_copies_deployments_and_media(camtrap_dir, tmp_path, decisions_dir):
    out = tmp_path / "verified"
    export_verified_camtrapdp(camtrap_dir, out, decisions_dir, set())
    assert (out / "deployments.csv").exists()
    assert (out / "media.csv").exists()
    assert (out / "observations.csv").exists()

def test_export_copies_datapackage_json_when_present(camtrap_dir, tmp_path, decisions_dir):
    (camtrap_dir / "datapackage.json").write_text('{"name": "test"}')
    out = tmp_path / "verified"
    export_verified_camtrapdp(camtrap_dir, out, decisions_dir, set())
    assert (out / "datapackage.json").read_text() == '{"name": "test"}'

def test_export_generates_default_datapackage_when_absent(camtrap_dir, tmp_path, decisions_dir):
    out = tmp_path / "verified"
    export_verified_camtrapdp(camtrap_dir, out, decisions_dir, set())
    dp = json.loads((out / "datapackage.json").read_text())
    assert dp["wildintelGenerated"]["generated"] is True
    assert "Vulpes vulpes" in [t["scientificName"] for t in dp["taxonomic"]]

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

# ─── classified_by parameter ──────────────────────────────────────────────────

def test_export_default_classified_by_is_expert_review(camtrap_dir, tmp_path, decisions_dir):
    out = tmp_path / "verified"
    export_verified_camtrapdp(camtrap_dir, out, decisions_dir, set())
    obs = pd.read_csv(out / "observations.csv", dtype=str)
    conf_id = pd.read_csv(decisions_dir / "decisions_Vulpes_vulpes_iter1.csv", dtype=str)["observationID"].iloc[0]
    assert obs[obs["observationID"] == conf_id].iloc[0]["classifiedBy"] == "expert_review"

def test_export_custom_classified_by(camtrap_dir, tmp_path, decisions_dir):
    out = tmp_path / "verified"
    export_verified_camtrapdp(camtrap_dir, out, decisions_dir, set(), classified_by_label="wildlife_expert")
    obs = pd.read_csv(out / "observations.csv", dtype=str)
    conf_id = pd.read_csv(decisions_dir / "decisions_Vulpes_vulpes_iter1.csv", dtype=str)["observationID"].iloc[0]
    assert obs[obs["observationID"] == conf_id].iloc[0]["classifiedBy"] == "wildlife_expert"

def test_export_classified_by_does_not_affect_unconfirmed(camtrap_dir, tmp_path, decisions_dir):
    out = tmp_path / "verified"
    export_verified_camtrapdp(camtrap_dir, out, decisions_dir, set(), classified_by_label="my_label")
    obs = pd.read_csv(out / "observations.csv", dtype=str)
    # o004 is SITE_B, never confirmed — classifiedBy must remain the original value
    row = obs[obs["observationID"] == "o004"].iloc[0]
    assert row["classifiedBy"] == "DeepFaune"

# ─── extended_confirmation parameter ─────────────────────────────────────────

def test_export_extended_false_marks_only_rep(camtrap_dir, tmp_path, decisions_dir, candidates):
    """Default (extended=False) marks only the representative observation."""
    out = tmp_path / "verified"
    export_verified_camtrapdp(
        camtrap_dir, out, decisions_dir, set(),
        extended_confirmation=False, candidates=candidates,
    )
    obs = pd.read_csv(out / "observations.csv", dtype=str)
    assert (obs["classificationMethod"] == "human").sum() == 1

def test_export_extended_true_marks_all_burst_mates(camtrap_dir, tmp_path, decisions_dir, candidates):
    """With extended=True, every obs in the confirmed burst is marked.

    burst0 of SITE_A/occ1 has m001 (o001, 0.9, rep) and m002 (o002, 0.8).
    Confirming the rep must also mark o002.
    """
    out = tmp_path / "verified"
    export_verified_camtrapdp(
        camtrap_dir, out, decisions_dir, set(),
        extended_confirmation=True, candidates=candidates,
    )
    obs = pd.read_csv(out / "observations.csv", dtype=str)
    human_rows = obs[obs["classificationMethod"] == "human"]
    assert len(human_rows) == 2
    assert set(human_rows["observationID"]) == {"o001", "o002"}

def test_export_extended_true_does_not_mark_other_bursts(camtrap_dir, tmp_path, decisions_dir, candidates):
    """Extended confirmation must not spill into other bursts or sites."""
    out = tmp_path / "verified"
    export_verified_camtrapdp(
        camtrap_dir, out, decisions_dir, set(),
        extended_confirmation=True, candidates=candidates,
    )
    obs = pd.read_csv(out / "observations.csv", dtype=str)
    # o003 (SITE_A occ2), o004 (SITE_B occ1), o005 (SITE_A occ1 burst1) are NOT confirmed
    for oid in ["o003", "o004", "o005"]:
        row = obs[obs["observationID"] == oid].iloc[0]
        assert row["classificationMethod"] == "machine", f"{oid} should remain machine"

def test_export_extended_true_without_candidates_fallback(camtrap_dir, tmp_path, decisions_dir):
    """extended=True with candidates=None gracefully falls back to rep-only behaviour."""
    out = tmp_path / "verified"
    export_verified_camtrapdp(
        camtrap_dir, out, decisions_dir, set(),
        extended_confirmation=True, candidates=None,
    )
    obs = pd.read_csv(out / "observations.csv", dtype=str)
    assert (obs["classificationMethod"] == "human").sum() == 1

def test_export_confirms_duplicate_bounding_box_siblings(camtrap_dir, tmp_path, decisions_dir):
    """A confirmed representative's sibling rows -- same (mediaID,
    scientificName), a different observationID -- must also be marked
    human-confirmed, even though build_candidates() only ever surfaces the
    representative for review."""
    obs = pd.read_csv(camtrap_dir / "observations.csv", dtype=str)
    dup = obs[obs["observationID"] == "o001"].copy()  # confirmed rep's mediaID
    dup["observationID"] = "o001b"
    dup["classificationProbability"] = "0.3"
    pd.concat([obs, dup], ignore_index=True).to_csv(
        camtrap_dir / "observations.csv", index=False
    )

    out = tmp_path / "verified"
    export_verified_camtrapdp(camtrap_dir, out, decisions_dir, set())

    result = pd.read_csv(out / "observations.csv", dtype=str)
    sibling = result[result["observationID"] == "o001b"].iloc[0]
    assert sibling["classificationMethod"] == "human"


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

def test_build_occupancy_inputs_includes_classified_site_with_no_detections(
    candidates, decisions_dir, session_config, camtrap_dir, tmp_path,
):
    """A camera that was classified but never detected the target is a true
    zero, not an exclusion. Adding SITE_C (no observations at all) to
    deployments.csv must not drop it from the site universe."""
    dep = pd.read_csv(camtrap_dir / "deployments.csv", dtype=str)
    dep = pd.concat([dep, pd.DataFrame({
        "deploymentID":    ["DEP3"],
        "locationID":      ["SITE_C"],
        "locationName":    ["Site C"],
        "deploymentStart": ["2025-11-01"],
        "deploymentEnd":   ["2025-11-10"],
    })], ignore_index=True)
    dep.to_csv(camtrap_dir / "deployments.csv", index=False)

    out = tmp_path / "occ"
    build_occupancy_inputs(candidates, decisions_dir, session_config, out)

    op = pd.read_csv(out / "camera_operation.csv")
    assert "SITE_C" in set(op["siteID"])
    occ_cols = [c for c in op.columns if c.startswith("occ")]
    site_c_op = op.loc[op["siteID"] == "SITE_C", occ_cols].iloc[0]
    assert (site_c_op > 0).all()  # active the whole period, per deploymentStart/End

    naive = pd.read_csv(out / "dethist_naive_Vulpes_vulpes.csv")
    site_c_row = naive.loc[naive["siteID"] == "SITE_C", occ_cols].iloc[0]
    assert (site_c_row == 0).all()  # classified, active, no detections -> true zero


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


# ─── DEEPFAUNE_LABEL_MAP ──────────────────────────────────────────────────────

def test_label_map_is_lowercase():
    assert all(k == k.lower() for k in DEEPFAUNE_LABEL_MAP)

def test_label_map_values_are_scientific_names():
    for sci in DEEPFAUNE_LABEL_MAP.values():
        parts = sci.split()
        assert len(parts) >= 1
        assert parts[0][0].isupper(), f"Expected capitalised genus in '{sci}'"

def test_label_map_contains_common_species():
    assert "red deer" in DEEPFAUNE_LABEL_MAP
    assert "wild boar" in DEEPFAUNE_LABEL_MAP
    assert "fox" in DEEPFAUNE_LABEL_MAP
    assert DEEPFAUNE_LABEL_MAP["red deer"] == "Cervus elaphus"
    assert DEEPFAUNE_LABEL_MAP["wild boar"] == "Sus scrofa"


# ─── deepfaune_to_camtrapdp ───────────────────────────────────────────────────

def _minimal_deepfaune_df() -> pd.DataFrame:
    return pd.DataFrame({
        "filename": ["/imgs/SITE_A/frame1.jpg", "/imgs/SITE_A/frame2.jpg"],
        "date":     ["2025-11-02 10:00:00",    "2025-11-02 10:00:30"],
        "top1":     ["red deer",                "empty"],
        "score":    ["0.92",                    "0.10"],
        "site":     ["SITE_A",                  "SITE_A"],
    })

def test_deepfaune_creates_three_files(tmp_path):
    out = deepfaune_to_camtrapdp(_minimal_deepfaune_df(), DEEPFAUNE_LABEL_MAP, tmp_path / "out")
    assert (out / "deployments.csv").exists()
    assert (out / "media.csv").exists()
    assert (out / "observations.csv").exists()

def test_deepfaune_maps_species_name(tmp_path):
    out = deepfaune_to_camtrapdp(_minimal_deepfaune_df(), DEEPFAUNE_LABEL_MAP, tmp_path / "out")
    obs = pd.read_csv(out / "observations.csv")
    animal_row = obs[obs["observationType"] == "animal"]
    assert animal_row.iloc[0]["scientificName"] == "Cervus elaphus"

def test_deepfaune_non_animal_label_blank(tmp_path):
    out = deepfaune_to_camtrapdp(_minimal_deepfaune_df(), DEEPFAUNE_LABEL_MAP, tmp_path / "out")
    obs = pd.read_csv(out / "observations.csv")
    blank_row = obs[obs["observationType"] == "blank"]
    assert not blank_row.empty
    assert pd.isna(blank_row.iloc[0]["scientificName"])

def test_deepfaune_below_min_score_gets_null_name(tmp_path):
    df = _minimal_deepfaune_df()
    df.loc[0, "score"] = "0.3"
    out = deepfaune_to_camtrapdp(df, DEEPFAUNE_LABEL_MAP, tmp_path / "out", min_score=0.5)
    obs = pd.read_csv(out / "observations.csv")
    animal_row = obs[obs["observationType"] == "animal"]
    assert pd.isna(animal_row.iloc[0]["scientificName"])

def test_deepfaune_above_min_score_keeps_name(tmp_path):
    df = _minimal_deepfaune_df()
    out = deepfaune_to_camtrapdp(df, DEEPFAUNE_LABEL_MAP, tmp_path / "out", min_score=0.5)
    obs = pd.read_csv(out / "observations.csv")
    animal_row = obs[obs["observationType"] == "animal"]
    assert animal_row.iloc[0]["scientificName"] == "Cervus elaphus"

def test_deepfaune_custom_score_col_is_read(tmp_path):
    """score_col must be configurable, not hardcoded to 'score' -- a caller
    using the old DeepFaune column names (predictionbase/scorebase) directly,
    without going through the API router's rename workaround, must still get
    a real classificationProbability instead of a silent NaN."""
    df = _minimal_deepfaune_df().rename(columns={"top1": "predictionbase", "score": "scorebase"})
    out = deepfaune_to_camtrapdp(
        df, DEEPFAUNE_LABEL_MAP, tmp_path / "out",
        label_col="predictionbase", score_col="scorebase",
    )
    obs = pd.read_csv(out / "observations.csv")
    animal_row = obs[obs["observationType"] == "animal"]
    assert animal_row.iloc[0]["classificationProbability"] == pytest.approx(0.92)

def test_deepfaune_derives_site_from_path_when_no_site_col(tmp_path):
    df = _minimal_deepfaune_df().drop(columns=["site"])
    out = deepfaune_to_camtrapdp(df, DEEPFAUNE_LABEL_MAP, tmp_path / "out")
    dep = pd.read_csv(out / "deployments.csv")
    assert "SITE_A" in dep["deploymentID"].values

def test_deepfaune_detects_predictionbase_format(tmp_path):
    df = pd.DataFrame({
        "filename":        ["/imgs/SITE_A/frame1.jpg"],
        "date":            ["2025-11-02 10:00:00"],
        "predictionbase":  ["roe deer"],
        "scorebase":       ["0.88"],
        "site":            ["SITE_A"],
    })
    # predictionbase is not in the default DEEPFAUNE_LABEL_MAP but converter
    # should still run; "roe deer" maps to Capreolus capreolus
    out = deepfaune_to_camtrapdp(
        df.rename(columns={"predictionbase": "top1", "scorebase": "score"}),
        DEEPFAUNE_LABEL_MAP,
        tmp_path / "out",
        label_col="top1",
    )
    obs = pd.read_csv(out / "observations.csv")
    assert obs.iloc[0]["scientificName"] == "Capreolus capreolus"

def test_deepfaune_filepath_written_as_is(tmp_path):
    """filePath is no longer resolved/made absolute here -- locating the
    files is resolve_media_path()'s job at review time, via image_base_dir,
    same as a plain CamtrapDP directory (see gallery_frame_img_url)."""
    df = pd.DataFrame({
        "filename": ["relative/frame.jpg"],
        "date":     ["2025-11-02 10:00:00"],
        "top1":     ["fox"],
        "score":    ["0.9"],
        "site":     ["S1"],
    })
    out = deepfaune_to_camtrapdp(df, DEEPFAUNE_LABEL_MAP, tmp_path / "out")
    med = pd.read_csv(out / "media.csv")
    assert med.iloc[0]["filePath"] == "relative/frame.jpg"

def test_deepfaune_writes_file_name_column(tmp_path):
    df = pd.DataFrame({
        "filename": ["relative/dir/frame.jpg"],
        "date":     ["2025-11-02 10:00:00"],
        "top1":     ["fox"],
        "score":    ["0.9"],
        "site":     ["S1"],
    })
    out = deepfaune_to_camtrapdp(df, DEEPFAUNE_LABEL_MAP, tmp_path / "out")
    med = pd.read_csv(out / "media.csv")
    assert med.iloc[0]["fileName"] == "frame.jpg"

def test_deepfaune_row_count_matches_input(tmp_path):
    out = deepfaune_to_camtrapdp(_minimal_deepfaune_df(), DEEPFAUNE_LABEL_MAP, tmp_path / "out")
    obs = pd.read_csv(out / "observations.csv")
    assert len(obs) == 2


# ─── generic_csv_to_camtrapdp ─────────────────────────────────────────────────
# DeepFaune is really just a fixed-column-mapping case of this same converter
# -- same expectations apply: filePath unresolved, fileName written.

def _minimal_custom_df() -> pd.DataFrame:
    return pd.DataFrame({
        "path":  ["relative/dir/frame1.jpg", "relative/dir/frame2.jpg"],
        "when":  ["2025-11-02 10:00:00", "2025-11-02 10:00:30"],
        "class": ["red deer", "empty"],
        "conf":  ["0.92", "0.10"],
        "loc":   ["SITE_A", "SITE_A"],
    })

def test_generic_csv_creates_three_files(tmp_path):
    out = generic_csv_to_camtrapdp(
        _minimal_custom_df(), tmp_path / "out",
        col_filename="path", col_datetime="when", col_label="class",
        col_score="conf", col_site="loc",
    )
    assert (out / "deployments.csv").exists()
    assert (out / "media.csv").exists()
    assert (out / "observations.csv").exists()

def test_generic_csv_filepath_written_as_is(tmp_path):
    out = generic_csv_to_camtrapdp(
        _minimal_custom_df(), tmp_path / "out",
        col_filename="path", col_datetime="when", col_label="class",
        col_score="conf", col_site="loc",
    )
    med = pd.read_csv(out / "media.csv")
    assert med.iloc[0]["filePath"] == "relative/dir/frame1.jpg"

def test_generic_csv_writes_file_name_column(tmp_path):
    out = generic_csv_to_camtrapdp(
        _minimal_custom_df(), tmp_path / "out",
        col_filename="path", col_datetime="when", col_label="class",
        col_score="conf", col_site="loc",
    )
    med = pd.read_csv(out / "media.csv")
    assert med.iloc[0]["fileName"] == "frame1.jpg"

def test_generic_csv_maps_species_via_species_map(tmp_path):
    out = generic_csv_to_camtrapdp(
        _minimal_custom_df(), tmp_path / "out",
        col_filename="path", col_datetime="when", col_label="class",
        col_score="conf", col_site="loc",
        species_map={"red deer": "Cervus elaphus"},
    )
    obs = pd.read_csv(out / "observations.csv")
    animal_row = obs[obs["observationType"] == "animal"]
    assert animal_row.iloc[0]["scientificName"] == "Cervus elaphus"

def test_generic_csv_non_animal_label_blank(tmp_path):
    out = generic_csv_to_camtrapdp(
        _minimal_custom_df(), tmp_path / "out",
        col_filename="path", col_datetime="when", col_label="class",
        col_score="conf", col_site="loc",
    )
    obs = pd.read_csv(out / "observations.csv")
    blank_row = obs[obs["observationType"] == "blank"]
    assert not blank_row.empty
    assert pd.isna(blank_row.iloc[0]["scientificName"])

def test_generic_csv_derives_site_from_path_when_no_col_site(tmp_path):
    df = _minimal_custom_df().drop(columns=["loc"])
    out = generic_csv_to_camtrapdp(
        df, tmp_path / "out",
        col_filename="path", col_datetime="when", col_label="class",
        col_score="conf",
    )
    dep = pd.read_csv(out / "deployments.csv")
    assert "dir" in dep["deploymentID"].values


# ─── build_candidates: burst context ─────────────────────────────────────────

def test_burst_context_is_context_column_present(candidates):
    assert "is_context" in candidates.columns

def test_burst_context_false_all_false(candidates):
    assert (candidates["is_context"] == False).all()  # noqa: E712

def test_burst_context_single_detection_burst_still_gets_context(camtrap_dir: Path):
    """A burst with a single target detection (min == max timestamp) must not
    collapse to a zero-width window: a neighbouring frame within gap_seconds
    of that lone detection is still picked up as context. This is the
    dominant real-world case (only one frame of a trigger sequence gets a
    positive species classification)."""
    med = pd.read_csv(camtrap_dir / "media.csv", dtype=str)
    # m005 (SITE_A occ1 burst1) is alone at 2025-11-02 12:00:00 -- add a
    # neighbour 20 s later, well within gap_seconds=60.
    extra = pd.DataFrame({
        "mediaID":      ["m_neighbor"],
        "deploymentID": ["DEP1"],
        "timestamp":    ["2025-11-02 12:00:20"],
        "filePath":     ["img/neighbor.jpg"],
    })
    pd.concat([med, extra], ignore_index=True).to_csv(
        camtrap_dir / "media.csv", index=False
    )
    dep, med2, obs = load_camtrapdp(camtrap_dir)
    cands = build_candidates(
        dep, med2, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    m005_burst_id = cands.loc[cands["mediaID"] == "m005", "burst_id"].iloc[0]
    ctx_ids = set(
        cands[(cands["is_context"] == True) & (cands["burst_id"] == m005_burst_id)]  # noqa: E712
        ["mediaID"]
    )
    assert "m_neighbor" in ctx_ids

def test_burst_context_adds_context_rows(camtrap_dir_with_context):
    dep, med, obs = load_camtrapdp(camtrap_dir_with_context)
    cands = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    ctx = cands[cands["is_context"] == True]  # noqa: E712
    assert not ctx.empty

def test_burst_context_obs_id_prefixed_ctx(camtrap_dir_with_context):
    dep, med, obs = load_camtrapdp(camtrap_dir_with_context)
    cands = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    ctx = cands[cands["is_context"] == True]  # noqa: E712
    assert all(str(oid).startswith("ctx_") for oid in ctx["observationID"])

def test_burst_context_prob_is_null(camtrap_dir_with_context):
    dep, med, obs = load_camtrapdp(camtrap_dir_with_context)
    cands = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    ctx = cands[cands["is_context"] == True]  # noqa: E712
    assert ctx["classificationProbability"].isna().all()

def test_burst_context_non_context_rows_unchanged(camtrap_dir_with_context):
    dep, med, obs = load_camtrapdp(camtrap_dir_with_context)
    cands = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    non_ctx = cands[cands["is_context"] == False]  # noqa: E712
    assert set(non_ctx["mediaID"]) == {"m001", "m002", "m003", "m004", "m005"}

def test_burst_context_does_not_duplicate_candidates(camtrap_dir_with_context):
    dep, med, obs = load_camtrapdp(camtrap_dir_with_context)
    cands = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    non_ctx = cands[cands["is_context"] == False]  # noqa: E712
    assert non_ctx["mediaID"].duplicated().sum() == 0


# ─── get_events: context frames ───────────────────────────────────────────────

def test_get_events_context_frame_is_context_true(camtrap_dir_with_context, tmp_path):
    dep, med, obs = load_camtrapdp(camtrap_dir_with_context)
    cands = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    decisions = tmp_path / "dec"
    decisions.mkdir()
    events = get_events(cands, decisions, set(), "Vulpes_vulpes", iteration=1)
    ctx_frames = [
        f for ev in events for f in ev["frames"] if f.get("isContext")
    ]
    assert len(ctx_frames) > 0

def test_get_events_context_frame_prob_none(camtrap_dir_with_context, tmp_path):
    dep, med, obs = load_camtrapdp(camtrap_dir_with_context)
    cands = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    decisions = tmp_path / "dec"
    decisions.mkdir()
    events = get_events(cands, decisions, set(), "Vulpes_vulpes", iteration=1)
    ctx_frames = [
        f for ev in events for f in ev["frames"] if f.get("isContext")
    ]
    assert all(f["prob"] is None for f in ctx_frames)

def test_get_events_rep_obs_id_not_context(camtrap_dir_with_context, tmp_path):
    dep, med, obs = load_camtrapdp(camtrap_dir_with_context)
    cands = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    decisions = tmp_path / "dec"
    decisions.mkdir()
    events = get_events(cands, decisions, set(), "Vulpes_vulpes", iteration=1)
    for ev in events:
        assert not str(ev["repObsId"]).startswith("ctx_")

def test_get_events_max_prob_from_non_context(camtrap_dir_with_context, tmp_path):
    dep, med, obs = load_camtrapdp(camtrap_dir_with_context)
    cands = build_candidates(
        dep, med, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    decisions = tmp_path / "dec"
    decisions.mkdir()
    events = get_events(cands, decisions, set(), "Vulpes_vulpes", iteration=1)
    for ev in events:
        assert ev["maxProb"] > 0


# ─── build_candidates: burst context boundary ─────────────────────────────────

def test_burst_context_pads_window_by_gap_seconds(camtrap_dir: Path):
    """A frame within gap_seconds of the burst's first detection IS included as
    context -- the window is padded by gap_seconds on each side (matching the
    reference R tool), not clipped exactly to [t_min, t_max]. Otherwise a burst
    with a single detection would get a zero-width window and never show any
    context at all."""
    med = pd.read_csv(camtrap_dir / "media.csv", dtype=str)
    # 30 s before the burst's first detection (10:00:00) -- within gap_seconds=60.
    extra = pd.DataFrame({
        "mediaID":      ["m_before"],
        "deploymentID": ["DEP1"],
        "timestamp":    ["2025-11-02 09:59:30"],
        "filePath":     ["img/before.jpg"],
    })
    pd.concat([med, extra], ignore_index=True).to_csv(
        camtrap_dir / "media.csv", index=False
    )
    dep, med2, obs = load_camtrapdp(camtrap_dir)
    cands = build_candidates(
        dep, med2, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    ctx_ids = set(cands[cands["is_context"] == True]["mediaID"])  # noqa: E712
    assert "m_before" in ctx_ids

def test_burst_context_excludes_frames_beyond_gap_seconds(camtrap_dir: Path):
    """A frame further than gap_seconds from the burst boundary must still be
    excluded -- e.g. a frame from an adjacent, unrelated visit."""
    med = pd.read_csv(camtrap_dir / "media.csv", dtype=str)
    # 5 minutes before the burst's first detection (10:00:00) -- well beyond gap_seconds=60.
    extra = pd.DataFrame({
        "mediaID":      ["m_far_before"],
        "deploymentID": ["DEP1"],
        "timestamp":    ["2025-11-02 09:55:00"],
        "filePath":     ["img/far_before.jpg"],
    })
    pd.concat([med, extra], ignore_index=True).to_csv(
        camtrap_dir / "media.csv", index=False
    )
    dep, med2, obs = load_camtrapdp(camtrap_dir)
    cands = build_candidates(
        dep, med2, obs,
        target_species=["Vulpes vulpes"],
        study_start=date(2025, 11, 1),
        study_end=date(2025, 11, 10),
        occasion_days=5,
        total_iterations=100_000,
        gap_seconds=60,
        include_burst_context=True,
    )
    ctx_ids = set(cands[cands["is_context"] == True]["mediaID"])  # noqa: E712
    assert "m_far_before" not in ctx_ids


# ─── build_species_effort ─────────────────────────────────────────────────────

def test_build_species_effort_file_columns_and_total(candidates, decisions_dir, tmp_path):
    from camtrap_workflow import build_species_effort
    out = tmp_path / "occ"
    df = build_species_effort(candidates, decisions_dir, out)
    assert (out / "effort_report.csv").exists()
    assert list(df["species"]) == ["Vulpes vulpes", "TOTAL"]
    for col in ("cells_detection", "cells_non_detection", "candidate_events", "events_inspected",
                "rejections_before_confirm_max", "rejected_score_median", "confirmed_score_median"):
        assert col in df.columns

def test_build_species_effort_matches_review_effort(candidates, decisions_dir, session_config, tmp_path):
    from camtrap_workflow import build_species_effort
    out = tmp_path / "occ"
    eff = build_species_effort(candidates, decisions_dir, out).iloc[0]
    build_review_effort(candidates, decisions_dir, session_config, out)
    glob = pd.read_csv(out / "review_effort.csv").iloc[0]
    assert eff["cells_detection"] == glob["confirmed_cells"]
    assert eff["cells_non_detection"] == glob["rejected_cells"]
    assert eff["events_inspected"] == glob["images_inspected"]

def test_build_species_effort_total_equals_sum(candidates, decisions_dir, tmp_path):
    from camtrap_workflow import build_species_effort
    df = build_species_effort(candidates, decisions_dir, tmp_path / "occ")
    sp, tot = df.iloc[:-1], df.iloc[-1]
    assert tot["events_inspected"] == sp["events_inspected"].sum()
    assert tot["candidate_cells"] == sp["candidate_cells"].sum()

def test_build_species_effort_rejections_and_scores(candidates, tmp_path):
    from camtrap_workflow import build_species_effort, save_decisions
    # confirm the rank-2 event of the first cell with >=2 events
    cell = candidates.groupby("site_occasion_key")["rank"].max()
    key = cell[cell >= 2].index[0]
    sub = candidates[candidates["site_occasion_key"] == key]
    obs = sub[sub["rank"] == 2].iloc[0]["observationID"]
    d = tmp_path / "dec"
    save_decisions(d, candidates, "Vulpes_vulpes", 2, [obs])
    row = build_species_effort(candidates, d, tmp_path / "o").iloc[0]
    assert row["rejections_before_confirm_max"] == 1
    top = pd.to_numeric(sub[sub["rank"] == 1]["classificationProbability"]).max()
    assert row["rejected_score_max"] == pytest.approx(round(float(top), 3))

def test_build_species_effort_unfinished_cells_are_unverified(candidates, tmp_path):
    from camtrap_workflow import build_species_effort
    df = build_species_effort(candidates, tmp_path / "none", tmp_path / "occ",
                              rounds_done={"Vulpes_vulpes": 0})
    row = df.iloc[0]
    assert row["cells_detection"] == 0 and row["cells_non_detection"] == 0
    assert row["cells_unverified"] == row["candidate_cells"]
    assert row["events_inspected"] == 0

def test_build_species_effort_without_decisions_all_non_detection(candidates, tmp_path):
    from camtrap_workflow import build_species_effort
    df = build_species_effort(candidates, tmp_path / "none", tmp_path / "occ")
    row = df.iloc[0]
    assert row["cells_non_detection"] == row["candidate_cells"]
    assert row["events_inspected"] == row["candidate_events"]
    assert row["pct_events_inspected"] == 100.0


# ─── compute_min_score_exclusions ─────────────────────────────────────────────
# Fixture scores: m001=0.9 m002=0.8 (A occ1 ev0), m005=0.6 (A occ1 ev1), m003=0.7 (A occ2), m004=0.85 (B occ1)

def _exclusions(camtrap_dir, min_score):
    from camtrap_workflow import build_candidates, compute_min_score_exclusions
    dep, med, obs = load_camtrapdp(camtrap_dir)
    kw = dict(target_species=["Vulpes vulpes"], study_start=date(2025, 11, 1),
              study_end=date(2025, 11, 10), occasion_days=5, total_iterations=100_000,
              gap_seconds=60)
    kept = build_candidates(dep, med, obs, min_score=min_score, **kw)
    return compute_min_score_exclusions(kept, dep, med, obs, min_score=min_score, **kw).iloc[0]

def test_exclusions_zero_without_cutoff(camtrap_dir):
    r = _exclusions(camtrap_dir, 0.0)
    assert (r["excluded_photos"], r["excluded_events"], r["excluded_cells"]) == (0, 0, 0)

def test_exclusions_score_equal_to_cutoff_is_kept(camtrap_dir):
    r = _exclusions(camtrap_dir, 0.6)          # m005 scores exactly 0.6
    assert (r["excluded_photos"], r["excluded_events"], r["excluded_cells"]) == (0, 0, 0)

def test_exclusions_just_above_boundary_removes_event_not_cell(camtrap_dir):
    r = _exclusions(camtrap_dir, 0.61)         # m005 (0.6) now below: event lost, cell A/occ1 keeps burst 0
    assert (r["excluded_photos"], r["excluded_events"], r["excluded_cells"]) == (1, 1, 0)

def test_exclusions_high_cutoff_removes_cells(camtrap_dir):
    r = _exclusions(camtrap_dir, 0.95)         # everything below
    assert (r["excluded_photos"], r["excluded_events"], r["excluded_cells"]) == (5, 4, 3)

def test_exclusions_partial_cutoff_counts_cells(camtrap_dir):
    r = _exclusions(camtrap_dir, 0.75)         # drops m003 (0.7) and m005 (0.6): cell A/occ2 lost
    assert r["excluded_photos"] == 2
    assert r["excluded_events"] == 2
    assert r["excluded_cells"] == 1

def test_effort_report_includes_exclusion_columns(candidates, decisions_dir, tmp_path):
    from camtrap_workflow import build_species_effort
    ex = pd.DataFrame({"species": ["Vulpes vulpes"], "excluded_photos": [4],
                       "excluded_events": [3], "excluded_cells": [2]})
    df = build_species_effort(candidates, decisions_dir, tmp_path / "o", exclusions=ex)
    assert df.iloc[0]["excluded_photos"] == 4 and df.iloc[-1]["excluded_cells"] == 2
    df2 = build_species_effort(candidates, decisions_dir, tmp_path / "o2")
    assert df2["excluded_photos"].isna().all()


# ─── uncertain decisions ──────────────────────────────────────────────────────
# Fixture cells: A/occ1 (events rank1=o001, rank2=o005), A/occ2 (o003), B/occ1 (o004)

def test_save_uncertain_writes_and_overwrites(candidates, tmp_path):
    from camtrap_workflow import load_all_uncertain, save_uncertain
    d = tmp_path / "dec"
    save_uncertain(d, candidates, "Vulpes_vulpes", 1, ["o003"])
    assert list(load_all_uncertain(d)["observationID"]) == ["o003"]
    save_uncertain(d, candidates, "Vulpes_vulpes", 1, [])          # changed round: no stale flag
    assert load_all_uncertain(d).empty

def test_uncertain_never_confirms_a_cell(candidates, tmp_path):
    from camtrap_workflow import save_uncertain
    d = tmp_path / "dec"
    save_uncertain(d, candidates, "Vulpes_vulpes", 1, ["o003", "o004"])
    assert confirmed_keys_set(d) == set()
    assert load_all_decisions(d).empty

def test_uncertain_histories_identical_to_reject(candidates, decisions_dir, session_config, tmp_path):
    from camtrap_workflow import save_uncertain
    a, b = tmp_path / "a", tmp_path / "b"
    build_occupancy_inputs(candidates, decisions_dir, session_config, a)
    save_uncertain(decisions_dir, candidates, "Vulpes_vulpes", 1, ["o003", "o004"])
    build_occupancy_inputs(candidates, decisions_dir, session_config, b)
    names = sorted(f.name for f in a.glob("*.csv"))
    assert names and names == sorted(f.name for f in b.glob("*.csv"))
    for n in names:
        assert (a / n).read_text() == (b / n).read_text(), n

def test_effort_report_counts_uncertain(candidates, tmp_path):
    from camtrap_workflow import build_species_effort, save_uncertain
    d = tmp_path / "dec"
    save_uncertain(d, candidates, "Vulpes_vulpes", 1, ["o003", "o004"])
    df = build_species_effort(candidates, d, tmp_path / "o")
    row, tot = df.iloc[0], df.iloc[-1]
    assert row["uncertain_events"] == 2 and tot["uncertain_events"] == 2
    assert row["non_detection_cells_with_uncertain"] == 2

def test_effort_report_uncertain_later_confirmed_not_counted(candidates, tmp_path):
    from camtrap_workflow import build_species_effort, save_decisions, save_uncertain
    d = tmp_path / "dec"
    save_uncertain(d, candidates, "Vulpes_vulpes", 1, ["o003", "o004"])
    save_decisions(d, candidates, "Vulpes_vulpes", 1, ["o003"])    # o003 confirmed after all
    row = build_species_effort(candidates, d, tmp_path / "o").iloc[0]
    assert row["uncertain_events"] == 1

def test_effort_report_zero_uncertain_without_files(candidates, tmp_path):
    from camtrap_workflow import build_species_effort
    row = build_species_effort(candidates, tmp_path / "none", tmp_path / "o").iloc[0]
    assert row["uncertain_events"] == 0 and row["non_detection_cells_with_uncertain"] == 0


# ─── rejection corrections ("actual species") ─────────────────────────────────
# Fixture events: A/occ1 rank1=o001 rank2=o005, A/occ2=o003, B/occ1=o004. decisions_dir confirms o001.

def test_save_rejection_corrections_replaces_round_and_ignores_noise(candidates, tmp_path):
    from camtrap_workflow import load_rejection_corrections, save_rejection_corrections
    f = tmp_path / "rejection_corrections.csv"
    save_rejection_corrections(f, candidates, "Vulpes_vulpes", 1, {"o003": "Dama dama", "o004": "  ", "nope": "x"})
    df = load_rejection_corrections(f)
    assert list(df["observationID"]) == ["o003"] and list(df["actual_species"]) == ["Dama dama"]
    save_rejection_corrections(f, candidates, "Vulpes_vulpes", 2, {"o005": "Homo sapiens"})
    save_rejection_corrections(f, candidates, "Vulpes_vulpes", 1, {"o004": "Canis familiaris"})   # redo round 1
    df = load_rejection_corrections(f)
    assert sorted(df["observationID"]) == ["o004", "o005"]

def test_false_positive_sources_counts_and_coverage(candidates, decisions_dir, tmp_path):
    from camtrap_workflow import build_false_positive_sources, build_species_effort, save_rejection_corrections
    f = tmp_path / "rejection_corrections.csv"
    save_rejection_corrections(f, candidates, "Vulpes_vulpes", 1,
                               {"o003": "Dama dama", "o004": "Homo sapiens", "o001": "Dama dama"})  # o001 is confirmed
    eff = build_species_effort(candidates, decisions_dir, tmp_path / "o")
    fp = build_false_positive_sources(eff, decisions_dir, f, tmp_path / "o").set_index("actual_species")
    assert (tmp_path / "o" / "false_positive_sources.csv").exists()
    assert fp.loc["Dama dama", "rejected_events"] == 1 and fp.loc["Dama dama", "pct_of_rejected_events"] == 50.0
    assert fp.loc["Homo sapiens", "rejected_events"] == 1
    assert fp.loc["(not recorded)", "rejected_events"] == 0           # o001 ignored: confirmed

def test_false_positive_sources_reports_uncorrected_share(candidates, decisions_dir, tmp_path):
    from camtrap_workflow import build_false_positive_sources, build_species_effort, save_rejection_corrections
    f = tmp_path / "rejection_corrections.csv"
    save_rejection_corrections(f, candidates, "Vulpes_vulpes", 1, {"o003": "Dama dama"})
    eff = build_species_effort(candidates, decisions_dir, tmp_path / "o")
    fp = build_false_positive_sources(eff, decisions_dir, f, tmp_path / "o")
    assert fp["pct_of_rejected_events"].sum() == 100.0
    assert fp[fp["actual_species"] == "(not recorded)"]["rejected_events"].iloc[0] == 1

def test_false_positive_sources_none_when_feature_unused(candidates, decisions_dir, tmp_path):
    from camtrap_workflow import build_false_positive_sources, build_species_effort
    eff = build_species_effort(candidates, decisions_dir, tmp_path / "o")
    assert build_false_positive_sources(eff, decisions_dir, tmp_path / "missing.csv", tmp_path / "o") is None

def test_corrections_do_not_change_histories(candidates, decisions_dir, session_config, tmp_path):
    from camtrap_workflow import save_rejection_corrections
    a, b = tmp_path / "a", tmp_path / "b"
    build_occupancy_inputs(candidates, decisions_dir, session_config, a)
    save_rejection_corrections(tmp_path / "rejection_corrections.csv", candidates, "Vulpes_vulpes", 1,
                               {"o003": "Dama dama", "o004": "Homo sapiens"})
    build_occupancy_inputs(candidates, decisions_dir, session_config, b)
    names = sorted(f.name for f in a.glob("*.csv"))
    assert names == sorted(f.name for f in b.glob("*.csv"))
    for n in names:
        assert (a / n).read_text() == (b / n).read_text(), n


# ─── review time (decision timestamps) ────────────────────────────────────────

def _log(rows):
    """rows: (species, 'HH:MM:SS') -> review log frame."""
    return pd.DataFrame({
        "observationID": [f"x{i}" for i in range(len(rows))],
        "site_occasion_key": "k", "species_safe": [s.replace(" ", "_") for s, _ in rows],
        "scientificName": [s for s, _ in rows], "iteration": "1", "decision": "rejected",
        "decided_at": [f"2026-01-01T{t}.000Z" for _, t in rows],
    })

def test_review_time_excludes_idle_gaps():
    from camtrap_workflow import review_time_by_species
    log = _log([("Cervus elaphus", "10:00:00"), ("Cervus elaphus", "10:00:30"),
                ("Dama dama", "10:01:00"), ("Dama dama", "10:10:00"),     # 9 min pause: idle
                ("Cervus elaphus", "10:10:20")])
    rt = review_time_by_species(log, idle_seconds=120)
    assert rt["seconds"] == 80 and rt["credited"] == 3 and rt["timed"] == 5
    assert rt["by_species"]["Cervus elaphus"] == {"seconds": 50.0, "credited": 2, "timed": 3}
    assert rt["by_species"]["Dama dama"] == {"seconds": 30.0, "credited": 1, "timed": 2}

def test_review_time_threshold_is_inclusive_and_configurable():
    from camtrap_workflow import review_time_by_species
    log = _log([("A a", "10:00:00"), ("A a", "10:02:00")])                # gap exactly 120 s
    assert review_time_by_species(log, 120)["seconds"] == 120
    assert review_time_by_species(log, 119)["seconds"] == 0
    assert review_time_by_species(_log([("A a", "10:00:00"), ("A a", "10:09:00")]), 600)["seconds"] == 540

def test_review_time_orders_by_time_and_handles_no_log():
    from camtrap_workflow import review_time_by_species
    shuffled = _log([("A a", "10:00:40"), ("A a", "10:00:00"), ("A a", "10:00:10")])
    assert review_time_by_species(shuffled)["seconds"] == 40
    empty = review_time_by_species(_log([]))
    assert empty["timed"] == 0 and empty["seconds"] == 0 and empty["by_species"] == {}

def test_save_review_log_labels_replaces_round_and_keeps_old_times(candidates, tmp_path):
    from camtrap_workflow import load_review_log, save_review_log
    f = tmp_path / "review_log.csv"
    t0 = 1_767_261_600_000                                              # 2026-01-01T10:00:00Z
    save_review_log(f, candidates, "Vulpes_vulpes", 1, ["o001"], ["o004"],
                    {"o001": t0, "o003": t0 + 30_000, "o004": t0 + 45_000})
    df = load_review_log(f).set_index("observationID")
    assert df.loc["o001", "decision"] == "confirmed" and df.loc["o004", "decision"] == "uncertain"
    assert df.loc["o003", "decision"] == "rejected" and df.loc["o001", "decided_at"] == "2026-01-01T10:00:00.000Z"
    # re-save the round touching only o003: o001/o004 are not in the new times, so keep what they had
    save_review_log(f, candidates, "Vulpes_vulpes", 1, ["o001"], ["o004"], {"o003": t0 + 90_000})
    df = load_review_log(f).set_index("observationID")
    assert df.loc["o001", "decided_at"] == "2026-01-01T10:00:00.000Z"
    assert df.loc["o003", "decided_at"] == "2026-01-01T10:01:30.000Z" and len(df) == 3

def test_effort_report_review_time_columns(candidates, tmp_path):
    from camtrap_workflow import build_species_effort
    log = _log([("Vulpes vulpes", "10:00:00"), ("Vulpes vulpes", "10:00:30"),
                ("Vulpes vulpes", "10:01:00"), ("Vulpes vulpes", "11:00:00")])   # last one after a break
    df = build_species_effort(candidates, tmp_path / "none", tmp_path / "o", review_log=log, idle_seconds=120)
    tot = df.iloc[-1]
    assert tot["review_active_seconds"] == 60 and tot["review_decisions_timed"] == 4
    assert tot["review_seconds_per_decision"] == 30.0                   # 60 s over 2 credited decisions
    assert tot["review_est_full_seconds"] == 30 * 4                     # 4 candidate events
    assert tot["review_est_saved_seconds"] == 120 - 60
    assert df.iloc[0]["review_active_seconds"] == 60

def test_effort_report_review_time_none_for_old_sessions(candidates, tmp_path):
    from camtrap_workflow import build_species_effort
    df = build_species_effort(candidates, tmp_path / "none", tmp_path / "o")
    assert df["review_active_seconds"].isna().all() and df["review_est_saved_seconds"].isna().all()


# ─── seeded random tie-break among events with the same score ─────────────────

def _tie_tables(scores, shuffle_seed=None):
    """One site, one occasion; one event per frame (3 h apart), so rank order = event review order."""
    n = len(scores)
    dep = pd.DataFrame({"deploymentID": ["D"], "locationID": ["S"],
                        "deploymentStart": ["2025-11-01"], "deploymentEnd": ["2025-11-05"]})
    med = pd.DataFrame({"mediaID": [f"m{i:02d}" for i in range(n)], "deploymentID": "D",
                        "timestamp": [f"2025-11-02 {(3 * i) // 60:02d}:{(3 * i) % 60:02d}:00" for i in range(n)],
                        "filePath": [f"i{i}.jpg" for i in range(n)]})
    # 3 minutes apart > the 60 s gap used below, so every frame is its own event
    obs = pd.DataFrame({"observationID": [f"o{i:02d}" for i in range(n)], "deploymentID": "D",
                        "mediaID": [f"m{i:02d}" for i in range(n)], "observationLevel": "media",
                        "observationType": "animal", "scientificName": "Vulpes vulpes",
                        "classificationProbability": [None if s is None else str(s) for s in scores],
                        "classificationMethod": "machine", "classifiedBy": "x", "classificationTimestamp": None})
    if shuffle_seed is not None:
        med = med.sample(frac=1, random_state=shuffle_seed).reset_index(drop=True)
        obs = obs.sample(frac=1, random_state=shuffle_seed).reset_index(drop=True)
    return dep, med, obs


def _review_order(scores, seed=42, shuffle_seed=None):
    from camtrap_workflow import build_candidates
    dep, med, obs = _tie_tables(scores, shuffle_seed)
    c = build_candidates(dep, med, obs, target_species=["Vulpes vulpes"], study_start=date(2025, 11, 1),
                         study_end=date(2025, 11, 5), occasion_days=5, total_iterations=1000,
                         gap_seconds=60, seed=seed)
    return list(c.sort_values("rank")["mediaID"])


def test_scores_still_decide_the_order():
    assert _review_order([0.2, 0.9, 0.5, 0.7]) == ["m01", "m03", "m02", "m00"]


def test_without_scores_order_is_random_not_chronological_and_complete():
    order = _review_order([None] * 12)
    assert sorted(order) == [f"m{i:02d}" for i in range(12)]          # every event, once
    assert order != [f"m{i:02d}" for i in range(12)]                  # not chronological


def test_tiebreak_is_reproducible_and_depends_on_the_seed():
    a = _review_order([None] * 12, seed=7)
    assert a == _review_order([None] * 12, seed=7)
    assert a != _review_order([None] * 12, seed=8)


def test_tiebreak_does_not_depend_on_row_order():
    assert _review_order([None] * 12, shuffle_seed=1) == _review_order([None] * 12) \
        == _review_order([None] * 12, shuffle_seed=2)


def test_only_equal_scores_are_shuffled():
    order = _review_order([0.9, 0.5, 0.5, 0.5, 0.5, 0.1])
    assert order[0] == "m00" and order[-1] == "m05"                    # distinct scores keep their place
    assert sorted(order[1:5]) == ["m01", "m02", "m03", "m04"]
