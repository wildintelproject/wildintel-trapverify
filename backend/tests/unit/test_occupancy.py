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
    assert set(result.keys()) == {"psi", "psi_lo", "psi_hi", "p", "p_lo", "p_hi", "degenerate", "converged"}

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


# ─── confidence intervals: method checks ──────────────────────────────────────

def _simulate(rng, n_sites, k, psi, p):
    z = rng.random(n_sites) < psi
    return ((rng.random((n_sites, k)) < p) * z[:, None]).astype(float)


def test_hessian_is_exact_for_a_quadratic():
    from occupancy_model import _hessian
    A = np.array([[4.0, 1.0], [1.0, 3.0]])
    H = _hessian(lambda t: 0.5 * t @ A @ t, np.array([0.3, -1.2]))
    assert H == pytest.approx(A, abs=1e-5)


def test_wald_interval_is_symmetric_on_the_logit_scale():
    from occupancy_model import _logit_wald_ci, _sigmoid
    lo, hi = _logit_wald_ci(0.4, 0.5)
    logit = lambda q: np.log(q / (1 - q))
    assert logit(hi) - 0.4 == pytest.approx(0.4 - logit(lo))
    assert logit(hi) - 0.4 == pytest.approx(1.96 * 0.5)
    assert 0 < lo < _sigmoid(0.4) < hi < 1


def test_fit_occu_intervals_match_an_independent_hessian():
    """SEs come from the inverse observed information: recompute it with a different step."""
    from occupancy_model import _hessian, _logit_wald_ci, _nll
    y = _simulate(np.random.default_rng(4), 60, 5, 0.5, 0.4)
    r = fit_occu(y)
    theta = np.array([np.log(r["psi"] / (1 - r["psi"])), np.log(r["p"] / (1 - r["p"]))])
    cov = np.linalg.inv(_hessian(lambda t: _nll(t, y), theta, h=1e-3))
    for k, (lo, hi) in enumerate((("psi_lo", "psi_hi"), ("p_lo", "p_hi"))):
        e_lo, e_hi = _logit_wald_ci(theta[k], np.sqrt(cov[k, k]))
        assert r[lo] == pytest.approx(e_lo, abs=5e-3) and r[hi] == pytest.approx(e_hi, abs=5e-3)


def test_fit_occu_gives_a_confidence_interval_for_p():
    r = fit_occu(_simulate(np.random.default_rng(1), 50, 5, 0.6, 0.4))
    assert r["p_lo"] is not None and r["p_lo"] < r["p"] < r["p_hi"]


def test_fit_occu_intervals_have_about_nominal_coverage():
    """Repeated datasets from known psi and p: the 95 % intervals must contain the truth most of the time."""
    rng = np.random.default_rng(2026)
    psi_true, p_true, hits_psi, hits_p, n = 0.5, 0.4, 0, 0, 0
    for _ in range(150):
        r = fit_occu(_simulate(rng, 60, 5, psi_true, p_true))
        if r["degenerate"] or r["psi_lo"] is None or r["p_lo"] is None:
            continue
        n += 1
        hits_psi += r["psi_lo"] <= psi_true <= r["psi_hi"]
        hits_p += r["p_lo"] <= p_true <= r["p_hi"]
    assert n > 120
    assert hits_psi / n > 0.88 and hits_p / n > 0.88          # nominal 0.95; Wald is a little liberal


def test_fit_naive_vs_verified_exports_all_four_estimates_with_intervals(tmp_path):
    rng = np.random.default_rng(9)
    for kind, y in (("naive", _simulate(rng, 50, 5, 0.7, 0.5)), ("verified", _simulate(rng, 50, 5, 0.5, 0.5))):
        df = pd.DataFrame(y, columns=[f"occ{i + 1}" for i in range(5)]).astype(int)
        df.insert(0, "siteID", [f"S{i}" for i in range(len(df))])
        df.to_csv(tmp_path / f"dethist_{kind}_Vulpes_vulpes.csv", index=False)
    row = fit_naive_vs_verified(tmp_path, ["Vulpes vulpes"])[0]
    out = pd.read_csv(tmp_path / "occupancy_fit.csv").iloc[0]
    for est in ("psi_naive", "psi_verified", "p_naive", "p_verified"):
        for suffix in ("", "_lo", "_hi"):
            assert pd.notna(out[est + suffix]), est + suffix
        assert out[est + "_lo"] < out[est] < out[est + "_hi"]
    assert row["p_naive_lo"] == out["p_naive_lo"]
