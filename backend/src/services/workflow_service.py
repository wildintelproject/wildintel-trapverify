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
    build_false_positive_sources,
    build_species_effort,
    compute_min_score_exclusions,
    dataset_fingerprint,
    archive_stats,
    cell_states,
    compute_archive_stats,
    cleared_keys_set,
    cross_key,
    load_cross,
    load_all_decisions,
    remove_cross_confirmations,
    sanitize,
    set_cross_confirmation,
    load_all_unsure,
    confirmed_observations,
    resolve_pending,
    get_events,
    load_rejection_corrections,
    load_review_log,
    rounds_completed,
    clear_media_caches,
    export_verified_camtrapdp,
    find_flat_search_ambiguities,
    load_camtrapdp,
)
from fastapi import HTTPException
from occupancy_model import fit_naive_vs_verified

from schemas.requests import SetupRequest
from services import progress_service, session_service


EXPORT_STALE_MARKER = ".outputs_stale"
OUTPUTS_STALE_MARKER = ".outputs_all_stale"        # the histories, reports and fits too (a click that must answer at once)


def export_is_stale() -> bool:
    """True when ``camtrap_dp_verified/`` does not reflect the latest decisions."""
    sd = session_service.session_dir()
    return sd is not None and (sd / EXPORT_STALE_MARKER).exists()


def _corrections_by_observation(path: Path) -> dict[str, str]:
    """``observationID`` -> actual species typed for a rejected event (empty when none was recorded)."""
    corr = load_rejection_corrections(path)
    return dict(zip(corr["observationID"], corr["actual_species"])) if not corr.empty else {}


def write_verified_export() -> None:
    """Write ``camtrap_dp_verified/`` from the current decisions (rewrites the whole observations table)."""
    p = session_service.paths()
    config = session_service.get_config()
    export_verified_camtrapdp(
        Path(config["camtrap_dir"]), p["camtrap_out"], p["decisions"], session_service.get_rejected_media(),
        classified_by_label=config.get("classified_by", "expert_review"),
        extended_confirmation=bool(config.get("extended_confirmation", False)),
        candidates=session_service.get_candidates(),
        corrections=_corrections_by_observation(p["corrections"]),
    )
    (session_service.session_dir() / EXPORT_STALE_MARKER).unlink(missing_ok=True)


def mark_outputs_stale() -> None:
    """Mark every output (not only the verified CamtrapDP) as out of date, without rebuilding.

    For actions that must answer at once, like confirming another species from a photo: rebuilding the
    histories and fits of every species takes seconds on a long study. Saving a round or opening
    Results / downloading rebuilds them (:func:`ensure_export_fresh`).
    """
    sd = session_service.session_dir()
    if sd is not None:
        (sd / OUTPUTS_STALE_MARKER).write_text(datetime.now().isoformat())
        (sd / EXPORT_STALE_MARKER).write_text("")


def ensure_export_fresh() -> None:
    """Bring ``camtrap_dp_verified/`` up to date if saving a round left it stale.

    Saving a round only marks it stale (rewriting the whole observations table on every save is the
    slowest step on a large archive); it is rebuilt here, when the results are opened, downloaded
    or the session folder is opened.
    """
    sd = session_service.session_dir()
    if sd is None or session_service.get_config() is None:
        return
    if (sd / OUTPUTS_STALE_MARKER).exists():
        logger.info("Rebuilding every output (stale)")
        rebuild_outputs(export=True)
    elif export_is_stale() or not session_service.paths()["camtrap_out"].exists():
        logger.info("Rebuilding the verified CamtrapDP (stale)")
        write_verified_export()


def rebuild_outputs(export: bool = True) -> None:
    """Regenerate occupancy_inputs (and, unless deferred, camtrap_dp_verified) from the session state.

    With ``export=False`` the verified CamtrapDP is only marked stale; see :func:`ensure_export_fresh`.
    """
    logger.info("Rebuilding output files")
    p = session_service.paths()
    config = session_service.get_config()
    candidates = session_service.get_candidates()

    if "archive_stats" not in config:                      # a session made before they were stored: once
        stats = archive_stats(config)
        if stats:
            config["archive_stats"] = stats
            session_service.write_config_file(session_service.session_dir() / "config.json", config)
    if export:
        write_verified_export()
    else:
        (session_service.session_dir() / EXPORT_STALE_MARKER).write_text("")
    (session_service.session_dir() / OUTPUTS_STALE_MARKER).unlink(missing_ok=True)
    build_occupancy_inputs(candidates, p["decisions"], config, p["occupancy_out"])
    build_review_effort(candidates, p["decisions"], config, p["occupancy_out"])
    exclusions = pd.read_csv(p["exclusions"]) if p["exclusions"].exists() else None
    effort = build_species_effort(
        candidates, p["decisions"], p["occupancy_out"], rounds_completed(p["decisions"]),
        exclusions=exclusions,
        review_log=load_review_log(p["review_log"]),
        idle_seconds=int(config.get("review_idle_seconds", 120)),
    )
    build_false_positive_sources(effort, p["decisions"], p["corrections"], p["occupancy_out"])
    # Also with occasions in hours (as in the community fork); Results and the manual caution that
    # the estimate is not meaningful when the occasions are hours of the same day.
    fit_naive_vs_verified(p["occupancy_out"], config.get("target_species", []))
    logger.info("Output files rebuilt successfully")


def run_setup(req: SetupRequest) -> dict:
    """Execute the full setup workflow for a new session.

    The caller must verify that req.camtrap_dir exists before calling.

    Returns:
        Dict with ok, session_dir, n_candidates, n_combos.
    """
    logger.info("Starting setup: camtrap_dir=%s species=%s", req.camtrap_dir, req.target_species)
    clear_media_caches()
    camtrap_dir = Path(req.camtrap_dir)
    dep, med, obs = load_camtrapdp(camtrap_dir, minimal=True)

    if req.flat_search and req.image_base_dir:
        ambiguous = find_flat_search_ambiguities(med, req.image_base_dir)
        if ambiguous:
            examples = ", ".join(a["fileName"] for a in ambiguous[:5])
            logger.warning(
                "Setup aborted: %d ambiguous flat-search match(es) under %s",
                len(ambiguous), req.image_base_dir,
            )
            raise HTTPException(
                400,
                f"{len(ambiguous)} imagen(es) con nombre ambiguo bajo {req.image_base_dir} "
                f"(el mismo nombre de archivo aparece en varias carpetas y deploymentID no "
                f"lo distingue): {examples}. Corrige la estructura de carpetas o desactiva "
                "la búsqueda en subcarpetas antes de continuar.",
            )

    candidates = build_candidates(
        dep, med, obs,
        target_species=req.target_species,
        study_start=date.fromisoformat(req.study_start),
        study_end=date.fromisoformat(req.study_end),
        occasion_days=req.occasion_days,
        total_iterations=req.total_iterations,
        gap_seconds=req.gap_seconds,
        include_burst_context=req.include_burst_context,
        min_score=req.min_score,
        min_score_by_species=req.min_score_by_species,
        occasion_hours=req.occasion_hours or None,
        review_order=req.review_order,
    )

    if candidates.empty:
        raise HTTPException(
            400,
            "No queda ninguna detección candidata con estos parámetros (especies, periodo de estudio y "
            "puntuación mínima). Revisa el periodo y baja la puntuación mínima, general o de la especie.",
        )

    base_out = Path(req.output_dir) if req.output_dir else session_service.DEFAULT_OUTPUT_DIR
    sd = base_out / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    sd.mkdir(parents=True, exist_ok=True)

    config = req.model_dump()
    config["session_name"] = session_service.clean_session_name(req.session_name)
    config["dataset_fingerprint"] = dataset_fingerprint(camtrap_dir)     # recognises the same data on another computer
    config["archive_stats"] = compute_archive_stats(obs, req.target_species)     # sized once, not on every save
    config["camtrap_dir"] = str(camtrap_dir.resolve())
    config["output_dir"] = str(base_out)
    config["session_dir"] = str(sd)

    (sd / "config.json").write_text(json.dumps(config, indent=2))
    candidates.to_csv(sd / "candidate_manifest.csv", index=False)
    compute_min_score_exclusions(
        candidates, dep, med, obs,
        target_species=req.target_species,
        study_start=date.fromisoformat(req.study_start),
        study_end=date.fromisoformat(req.study_end),
        occasion_days=req.occasion_days,
        total_iterations=req.total_iterations,
        gap_seconds=req.gap_seconds,
        min_score=req.min_score,
        min_score_by_species=req.min_score_by_species,
        occasion_hours=req.occasion_hours or None,
        review_order=req.review_order,
    ).to_csv(sd / "min_score_exclusions.csv", index=False)

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
    from confirmed_keys (keeping the detection event already confirmed for a
    cell, or the rank-1 representative for a newly confirmed one), then
    regenerates all output files.

    The number of rounds already done is preserved (an empty file for the last
    round is kept), so cells the expert leaves unconfirmed stay settled as "not
    detected" instead of re-opening for review.

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
    rounds_done = rounds_completed(p["decisions"]).get(species_safe, 0)
    previous = confirmed_observations(p["decisions"], sp_cands)       # cell -> event already confirmed

    # Cells pending expert review before the edit are settled by it.
    states = cell_states(sp_cands, p["decisions"])
    was_pending = set(states.loc[states["status"] == "pending", "site_occasion_key"])
    flagged = set(load_all_unsure(p["decisions"], species_safe)["site_occasion_key"].dropna())

    for pattern in (f"decisions_{species_safe}_iter*.csv", f"decisions_{species_safe}_pending.csv"):
        for f in p["decisions"].glob(pattern):
            f.unlink()

    if confirmed_keys:
        rank1 = sp_cands[sp_cands["rank"] == 1]
        obs_ids = sp_cands["observationID"].astype(str)
        confirmed_rows = []
        for key in confirmed_keys:
            if key in previous:                                       # keep the event that was confirmed
                kept = sp_cands[obs_ids == previous[key]]
                if not kept.empty:
                    confirmed_rows.append(kept.iloc[0])
                    continue
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

    # Keep the number of rounds done: an empty file for the last round if the edit left none.
    last_round = p["decisions"] / f"decisions_{species_safe}_iter{max(rounds_done, 1)}.csv"
    if rounds_done and not last_round.exists():
        pd.DataFrame(columns=["observationID", "site_occasion_key", "mediaID",
                              "scientificName", "siteID", "occasion"]).to_csv(last_round, index=False)

    # Unsure cells the edit left unconfirmed are settled as not detected (they no longer wait for a verdict).
    settled = sorted((flagged | was_pending) - set(confirmed_keys))
    if settled:
        cleared = p["decisions"] / f"unsure_cleared_{species_safe}.csv"
        existing = pd.read_csv(cleared, dtype=str) if cleared.exists() else pd.DataFrame(columns=["site_occasion_key"])
        pd.concat([existing, pd.DataFrame({"site_occasion_key": settled})]).drop_duplicates("site_occasion_key").to_csv(cleared, index=False)

    # Cells of this species confirmed from another species' gallery that the expert has now left
    # unconfirmed in this review are dropped too.
    shown = set(sp_cands["site_occasion_key"])
    remove_cross_confirmations(p["decisions"], species_safe, shown - set(confirmed_keys))

    # Remember the species was edited as a whole: the rounds no longer describe what was decided
    # in each, so the last one cannot be reopened any more.
    pd.DataFrame({"edited_at": [datetime.now().isoformat(timespec="seconds")]}).to_csv(
        p["decisions"] / f"edited_{species_safe}.csv", index=False)
    progress_service.clear_progress(p["decisions"], species_safe)
    rebuild_outputs()
    return len(confirmed_keys)


def settle_pending(species_safe: str, confirmed_ids: list[str], rejected_keys: list[str]) -> dict:
    """Apply an expert's verdict on pending cells and refresh the outputs."""
    p = session_service.paths()
    n_conf, n_rej = resolve_pending(
        p["decisions"], session_service.get_candidates(), species_safe, confirmed_ids, rejected_keys,
    )
    progress_service.clear_progress(p["decisions"], species_safe, "pending", 0)
    rebuild_outputs(export=False)
    logger.info("Pending cells settled for %s: confirmed=%d rejected=%d", species_safe, n_conf, n_rej)
    return {"success": True, "confirmed": n_conf, "rejected": n_rej}


# ─── Confirming another species from a photo ─────────────────────────────────

def _target_species() -> list[str]:
    return list((session_service.get_config() or {}).get("target_species", []))


def cross_status(site_id: str, occasion: int) -> list[dict]:
    """State of every target species at one site and occasion.

    ``status`` is ``cross`` (confirmed from a photo of another species, with that photo's mediaID),
    ``confirmed`` (confirmed in its own review) or ``none``. ``has_candidates`` tells whether the
    classifier flagged the species there: a confirmation where it did not is kept apart ("added";
    see ``camtrap_workflow.added_cross_keys``).
    """
    d = session_service.paths()["decisions"]
    cands = session_service.get_candidates()
    cand_keys = set(cands["site_occasion_key"]) if cands is not None else set()
    dec = load_all_decisions(d) if d.exists() else pd.DataFrame()
    own = set(dec["site_occasion_key"].dropna()) if "site_occasion_key" in dec.columns else set()
    cross = load_cross(d).set_index("site_occasion_key") if d.exists() else pd.DataFrame()
    out = []
    for sp in _target_species():
        sp_safe = sanitize(sp)
        key = cross_key(site_id, occasion, sp_safe)
        item = {"scientificName": sp, "species_safe": sp_safe, "status": "none",
                "has_candidates": key in cand_keys}
        if key in own:
            item["status"] = "confirmed"
        elif not cross.empty and key in cross.index:
            row = cross.loc[key]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[-1]
            item.update(status="cross", mediaID=row["mediaID"], observationID=row["observationID"],
                        source=row["source_scientificName"])
        out.append(item)
    return out


def add_cross(species: str, site_id: str, occasion: int, media_id: str,
              observation_id: str, source_species: str) -> dict:
    if species not in _target_species():
        raise HTTPException(400, f"{species} no es una especie objetivo de esta sesión.")
    if species == source_species:
        raise HTTPException(400, "Para la especie que se está revisando usa Confirmada.")
    key = set_cross_confirmation(
        session_service.paths()["decisions"], species, site_id, occasion, media_id, observation_id, source_species,
    )
    mark_outputs_stale()
    cands = session_service.get_candidates()
    added = cands is not None and key not in set(cands["site_occasion_key"])
    logger.info("Cross-species confirmation: %s from a photo of %s (%s)%s", key, source_species, media_id,
                " [no candidates: added]" if added else "")
    return {"success": True, "key": key, "added": added}


def remove_cross(species: str, site_id: str, occasion: int) -> dict:
    sp_safe = sanitize(species)
    n = remove_cross_confirmations(
        session_service.paths()["decisions"], sp_safe, {cross_key(site_id, occasion, sp_safe)},
    )
    if n:
        mark_outputs_stale()
    return {"success": True, "removed": n}


def reopen_last_round(species_safe: str) -> dict:
    """Re-open the last finished round of a species so it can be corrected.

    The round's decision files are moved to ``decisions/reopened/`` (a backup the app never
    reads) and its decisions, actual-species corrections and decision times become the saved
    progress of that round, so the gallery shows them exactly as they were. Progress of the
    round that was being reviewed is kept. Finishing the re-opened round again writes the same
    files as deciding it once.
    """
    p = session_service.paths()
    d = p["decisions"]
    rounds = rounds_completed(d).get(species_safe, 0)
    if rounds < 1:
        raise HTTPException(400, "Esta especie no tiene ninguna ronda terminada.")
    if (d / f"edited_{species_safe}.csv").exists():
        raise HTTPException(
            400,
            "Las decisiones de esta especie se han editado en bloque; para corregir algo, "
            "usa la edición de la especie (candado).",
        )
    if (d / f"decisions_{species_safe}_pending.csv").exists() or (d / f"unsure_cleared_{species_safe}.csv").exists():
        raise HTTPException(
            400,
            "Ya se han resuelto ocasiones pendientes de revisión por un experto; para corregir algo, "
            "usa la edición de la especie (candado) cuando esté completa.",
        )
    dec_file = d / f"decisions_{species_safe}_iter{rounds}.csv"
    unc_file = d / f"unsure_{species_safe}_iter{rounds}.csv"
    confirmed_ids = set(pd.read_csv(dec_file, dtype=str)["observationID"].dropna()) if dec_file.exists() else set()
    unsure_ids = set(pd.read_csv(unc_file, dtype=str)["observationID"].dropna()) if unc_file.exists() else set()

    backup = d / "reopened"
    backup.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for f in (dec_file, unc_file):
        if f.exists():
            f.replace(backup / f"{f.stem}.{stamp}.bak")

    candidates = session_service.get_candidates()
    events = get_events(candidates, d, session_service.get_rejected_media(), species_safe, rounds)

    def _of(ev: dict, ids: set[str]) -> bool:
        return ev["repObsId"] in ids or any(f["obsId"] in ids for f in ev["frames"])

    decisions = {
        ev["key"]: "confirmed" if _of(ev, confirmed_ids) else "unsure" if _of(ev, unsure_ids) else "rejected"
        for ev in events
    }
    corr = load_rejection_corrections(p["corrections"])
    corr = corr[(corr["species_safe"] == species_safe) & (corr["iteration"] == str(rounds))]
    corrections = {k: t for k, t in zip(corr["site_occasion_key"], corr["actual_species"]) if k in decisions}
    log = load_review_log(p["review_log"])
    times: dict[str, int] = {}
    if not log.empty:
        mine = log[(log["species_safe"] == species_safe) & (log["iteration"] == str(rounds))]
        for k, at in zip(mine["site_occasion_key"], mine["decided_at"]):
            if k in decisions and at:
                times[k] = int(pd.Timestamp(at).timestamp() * 1000)
    progress_service.save_progress(d, species_safe, "rounds", rounds, decisions, {}, corrections, times)
    rebuild_outputs()
    logger.info("Round %d of %s re-opened (%d decisions restored)", rounds, species_safe, len(decisions))
    return {"success": True, "iteration": rounds, "restored": len(decisions)}
