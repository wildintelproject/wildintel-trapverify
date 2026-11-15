"""Tests for the random-subsample simulation (small fixtures)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

from random_subsample import load_session, simulate_random_subsample

ROOT = Path(__file__).resolve().parents[3]


def _cells(n_cells: int, events_per_cell: int = 1, species: str = "Vulpes vulpes") -> pd.DataFrame:
    """Candidates: `n_cells` cells with `events_per_cell` events (rank 1, 2, ...), one photo each."""
    sp = species.replace(" ", "_")
    rows = []
    for c in range(n_cells):
        for e in range(events_per_cell):
            rows.append({
                "observationID": f"{sp}_o{c}_{e}", "mediaID": f"{sp}_m{c}_{e}", "scientificName": species,
                "species_safe": sp, "site_occasion_key": f"S{c}_occ1_{sp}", "siteID": f"S{c}", "occasion": 1,
                "burst_id": e, "rank": e + 1, "classificationProbability": "0.9",
            })
    return pd.DataFrame(rows)


def _confirm(tmp_path, cand, ids):
    from camtrap_workflow import save_decisions
    d = tmp_path / "decisions"
    save_decisions(d, cand, "Vulpes_vulpes", 1, ids)
    return d


def test_fixture_expected_value(candidates, decisions_dir):
    """5 photos, 3 reviewed, one detection cell whose event has 2 of the 5 photos:
    P(found) = 1 - C(3,3)/C(5,3) = 0.9."""
    df = simulate_random_subsample(candidates, decisions_dir, draws=4000, seed=1)
    row = df[df["species"] == "Vulpes vulpes"].iloc[0]
    assert (row["candidate_photos"], row["photos_reviewed"], row["cells_with_detection"]) == (5, 3, 1)
    assert row["targeted_found"] == 1 and row["targeted_found_pct"] == 100.0
    assert row["random_found_mean"] == pytest.approx(0.9, abs=0.03)
    assert row["random_found_min"] in (0, 1) and row["random_found_max"] == 1


def test_same_seed_is_reproducible_and_other_seed_differs(candidates, decisions_dir):
    a = simulate_random_subsample(candidates, decisions_dir, draws=200, seed=7)
    b = simulate_random_subsample(candidates, decisions_dir, draws=200, seed=7)
    c = simulate_random_subsample(candidates, decisions_dir, draws=200, seed=8)
    pd.testing.assert_frame_equal(a, b)
    assert not a["random_found_mean"].equals(c["random_found_mean"])


def test_reviewing_everything_finds_everything(tmp_path):
    cand = _cells(4)
    d = _confirm(tmp_path, cand, list(cand["observationID"]))          # 4 cells, 4 photos, all reviewed
    row = simulate_random_subsample(cand, d, draws=50, seed=1).iloc[0]
    assert row["photos_reviewed"] == row["candidate_photos"] == 4
    assert (row["random_found_min"], row["random_found_max"]) == (4, 4)
    assert row["random_found_pct_mean"] == 100.0


def test_random_matches_hypergeometric_expectation(tmp_path):
    """10 cells x 2 events = 20 photos. Round 1 inspects the 10 rank-1 events and confirms 4, so 10 of
    the 20 photos are drawn and 4 are true: each true photo is drawn with p = 10/20, mean found = 2."""
    cand = _cells(10, events_per_cell=2)
    d = _confirm(tmp_path, cand, list(cand[(cand["rank"] == 1)]["observationID"][:4]))
    row = simulate_random_subsample(cand, d, draws=4000, seed=3).iloc[0]
    assert (row["candidate_photos"], row["photos_reviewed"], row["cells_with_detection"]) == (20, 10, 4)
    assert row["random_found_mean"] == pytest.approx(2.0, abs=0.06)
    assert row["random_found_pct_mean"] == pytest.approx(50.0, abs=1.5)


def test_species_without_detections_has_no_random_columns(tmp_path):
    cand = _cells(3)
    d = _confirm(tmp_path, cand, [])                                   # nothing confirmed
    row = simulate_random_subsample(cand, d, draws=10, seed=1).iloc[0]
    assert row["cells_with_detection"] == 0
    assert pd.isna(row["random_found_mean"]) and pd.isna(row["random_found_pct_mean"])


def test_total_row_sums_species(candidates, decisions_dir):
    df = simulate_random_subsample(candidates, decisions_dir, draws=100, seed=2)
    sp, tot = df.iloc[:-1], df.iloc[-1]
    assert tot["species"] == "TOTAL"
    assert tot["photos_reviewed"] == sp["photos_reviewed"].sum()
    assert tot["cells_with_detection"] == sp["cells_with_detection"].sum()


def test_species_result_does_not_depend_on_other_species(tmp_path):
    from camtrap_workflow import save_decisions
    a, b = _cells(6, 2, "Vulpes vulpes"), _cells(6, 2, "Sus scrofa")
    both = pd.concat([a, b], ignore_index=True)
    d = tmp_path / "dec"
    for frame, sp in ((a, "Vulpes_vulpes"), (b, "Sus_scrofa")):
        save_decisions(d, both, sp, 1, list(frame[frame["rank"] == 1]["observationID"][:3]))
    full = simulate_random_subsample(both, d, draws=100, seed=5).set_index("species")
    only_a = simulate_random_subsample(a, d, draws=100, seed=5).set_index("species")
    only_b = simulate_random_subsample(b, d, draws=100, seed=5).set_index("species")
    pd.testing.assert_series_equal(full.loc["Vulpes vulpes"], only_a.loc["Vulpes vulpes"])
    pd.testing.assert_series_equal(full.loc["Sus scrofa"], only_b.loc["Sus scrofa"])


def test_load_session_errors_without_manifest(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_session(tmp_path)


def test_cli_writes_csv_into_the_session(candidates, decisions_dir, tmp_path):
    from typer.testing import CliRunner
    sys.path.insert(0, str(ROOT))
    import manage
    session = tmp_path / "session"
    session.mkdir()
    candidates.to_csv(session / "candidate_manifest.csv", index=False)
    (session / "decisions").mkdir()
    for f in decisions_dir.glob("*.csv"):
        (session / "decisions" / f.name).write_text(f.read_text())
    res = CliRunner().invoke(manage.app, ["simulate-random", str(session), "--draws", "50", "--seed", "3"])
    assert res.exit_code == 0, res.output
    out = pd.read_csv(session / "random_subsample_simulation.csv")
    assert list(out["species"]) == ["Vulpes vulpes", "TOTAL"] and (out["draws"] == 50).all()
    bad = CliRunner().invoke(manage.app, ["simulate-random", str(tmp_path / "nope")])
    assert bad.exit_code == 1
