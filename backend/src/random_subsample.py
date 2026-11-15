"""Random-subsample simulation for a finished session.

The paper claims that reviewing the same number of photos *at random* would leave
most cells with a detection unresolved. This module tests that claim on a real
session: for each species it draws the same number of candidate photos the
reviewer inspected, many times, and counts in how many of the cells where the
targeted workflow confirmed a detection the draw would also have hit a photo of
the confirmed event.

Definitions (also in the developer manual):

* **Photos reviewed** per species = detection events inspected (inspecting an
  event means viewing its top-scoring photo), so a random draw of the same size
  picks that many *candidate photos* of the species.
* **Truth** = the cells confirmed in the session; a draw *finds* such a cell when
  it contains at least one photo of the confirmed detection event. Other true
  events of the same cell are unknown (the workflow stops at the first
  confirmation), so this is, if anything, a lower bound for random sampling.
* Cells with no detection cannot be "found" by chance, so only detection cells
  are compared; the targeted workflow finds 100 % of them by construction.
"""
from pathlib import Path
import tempfile
import zlib

import numpy as np
import pandas as pd

from camtrap_workflow import (
    build_species_effort,
    load_all_decisions,
    rounds_completed,
)


def simulate_random_subsample(
    candidates: pd.DataFrame,
    decisions_dir: Path,
    draws: int = 1000,
    seed: int = 42,
) -> pd.DataFrame:
    """Compare targeted verification with random photo subsamples of the same size.

    Args:
        candidates: The session's candidate manifest.
        decisions_dir: The session's ``decisions/`` folder.
        draws: Number of random subsamples per species.
        seed: Seed of the random generator; the same seed gives the same result
            (each species uses its own child stream, so it does not depend on
            which other species are present).

    Returns:
        One row per species plus ``TOTAL`` with the cells with a detection, how
        many the targeted workflow found, and the mean, minimum and maximum found
        by the random draws (counts and % of detection cells).
    """
    cand = candidates.copy()
    if "is_context" in cand.columns:
        cand = cand[~cand["is_context"].astype(bool)]
    dec = load_all_decisions(decisions_dir) if decisions_dir.exists() else pd.DataFrame()
    conf_ids = set(dec["observationID"].dropna()) if not dec.empty else set()

    with tempfile.TemporaryDirectory() as tmp:
        effort = build_species_effort(
            candidates, decisions_dir, Path(tmp), rounds_completed(decisions_dir)
        )
    reviewed = dict(zip(effort["species"], effort["events_inspected"]))

    species = sorted(cand["scientificName"].unique())
    rows: list[dict] = []
    per_draw_total = np.zeros(draws)
    tot = {"candidate_photos": 0, "photos_reviewed": 0, "cells_with_detection": 0}

    for sp in species:
        sub = cand[cand["scientificName"] == sp].reset_index(drop=True)
        n_pool = len(sub)
        n_draw = int(min(reviewed.get(sp, 0), n_pool))

        # Photos of the confirmed event of each confirmed cell are the "true" ones.
        confirmed = sub[sub["observationID"].isin(conf_ids)].sort_values("rank")
        confirmed = confirmed.drop_duplicates("site_occasion_key")
        key = confirmed[["site_occasion_key", "burst_id"]]
        is_true = sub.merge(key.assign(_t=True), on=["site_occasion_key", "burst_id"], how="left")["_t"] \
            .fillna(False).to_numpy(dtype=bool)
        cell_codes, _ = pd.factorize(sub["site_occasion_key"])
        true_idx = np.flatnonzero(is_true)
        true_cells = cell_codes[true_idx]
        n_cells = len(confirmed)

        # Own stream per species, derived from the seed and the species name, so the result
        # for a species does not depend on which other species are in the session.
        rng = np.random.default_rng(np.random.SeedSequence([seed, zlib.crc32(sp.encode())]))
        found = np.zeros(draws, dtype=int)
        if n_cells and n_draw:
            for d in range(draws):
                hit = np.zeros(n_pool, dtype=bool)
                hit[rng.choice(n_pool, size=n_draw, replace=False)] = True
                found[d] = np.unique(true_cells[hit[true_idx]]).size
        per_draw_total += found

        rows.append(_row(sp, n_pool, n_draw, n_cells, found, draws, seed))
        tot["candidate_photos"] += n_pool
        tot["photos_reviewed"] += n_draw
        tot["cells_with_detection"] += n_cells

    rows.append(_row("TOTAL", tot["candidate_photos"], tot["photos_reviewed"],
                     tot["cells_with_detection"], per_draw_total, draws, seed))
    return pd.DataFrame(rows)


def _row(species: str, n_pool: int, n_draw: int, n_cells: int,
         found: np.ndarray, draws: int, seed: int) -> dict:
    def pct(x: float) -> float | None:
        return round(100 * x / n_cells, 1) if n_cells else None
    return {
        "species": species,
        "candidate_photos": n_pool,
        "photos_reviewed": n_draw,
        "cells_with_detection": n_cells,
        "targeted_found": n_cells,
        "targeted_found_pct": 100.0 if n_cells else None,
        "random_found_mean": round(float(found.mean()), 2) if n_cells else None,
        "random_found_min": int(found.min()) if n_cells else None,
        "random_found_max": int(found.max()) if n_cells else None,
        "random_found_pct_mean": pct(float(found.mean())),
        "random_found_pct_min": pct(float(found.min())),
        "random_found_pct_max": pct(float(found.max())),
        "draws": draws,
        "seed": seed,
    }


def load_session(session_dir: Path) -> tuple[pd.DataFrame, Path]:
    """Read ``candidate_manifest.csv`` and locate ``decisions/`` of a session folder."""
    manifest = session_dir / "candidate_manifest.csv"
    if not manifest.exists():
        raise FileNotFoundError(f"Not a session folder (no candidate_manifest.csv): {session_dir}")
    candidates = pd.read_csv(manifest, dtype={"mediaID": str, "observationID": str})
    return candidates, session_dir / "decisions"
