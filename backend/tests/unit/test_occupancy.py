"""Unit tests for occupancy_model.py."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from occupancy_model import _sigmoid, fit_occu, fit_naive_vs_verified


# ─── _sigmoid ─────────────────────────────────────────────────────────────────

def test_sigmoid_zero():
    assert abs(_sigmoid(0.0) - 0.5) < 1e-9

def test_sigmoid_large_positive():
    assert _sigmoid(100.0) > 0.999

def test_sigmoid_large_negative():
    assert _sigmoid(-100.0) < 0.001

def test_sigmoid_clamps_extreme():
    assert 0.0 < _sigmoid(1e6) <= 1.0
    assert 0.0 <= _sigmoid(-1e6) < 1.0


# ─── fit_occu: return structure ───────────────────────────────────────────────

def test_fit_occu_returns_expected_keys():
    y = np.array([[1, 0], [0, 0], [1, 1]], dtype=float)
    result = fit_occu(y)
    assert set(result.keys()) == {"psi", "psi_lo", "psi_hi", "p", "degenerate", "converged"}

def test_fit_occu_psi_in_unit_interval():
    y = np.array([[1, 0], [0, 0], [1, 1], [0, 1], [1, 0]], dtype=float)
    r = fit_occu(y)
    assert 0.0 <= r["psi"] <= 1.0

def test_fit_occu_p_in_unit_interval():
    y = np.array([[1, 0], [0, 0], [1, 1], [0, 1], [1, 0]], dtype=float)
    r = fit_occu(y)
    if r["p"] is not None:
        assert 0.0 <= r["p"] <= 1.0

def test_fit_occu_ci_ordered():
    y = np.array([[1, 0], [0, 0], [1, 1], [0, 1], [1, 0]], dtype=float)
    r = fit_occu(y)
    if r["psi_lo"] is not None and r["psi_hi"] is not None:
        assert r["psi_lo"] <= r["psi"] <= r["psi_hi"]


# ─── fit_occu: normal case ────────────────────────────────────────────────────

def test_fit_occu_converges_on_typical_data():
    # 10 sites × 4 occasions, psi≈0.6, p≈0.5
    rng = np.random.default_rng(0)
    occupied = rng.binomial(1, 0.6, 10).astype(float)
    y = np.column_stack([
        occupied * rng.binomial(1, 0.5, 10) for _ in range(4)
    ]).astype(float)
    r = fit_occu(y)
    assert r["converged"]
    assert not r["degenerate"]
    assert 0 < r["psi"] < 1
    assert 0 < r["p"] < 1

def test_fit_occu_psi_roughly_matches_truth():
    # True psi=0.5, p=0.7 over 20 sites × 5 occasions
    rng = np.random.default_rng(42)
    occupied = rng.binomial(1, 0.5, 20).astype(float)
    y = np.column_stack([
        occupied * rng.binomial(1, 0.7, 20) for _ in range(5)
    ]).astype(float)
    r = fit_occu(y)
    assert r["converged"]
    # psi should be in a plausible range around 0.5
    assert 0.2 < r["psi"] < 0.9


# ─── fit_occu: degenerate cases ──────────────────────────────────────────────

def test_fit_occu_all_zeros_degenerate():
    y = np.zeros((5, 3))
    r = fit_occu(y)
    assert r["degenerate"]
    assert not r["converged"]
    assert r["psi"] == 0.0
    assert r["psi_lo"] is None
    assert r["psi_hi"] is None

def test_fit_occu_all_ones_degenerate():
    y = np.ones((5, 3))
    r = fit_occu(y)
    assert r["degenerate"]
    assert r["psi_lo"] is None

def test_fit_occu_empty_matrix_degenerate():
    y = np.full((3, 2), np.nan)
    r = fit_occu(y)
    assert r["degenerate"]

def test_fit_occu_single_site_all_detected():
    y = np.array([[1, 1, 1]], dtype=float)
    r = fit_occu(y)
    assert r["degenerate"]


# ─── fit_occu: NaN handling ───────────────────────────────────────────────────

def test_fit_occu_ignores_nan_occasions():
    y = np.array([
        [1.0, np.nan],
        [0.0, 0.0],
        [1.0, 1.0],
        [0.0, np.nan],
        [1.0, 0.0],
    ])
    r = fit_occu(y)
    assert r["psi"] is not None
    assert 0 < r["psi"] < 1

def test_fit_occu_all_nan_row_ignored():
    # With only 3 effective sites CI may be wide (degenerate=True is acceptable);
    # what matters is that NaN rows don't crash the model and psi is returned.
    y = np.array([
        [np.nan, np.nan],
        [1.0, 0.0],
        [0.0, 0.0],
        [1.0, 1.0],
    ])
    r = fit_occu(y)
    assert r["psi"] is not None
    assert 0.0 <= r["psi"] <= 1.0


# ─── fit_naive_vs_verified ────────────────────────────────────────────────────

def _write_dethist(path: Path, y: np.ndarray):
    n_occ = y.shape[1]
    cols = [f"occ{i+1}" for i in range(n_occ)]
    pd.DataFrame(y, columns=cols).to_csv(path, index=False)


def test_fit_naive_vs_verified_returns_one_row_per_species(tmp_path):
    y = np.array([[1, 0, 1], [0, 0, 0], [1, 1, 0]], dtype=float)
    _write_dethist(tmp_path / "dethist_naive_Vulpes_vulpes.csv", y)
    _write_dethist(tmp_path / "dethist_verified_Vulpes_vulpes.csv", y)
    results = fit_naive_vs_verified(tmp_path, ["Vulpes vulpes"])
    assert len(results) == 1

def test_fit_naive_vs_verified_result_keys(tmp_path):
    y = np.array([[1, 0, 1], [0, 0, 0], [1, 1, 0]], dtype=float)
    _write_dethist(tmp_path / "dethist_naive_Vulpes_vulpes.csv", y)
    _write_dethist(tmp_path / "dethist_verified_Vulpes_vulpes.csv", y)
    row = fit_naive_vs_verified(tmp_path, ["Vulpes vulpes"])[0]
    assert "species" in row
    assert "psi_naive" in row
    assert "psi_verified" in row
    assert "degenerate_naive" in row
    assert "degenerate_verified" in row

def test_fit_naive_vs_verified_species_name_preserved(tmp_path):
    y = np.array([[1, 0, 1], [0, 0, 0], [1, 1, 0]], dtype=float)
    _write_dethist(tmp_path / "dethist_naive_Vulpes_vulpes.csv", y)
    _write_dethist(tmp_path / "dethist_verified_Vulpes_vulpes.csv", y)
    row = fit_naive_vs_verified(tmp_path, ["Vulpes vulpes"])[0]
    assert row["species"] == "Vulpes vulpes"

def test_fit_naive_vs_verified_writes_csv(tmp_path):
    y = np.array([[1, 0, 1], [0, 0, 0], [1, 1, 0]], dtype=float)
    _write_dethist(tmp_path / "dethist_naive_Vulpes_vulpes.csv", y)
    _write_dethist(tmp_path / "dethist_verified_Vulpes_vulpes.csv", y)
    fit_naive_vs_verified(tmp_path, ["Vulpes vulpes"])
    assert (tmp_path / "occupancy_fit.csv").exists()

def test_fit_naive_vs_verified_csv_has_species_column(tmp_path):
    y = np.array([[1, 0, 1], [0, 0, 0], [1, 1, 0]], dtype=float)
    _write_dethist(tmp_path / "dethist_naive_Vulpes_vulpes.csv", y)
    _write_dethist(tmp_path / "dethist_verified_Vulpes_vulpes.csv", y)
    fit_naive_vs_verified(tmp_path, ["Vulpes vulpes"])
    df = pd.read_csv(tmp_path / "occupancy_fit.csv")
    assert "species" in df.columns
    assert df.iloc[0]["species"] == "Vulpes vulpes"

def test_fit_naive_vs_verified_missing_files_skipped(tmp_path):
    results = fit_naive_vs_verified(tmp_path, ["Vulpes vulpes"])
    assert results == []

def test_fit_naive_vs_verified_only_naive_missing_skips(tmp_path):
    y = np.array([[1, 0, 1], [0, 0, 0]], dtype=float)
    _write_dethist(tmp_path / "dethist_verified_Vulpes_vulpes.csv", y)
    results = fit_naive_vs_verified(tmp_path, ["Vulpes vulpes"])
    assert results == []

def test_fit_naive_vs_verified_multiple_species(tmp_path):
    y1 = np.array([[1, 0, 1], [0, 0, 0], [1, 1, 0]], dtype=float)
    y2 = np.array([[0, 0, 0], [1, 0, 1]], dtype=float)
    _write_dethist(tmp_path / "dethist_naive_Vulpes_vulpes.csv", y1)
    _write_dethist(tmp_path / "dethist_verified_Vulpes_vulpes.csv", y1)
    _write_dethist(tmp_path / "dethist_naive_Cervus_elaphus.csv", y2)
    _write_dethist(tmp_path / "dethist_verified_Cervus_elaphus.csv", y2)
    results = fit_naive_vs_verified(tmp_path, ["Vulpes vulpes", "Cervus elaphus"])
    assert len(results) == 2
    species = {r["species"] for r in results}
    assert species == {"Vulpes vulpes", "Cervus elaphus"}

def test_fit_naive_vs_verified_all_zeros_degenerate(tmp_path):
    y = np.zeros((5, 3))
    _write_dethist(tmp_path / "dethist_naive_Vulpes_vulpes.csv", y)
    _write_dethist(tmp_path / "dethist_verified_Vulpes_vulpes.csv", y)
    row = fit_naive_vs_verified(tmp_path, ["Vulpes vulpes"])[0]
    assert row["degenerate_naive"] is True
    assert row["degenerate_verified"] is True
