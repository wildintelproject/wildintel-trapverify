"""
Workflow orchestration for CamTrap Verify.

Wraps camtrap_workflow calls triggered by multiple routes to avoid
duplication across routers. All session state is accessed via
session_service's public API.
"""
import json
import logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

import pandas as pd
from camtrap_workflow import (
    build_candidates,
    build_occupancy_inputs,
    build_review_effort,
    export_verified_camtrapdp,
    load_camtrapdp,
)
from occupancy_model import fit_naive_vs_verified

from schemas.requests import SetupRequest
from services import session_service


def rebuild_outputs() -> None:
    """Regenerate camtrap_dp_verified and occupancy_inputs from current session state."""
    logger.info("Rebuilding output files")
    p = session_service.paths()
    config = session_service.get_config()
    candidates = session_service.get_candidates()
    rejected = session_service.get_rejected_media()

    export_verified_camtrapdp(
        Path(config["camtrap_dir"]), p["camtrap_out"], p["decisions"], rejected,
    )
    build_occupancy_inputs(candidates, p["decisions"], config, p["occupancy_out"])
    build_review_effort(candidates, p["decisions"], config, p["occupancy_out"])
    fit_naive_vs_verified(p["occupancy_out"], config.get("target_species", []))
    logger.info("Output files rebuilt successfully")


def run_setup(req: SetupRequest) -> dict:
    """Execute the full setup workflow for a new session.

    The caller must verify that req.camtrap_dir exists before calling.

    Returns:
        Dict with ok, session_dir, n_candidates, n_combos.
    """
    logger.info("Starting setup: camtrap_dir=%s species=%s", req.camtrap_dir, req.target_species)
    camtrap_dir = Path(req.camtrap_dir)
    dep, med, obs = load_camtrapdp(camtrap_dir)
    candidates = build_candidates(
        dep, med, obs,
        target_species=req.target_species,
        study_start=date.fromisoformat(req.study_start),
        study_end=date.fromisoformat(req.study_end),
        occasion_days=req.occasion_days,
        total_iterations=req.total_iterations,
        gap_seconds=req.gap_seconds,
    )

    base_out = Path(req.output_dir) if req.output_dir else session_service.DEFAULT_OUTPUT_DIR
    sd = base_out / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    sd.mkdir(parents=True, exist_ok=True)

    config = req.model_dump()
    config["camtrap_dir"] = str(camtrap_dir.resolve())
    config["output_dir"] = str(base_out)
    config["session_dir"] = str(sd)

    (sd / "config.json").write_text(json.dumps(config, indent=2))
    candidates.to_csv(sd / "candidate_manifest.csv", index=False)

    session_service.APP_DIR.mkdir(parents=True, exist_ok=True)
    session_service.SESSION_FILE.write_text(json.dumps({"session_dir": str(sd)}))

    session_service.init_session(sd, config, candidates)
    rebuild_outputs()

    logger.info(
        "Setup complete: session=%s candidates=%d combos=%d",
        sd, len(candidates), int(candidates["site_occasion_key"].nunique()),
    )
    return {
        "ok": True,
        "session_dir": str(sd),
        "n_candidates": len(candidates),
        "n_combos": int(candidates["site_occasion_key"].nunique()),
    }


def replace_species_decisions(species_safe: str, confirmed_keys: list[str]) -> int:
    """Replace all decisions for a species with a corrected set and regenerate outputs.

    Deletes existing decision CSVs for the species, writes a fresh iter1.csv
    from confirmed_keys (using the rank-1 representative per key), then
    regenerates all output files.

    Returns:
        Number of confirmed keys saved.
    """
    logger.info(
        "Replacing decisions for %s: %d confirmed keys", species_safe, len(confirmed_keys)
    )
    p = session_service.paths()
    p["decisions"].mkdir(parents=True, exist_ok=True)
    candidates = session_service.get_candidates()
    sp_cands = candidates[candidates["species_safe"] == species_safe]

    for f in p["decisions"].glob(f"decisions_{species_safe}_iter*.csv"):
        f.unlink()

    if confirmed_keys:
        rank1 = sp_cands[sp_cands["rank"] == 1]
        confirmed_rows = []
        for key in confirmed_keys:
            key_cands = rank1[rank1["site_occasion_key"] == key]
            if not key_cands.empty:
                prob_col = pd.to_numeric(
                    key_cands["classificationProbability"], errors="coerce"
                ).fillna(0)
                confirmed_rows.append(key_cands.loc[prob_col.idxmax()])
        if confirmed_rows:
            cols = ["observationID", "site_occasion_key", "mediaID",
                    "scientificName", "siteID", "occasion"]
            csv_path = p["decisions"] / f"decisions_{species_safe}_iter1.csv"
            pd.DataFrame(confirmed_rows)[cols].to_csv(csv_path, index=False)

    rebuild_outputs()
    return len(confirmed_keys)
