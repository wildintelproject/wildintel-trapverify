"""
CamTrap Verify — backend workflow.

Port of the R verification pipeline to Python/pandas. Handles loading a
CamtrapDP dataset, building the ranked candidate manifest, persisting expert
decisions, and generating the verified CamtrapDP and occupancy-model inputs.
"""
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd


# ─── Helpers ──────────────────────────────────────────────────────────────────

def sanitize(name: str) -> str:
    """Replace non-alphanumeric characters with underscores.

    Used to produce safe filenames and DataFrame key suffixes from scientific
    names (e.g. ``'Vulpes vulpes'`` → ``'Vulpes_vulpes'``).

    Args:
        name: Arbitrary string to sanitize.

    Returns:
        String with every character outside ``[A-Za-z0-9]`` replaced by ``_``.
    """
    return re.sub(r"[^A-Za-z0-9]", "_", name)


def normalise_ts(x: str) -> str:
    """Convert an EXIF timestamp to ISO-8601 format.

    EXIF stores dates as ``'YYYY:MM:DD HH:MM:SS'``; this converts the date
    separator from ``:`` to ``-``. Already-ISO strings are returned unchanged.

    Args:
        x: Timestamp string, either EXIF (``'YYYY:MM:DD …'``) or ISO-8601.

    Returns:
        ISO-8601 timestamp string ``'YYYY-MM-DD HH:MM:SS'``.
    """
    return re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", str(x))


# ─── CamtrapDP I/O ────────────────────────────────────────────────────────────

def load_camtrapdp(camtrap_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the three core CamtrapDP tables from a directory.

    All columns are kept as ``str`` to avoid silent type coercions on IDs.

    Args:
        camtrap_dir: Path to the directory containing ``deployments.csv``,
            ``media.csv`` and ``observations.csv``.

    Returns:
        Tuple of ``(deployments, media, observations)`` DataFrames.
    """
    dep = pd.read_csv(camtrap_dir / "deployments.csv", dtype=str)
    med = pd.read_csv(camtrap_dir / "media.csv", dtype=str)
    obs = pd.read_csv(camtrap_dir / "observations.csv", dtype=str)
    return dep, med, obs


def detect_site_col(dep: pd.DataFrame) -> str:
    """Detect the site identifier column in a deployments DataFrame.

    Prefers ``locationID`` when the column exists and contains at least one
    non-empty value; otherwise falls back to ``deploymentID``.

    Args:
        dep: Deployments DataFrame as read from ``deployments.csv``.

    Returns:
        Column name: ``'locationID'`` or ``'deploymentID'``.
    """
    if "locationID" in dep.columns:
        valid = dep["locationID"].dropna()
        valid = valid[valid != ""]
        if len(valid) > 0:
            return "locationID"
    return "deploymentID"


# ─── DeepFaune → CamtrapDP ────────────────────────────────────────────────────

def deepfaune_to_camtrapdp(
    df: pd.DataFrame,
    species_map: dict,
    out_dir: Path,
    image_base_dir: Optional[Path] = None,
    label_col: str = "top1",
    min_score: float = 0.0,
) -> Path:
    """Convert a DeepFaune results CSV to CamtrapDP format.

    Writes ``deployments.csv``, ``media.csv`` and ``observations.csv`` to
    ``out_dir``. Non-animal labels (empty, human, undefined) are mapped to the
    appropriate CamtrapDP ``observationType`` values. Rows below ``min_score``
    are included but with ``scientificName=None``.

    Args:
        df: DeepFaune results DataFrame (one row per image).
        species_map: Mapping from DeepFaune label (lowercase) to scientific name.
        out_dir: Destination directory for the CamtrapDP files.
        image_base_dir: Base directory prepended to relative ``filename`` paths.
            If ``None``, paths are used as-is.
        label_col: Column in ``df`` holding the predicted label. Defaults to
            ``'top1'``.
        min_score: Minimum confidence score to assign a scientific name.
            Rows below this threshold get ``scientificName=None``.

    Returns:
        Path to ``out_dir`` (the written CamtrapDP directory).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    nonanimal = {
        "empty": "blank", "vide": "blank", "human": "human",
        "humain": "human", "undefined": "unclassified",
    }

    def abs_path(p: str) -> str:
        p = p.replace("\\", "/")
        if image_base_dir and not (p.startswith("/") or (len(p) > 1 and p[1] == ":")):
            p = str(image_base_dir / p)
        return str(Path(p).resolve())

    def site_from_path(p: str) -> str:
        return re.sub(r"^R\d+-", "", Path(p).parent.name)

    paths = df["filename"].astype(str).apply(abs_path)
    sites = df["site"].astype(str) if "site" in df.columns else paths.apply(site_from_path)
    labels = df[label_col].astype(str).str.lower().str.strip()
    scores = pd.to_numeric(df.get("score", pd.Series([None] * len(df))), errors="coerce")
    timestamps = df["date"].astype(str).apply(normalise_ts)

    n = len(df)
    media_ids = [f"m{i:07d}" for i in range(1, n + 1)]
    obs_ids = [f"o{i:07d}" for i in range(1, n + 1)]

    sci_names, obs_types = [], []
    for label, score in zip(labels, scores):
        if label in nonanimal:
            sci_names.append(None)
            obs_types.append(nonanimal[label])
        else:
            sn = species_map.get(label, label)
            obs_types.append("animal")
            if min_score > 0 and (pd.isna(score) or score < min_score):
                sci_names.append(None)
            else:
                sci_names.append(sn)

    unique_sites = sorted(set(sites))
    pd.DataFrame({"deploymentID": unique_sites, "locationID": unique_sites,
                  "locationName": unique_sites}).to_csv(out_dir / "deployments.csv", index=False)
    pd.DataFrame({"mediaID": media_ids, "deploymentID": list(sites),
                  "timestamp": list(timestamps), "filePath": list(paths)}).to_csv(
        out_dir / "media.csv", index=False)
    pd.DataFrame({
        "observationID": obs_ids, "deploymentID": list(sites), "mediaID": media_ids,
        "observationLevel": "media", "observationType": obs_types,
        "scientificName": sci_names, "classificationProbability": list(scores),
        "classificationMethod": "machine", "classifiedBy": "DeepFaune",
        "classificationTimestamp": None,
    }).to_csv(out_dir / "observations.csv", index=False)
    return out_dir


# ─── Build candidate manifest ─────────────────────────────────────────────────

def build_candidates(
    dep: pd.DataFrame,
    med: pd.DataFrame,
    obs: pd.DataFrame,
    target_species: list[str],
    study_start: date,
    study_end: date,
    occasion_days: int,
    total_iterations: int,
    gap_seconds: int = 60,
) -> pd.DataFrame:
    """Build the verification candidate manifest from CamtrapDP tables.

    Filters observations to ``target_species`` within the study window, assigns
    each frame to a sampling occasion (fixed-width breaks of ``occasion_days``),
    groups frames into sequences (bursts separated by more than ``gap_seconds``),
    and ranks bursts by maximum classification probability within each
    site × occasion × species cell (rank 1 = highest confidence).

    Args:
        dep: Deployments DataFrame (from ``load_camtrapdp``).
        med: Media DataFrame (from ``load_camtrapdp``).
        obs: Observations DataFrame (from ``load_camtrapdp``).
        target_species: Scientific names to include.
        study_start: First date of the study period (inclusive).
        study_end: Last date of the study period (inclusive).
        occasion_days: Width of each sampling occasion in days.
        total_iterations: Maximum number of bursts to keep per cell (caps rank).
        gap_seconds: Maximum gap in seconds between frames of the same burst.
            Defaults to 60.

    Returns:
        DataFrame with one row per candidate frame, including columns
        ``site_occasion_key``, ``rank``, ``burst_id``, ``burst_seq``,
        ``observationID``, ``mediaID``, ``filePath``, ``classificationProbability``,
        ``scientificName``, ``siteID``, ``occasion``, ``species_safe``,
        ``ts`` and ``timestamp_display``.
        Returns an empty DataFrame if no candidates match the filters.
    """
    site_col = detect_site_col(dep)

    med = med.copy()
    med["ts"] = pd.to_datetime(
        med["timestamp"].apply(normalise_ts), errors="coerce", utc=False
    )

    target_obs = obs[
        (obs["observationLevel"] == "media")
        & (obs["observationType"] == "animal")
        & (obs["scientificName"].isin(target_species))
    ].copy()

    joined = (
        target_obs
        .merge(med[["mediaID", "filePath", "ts"]], on="mediaID", how="left")
        .merge(
            dep[["deploymentID", site_col]].rename(columns={site_col: "siteID"}),
            on="deploymentID", how="left",
        )
    )

    joined = joined[
        joined["ts"].notna()
        & (joined["ts"].dt.date >= study_start)
        & (joined["ts"].dt.date <= study_end)
    ].copy()

    if joined.empty:
        return pd.DataFrame()

    # Build occasion breaks
    breaks = []
    d = study_start
    while d <= study_end + timedelta(days=1):
        breaks.append(d)
        d += timedelta(days=occasion_days)
    n_occ = len(breaks) - 1

    def assign_occ(ts: pd.Timestamp) -> int:
        dt = ts.date()
        for i in range(len(breaks) - 1):
            if breaks[i] <= dt < breaks[i + 1]:
                return i + 1
        return n_occ if dt == breaks[-1] else -1

    joined["occasion"] = joined["ts"].apply(assign_occ)
    joined = joined[joined["occasion"] >= 1].copy()

    joined["species_safe"] = joined["scientificName"].apply(sanitize)
    joined["site_occasion_key"] = (
        joined["siteID"].astype(str)
        + "_occ" + joined["occasion"].astype(str)
        + "_" + joined["species_safe"]
    )
    joined["prob"] = pd.to_numeric(
        joined["classificationProbability"], errors="coerce"
    ).fillna(0)
    joined = joined.sort_values(["site_occasion_key", "ts"])

    # Assign burst IDs (consecutive frames within gap_seconds form one burst)
    records = []
    for _, group in joined.groupby("site_occasion_key", sort=False):
        group = group.copy().reset_index(drop=True)
        burst_id = 0
        bids = [0]
        for i in range(1, len(group)):
            prev, curr = group["ts"].iloc[i - 1], group["ts"].iloc[i]
            if pd.isna(prev) or pd.isna(curr) or (curr - prev).total_seconds() > gap_seconds:
                burst_id += 1
            bids.append(burst_id)
        group["burst_id"] = bids
        records.append(group)

    if not records:
        return pd.DataFrame()

    joined = pd.concat(records, ignore_index=True)

    # Rank bursts by max prob within each cell (highest prob = rank 1)
    burst_max = (
        joined.groupby(["site_occasion_key", "burst_id"])["prob"]
        .max()
        .reset_index(name="burst_max_prob")
    )
    burst_max["rank"] = (
        burst_max.groupby("site_occasion_key")["burst_max_prob"]
        .rank(method="first", ascending=False)
        .astype(int)
    )

    joined = joined.merge(burst_max[["site_occasion_key", "burst_id", "rank"]],
                          on=["site_occasion_key", "burst_id"])
    joined["burst_seq"] = (
        joined.groupby(["site_occasion_key", "burst_id"]).cumcount() + 1
    )

    candidates = joined[joined["rank"] <= total_iterations].copy()
    candidates["timestamp_display"] = candidates["ts"].dt.strftime("%Y-%m-%d %H:%M")

    return candidates[[
        "site_occasion_key", "rank", "burst_id", "burst_seq",
        "observationID", "mediaID", "filePath",
        "classificationProbability", "scientificName", "deploymentID",
        "siteID", "occasion", "species_safe", "ts", "timestamp_display",
    ]]


# ─── Decision persistence ─────────────────────────────────────────────────────

def load_all_decisions(decisions_dir: Path) -> pd.DataFrame:
    """Concatenate all ``decisions_*.csv`` files from the decisions directory.

    Args:
        decisions_dir: Directory containing per-species, per-round decision CSVs.

    Returns:
        Single DataFrame with all decisions, or an empty DataFrame with the
        expected columns if no files exist.
    """
    files = list(decisions_dir.glob("decisions_*.csv"))
    if not files:
        return pd.DataFrame(columns=[
            "observationID", "site_occasion_key", "mediaID",
            "scientificName", "siteID", "occasion",
        ])
    return pd.concat([pd.read_csv(f, dtype=str) for f in files], ignore_index=True)


def confirmed_keys_set(decisions_dir: Path) -> set[str]:
    """Return the set of confirmed ``site_occasion_key`` values across all decision files.

    Args:
        decisions_dir: Directory containing decision CSVs.

    Returns:
        Set of confirmed keys, empty if no decisions exist.
    """
    dec = load_all_decisions(decisions_dir)
    if dec.empty:
        return set()
    return set(dec["site_occasion_key"].dropna().unique())


def save_decisions(
    decisions_dir: Path,
    candidates: pd.DataFrame,
    species_safe: str,
    iteration: int,
    confirmed_ids: list[str],
) -> pd.DataFrame:
    """Persist confirmed observation IDs to ``decisions_{species_safe}_iter{N}.csv``.

    Writes an empty file when ``confirmed_ids`` is empty so the round is
    recorded and the species does not regress to a previous state.

    Args:
        decisions_dir: Directory where decision CSVs are stored.
        candidates: Full candidate manifest (used to look up metadata by ID).
        species_safe: Sanitized species name used in the filename.
        iteration: Round number used in the filename.
        confirmed_ids: List of ``observationID`` values confirmed by the expert.

    Returns:
        DataFrame of the confirmed rows that was written to disk.
    """
    decisions_dir.mkdir(parents=True, exist_ok=True)
    path = decisions_dir / f"decisions_{species_safe}_iter{iteration}.csv"
    cols = ["observationID", "site_occasion_key", "mediaID",
            "scientificName", "siteID", "occasion"]
    if not confirmed_ids:
        df = candidates.iloc[0:0][cols]
    else:
        df = candidates[candidates["observationID"].isin(confirmed_ids)][cols]
    df.to_csv(path, index=False)
    return df


# ─── Species stats for index page ─────────────────────────────────────────────

def species_stats(
    candidates: pd.DataFrame,
    decisions_dir: Path,
    total_iterations: int,
) -> list[dict]:
    """Compute per-species progress statistics for the index page.

    A cell is considered *resolved* when it is confirmed OR all of its available
    ranks have been reviewed (``max_rank <= rounds_done``). ``n_resolved`` drives
    the progress bar and the "Completo" badge.

    Args:
        candidates: Full candidate manifest DataFrame.
        decisions_dir: Directory containing decision CSVs.
        total_iterations: Maximum number of rounds configured for the session.

    Returns:
        List of dicts, one per species, with keys ``species_name``,
        ``species_safe``, ``n_total_combos``, ``n_confirmed_combos``,
        ``n_resolved`` and ``current_iteration``.
    """
    conf_keys = confirmed_keys_set(decisions_dir)

    iter_by_sp: dict[str, int] = {}
    for f in decisions_dir.glob("*.csv"):
        m = re.match(r"decisions_(.+)_iter(\d+)\.csv", f.name)
        if m:
            sp, it = m.group(1), int(m.group(2))
            iter_by_sp[sp] = max(iter_by_sp.get(sp, 0), it)

    result = []
    for sp_safe, grp in candidates.groupby("species_safe"):
        sp_name = grp["scientificName"].iloc[0]
        all_keys = set(grp["site_occasion_key"].unique())
        max_rank = grp.groupby("site_occasion_key")["rank"].max()
        R = iter_by_sp.get(str(sp_safe), 0)
        resolved = sum(
            1 for k in all_keys
            if k in conf_keys or max_rank.get(k, 0) <= R
        )
        result.append({
            "species_name": sp_name,
            "species_safe": str(sp_safe),
            "n_total_combos": len(all_keys),
            "n_confirmed_combos": sum(1 for k in all_keys if k in conf_keys),
            "n_resolved": resolved,
            "current_iteration": R + 1,
        })
    return result


# ─── Events for gallery ───────────────────────────────────────────────────────

def get_events(
    candidates: pd.DataFrame,
    decisions_dir: Path,
    rejected_media: set[str],
    species_safe: str,
    iteration: int,
) -> list[dict]:
    """Return pending gallery events for a species in a given verification round.

    Only returns cells at the requested rank that are not yet confirmed and whose
    media have not been manually rejected. Each event carries all frames of the
    representative burst plus metadata for the UI card.

    Args:
        candidates: Full candidate manifest DataFrame.
        decisions_dir: Directory containing decision CSVs.
        rejected_media: Set of ``mediaID`` values excluded from the gallery.
        species_safe: Sanitized species name to filter by.
        iteration: Round number (equals the burst rank to show).

    Returns:
        List of event dicts with keys ``key``, ``siteId``, ``occasion``,
        ``rank``, ``totalSeqs``, ``repObsId``, ``maxProb`` and ``frames``
        (list of frame dicts with ``obsId``, ``mediaId``, ``img``, ``ts``,
        ``prob``).
    """
    conf_keys = confirmed_keys_set(decisions_dir)

    sp_cands = candidates[
        (candidates["species_safe"] == species_safe)
        & (candidates["rank"] == iteration)
        & (~candidates["site_occasion_key"].isin(conf_keys))
        & (~candidates["mediaID"].isin(rejected_media))
    ].copy()

    # Total de secuencias disponibles por período (sin filtrar por ronda)
    all_sp = candidates[candidates["species_safe"] == species_safe]
    total_seqs_by_key = all_sp.groupby("site_occasion_key")["rank"].max().to_dict()

    events = []
    for key, group in sp_cands.sort_values(["burst_id", "burst_seq"]).groupby(
        "site_occasion_key", sort=False
    ):
        group = group.sort_values(["burst_id", "burst_seq"])
        prob_col = pd.to_numeric(group["classificationProbability"], errors="coerce").fillna(0)
        rep_idx = prob_col.idxmax()
        rep_obs = group.loc[rep_idx, "observationID"]
        max_prob = float(prob_col.max())

        frames = []
        for _, row in group.iterrows():
            fp = str(row["filePath"])
            img_url = (
                f'/api/proxy-image?url={fp}'
                if fp.startswith("http")
                else f'/api/image/{row["mediaID"]}'
            )
            frames.append({
                "obsId": row["observationID"],
                "mediaId": str(row["mediaID"]),
                "img": img_url,
                "ts": row["timestamp_display"] if pd.notna(row.get("timestamp_display")) else "",
                "prob": round(float(prob_col.loc[row.name]), 3),
            })

        events.append({
            "key": key,
            "siteId": str(group["siteID"].iloc[0]),
            "occasion": int(group["occasion"].iloc[0]),
            "rank": int(group["rank"].iloc[0]),
            "totalSeqs": int(total_seqs_by_key.get(key, 1)),
            "repObsId": rep_obs,
            "maxProb": max_prob,
            "frames": frames,
        })

    return events


def get_review_events(
    species_cands: pd.DataFrame,
    decisions_dir: Path,
) -> list[dict]:
    """Return all cells for a completed species with their decision status.

    Uses rank-1 frames for display (highest-confidence burst per cell). Each
    event includes a ``status`` field so the review screen can pre-mark cards
    as confirmed or not confirmed without reloading decisions separately.

    Used by the locked review screen so the expert can audit or correct
    decisions without starting a new session.

    Args:
        species_cands: Candidate manifest already filtered to a single species.
        decisions_dir: Directory containing decision CSVs.

    Returns:
        List of event dicts (same structure as :func:`get_events`) with an
        additional ``status`` key: ``'confirmed'`` or ``'not_confirmed'``.
        Sorted by ``siteId`` then ``occasion``.
    """
    conf_keys = confirmed_keys_set(decisions_dir)
    rank1 = species_cands[species_cands["rank"] == 1].copy()
    total_seqs_by_key = species_cands.groupby("site_occasion_key")["rank"].max().to_dict()

    events = []
    for key, group in rank1.sort_values(["burst_id", "burst_seq"]).groupby(
        "site_occasion_key", sort=False
    ):
        group = group.sort_values(["burst_id", "burst_seq"])
        prob_col = pd.to_numeric(group["classificationProbability"], errors="coerce").fillna(0)
        rep_idx = prob_col.idxmax()
        rep_obs = group.loc[rep_idx, "observationID"]
        max_prob = float(prob_col.max())

        frames = []
        for _, row in group.iterrows():
            fp = str(row["filePath"])
            img_url = (
                f'/api/proxy-image?url={fp}'
                if fp.startswith("http")
                else f'/api/image/{row["mediaID"]}'
            )
            frames.append({
                "obsId": row["observationID"],
                "mediaId": str(row["mediaID"]),
                "img": img_url,
                "ts": row["timestamp_display"] if pd.notna(row.get("timestamp_display")) else "",
                "prob": round(float(prob_col.loc[row.name]), 3),
            })

        events.append({
            "key": key,
            "siteId": str(group["siteID"].iloc[0]),
            "occasion": int(group["occasion"].iloc[0]),
            "rank": 1,
            "totalSeqs": int(total_seqs_by_key.get(key, 1)),
            "repObsId": rep_obs,
            "maxProb": max_prob,
            "frames": frames,
            "status": "confirmed" if key in conf_keys else "not_confirmed",
        })

    events.sort(key=lambda e: (e["siteId"], e["occasion"]))
    return events


# ─── Export verified CamtrapDP ────────────────────────────────────────────────

def export_verified_camtrapdp(
    camtrap_dir: Path,
    out_dir: Path,
    decisions_dir: Path,
    rejected_media: set,
    classified_by_label: str = "expert_review",
) -> None:
    """Write ``camtrap_dp_verified/``, replicating R's ``update_metadata()`` + ``export_results()``.

    ``deployments.csv`` and ``media.csv`` are copied unchanged. In
    ``observations.csv`` only the representative observation of each confirmed
    sequence is updated: ``classificationMethod='human'``,
    ``classificationProbability=1.0``, ``classifiedBy``, and
    ``classificationTimestamp`` (UTC). No ``verificationStatus`` column is added.

    Args:
        camtrap_dir: Source CamtrapDP directory.
        out_dir: Destination directory (created if absent).
        decisions_dir: Directory containing decision CSVs.
        rejected_media: Set of manually rejected ``mediaID`` values (not used
            for the export itself, kept for API symmetry).
        classified_by_label: Value written to ``classifiedBy`` on confirmed
            observations. Defaults to ``'expert_review'``.
    """
    import shutil
    from datetime import datetime, timezone

    out_dir.mkdir(parents=True, exist_ok=True)

    # deployments y media se copian sin cambios
    for name in ("deployments.csv", "media.csv"):
        src = camtrap_dir / name
        if src.exists():
            shutil.copy2(src, out_dir / name)

    # Cargar observaciones originales
    obs = pd.read_csv(camtrap_dir / "observations.csv", dtype=str)

    # IDs de observaciones confirmadas (repObsId de cada decisión)
    confirmed_ids: set[str] = set()
    if decisions_dir.exists():
        for f in decisions_dir.glob("decisions_*_iter*.csv"):
            df = pd.read_csv(f, dtype=str)
            if "observationID" in df.columns:
                confirmed_ids.update(df["observationID"].dropna().tolist())

    if confirmed_ids:
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        mask = obs["observationID"].isin(confirmed_ids)
        obs.loc[mask, "classificationMethod"] = "human"
        obs.loc[mask, "classificationProbability"] = "1.0"
        obs.loc[mask, "classifiedBy"] = classified_by_label
        obs.loc[mask, "classificationTimestamp"] = now_ts

    obs.to_csv(out_dir / "observations.csv", index=False)


# ─── Occasion windows helper ──────────────────────────────────────────────────

def _occasion_windows(
    study_start: date, study_end: date, occasion_days: int
) -> list[tuple[date, date]]:
    """Split the study period into consecutive fixed-width windows.

    Args:
        study_start: First day of the study period.
        study_end: Last day of the study period (inclusive).
        occasion_days: Width of each window in days.

    Returns:
        List of ``(lo, hi)`` date tuples. The last window is clipped to
        ``study_end`` so it may be shorter than ``occasion_days``.
    """
    windows: list[tuple[date, date]] = []
    d = study_start
    while d <= study_end:
        hi = min(d + timedelta(days=occasion_days - 1), study_end)
        windows.append((d, hi))
        d += timedelta(days=occasion_days)
    return windows


# ─── Occupancy inputs ─────────────────────────────────────────────────────────

def build_occupancy_inputs(
    candidates: pd.DataFrame,
    decisions_dir: Path,
    config: dict,
    out_dir: Path,
) -> None:
    """Generate occupancy-model input files, replicating R's ``build_occupancy_inputs()``.

    Outputs written to ``out_dir``:

    * ``camera_operation.csv`` — days active per site × occasion, computed from
      ``deploymentStart``/``deploymentEnd`` in ``deployments.csv`` when available;
      falls back to the full occasion length otherwise.
    * ``dethist_naive_<sp>.csv`` — 1/0/NA detection history trusting the classifier.
    * ``dethist_verified_<sp>.csv`` — 1/0/NA detection history using only
      human-confirmed detections.
    * ``verification_summary.csv`` — per-species summary with ``psi_obs`` naive
      vs. verified.

    Args:
        candidates: Full candidate manifest DataFrame.
        decisions_dir: Directory containing decision CSVs.
        config: Session configuration dict (requires keys ``study_start``,
            ``study_end``, ``occasion_days``, ``target_species``,
            ``camtrap_dir``).
        out_dir: Destination directory (created if absent).
    """
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)

    study_start    = date.fromisoformat(config["study_start"])
    study_end      = date.fromisoformat(config["study_end"])
    occasion_days  = int(config["occasion_days"])
    target_species = config["target_species"]

    sites     = sorted(candidates["siteID"].astype(str).unique())
    n_sites   = len(sites)
    windows   = _occasion_windows(study_start, study_end, occasion_days)
    n_occ     = len(windows)
    occ_cols  = [f"occ{j + 1}" for j in range(n_occ)]

    # ── Camera operation matrix (días activos por sitio × ocasión) ──────────
    op = np.zeros((n_sites, n_occ), dtype=int)

    # Intentar usar deploymentStart/End de deployments.csv
    dep_path = Path(config["camtrap_dir"]) / "deployments.csv"
    activity: dict[str, list[tuple[date, date]]] = {}
    if dep_path.exists():
        dep = pd.read_csv(dep_path, dtype=str)
        site_col = detect_site_col(dep)
        if "deploymentStart" in dep.columns and "deploymentEnd" in dep.columns:
            for _, row in dep.iterrows():
                s = str(row[site_col])
                try:
                    s_d = date.fromisoformat(str(row["deploymentStart"])[:10])
                    e_d = date.fromisoformat(str(row["deploymentEnd"])[:10])
                    activity.setdefault(s, []).append((s_d, e_d))
                except Exception:
                    pass

    for i, site in enumerate(sites):
        periods = activity.get(site, [])
        for j, (lo, hi) in enumerate(windows):
            full = (hi - lo).days + 1
            if not periods:
                op[i, j] = full
            else:
                active = 0
                for ps, pe in periods:
                    a = max(lo, ps)
                    b = min(hi, pe)
                    if b >= a:
                        active += (b - a).days + 1
                op[i, j] = min(active, full)

    op_df = pd.DataFrame(op, columns=occ_cols)
    op_df.insert(0, "siteID", sites)
    op_df.to_csv(out_dir / "camera_operation.csv", index=False)

    # ── Cargar decisiones ────────────────────────────────────────────────────
    dec = load_all_decisions(decisions_dir) if decisions_dir.exists() else pd.DataFrame(
        columns=["observationID", "site_occasion_key", "scientificName"]
    )

    # ── Historiales de detección por especie ─────────────────────────────────
    summary_rows = []

    for sp in target_species:
        sp_safe   = sanitize(sp)
        sp_cands  = candidates[candidates["scientificName"] == sp]
        naive_keys = set(sp_cands["site_occasion_key"].unique())

        if not dec.empty and "scientificName" in dec.columns:
            verif_keys: set[str] = set(
                dec[dec["scientificName"] == sp]["site_occasion_key"].dropna()
            )
        else:
            verif_keys = {k for k in (dec["site_occasion_key"].dropna() if not dec.empty else [])
                          if k.endswith(f"_{sp_safe}")}

        yN = np.full((n_sites, n_occ), np.nan)
        yV = np.full((n_sites, n_occ), np.nan)
        for i, site in enumerate(sites):
            for j in range(n_occ):
                if op[i, j] == 0:
                    continue
                key = f"{site}_occ{j + 1}_{sp_safe}"
                yN[i, j] = 1.0 if key in naive_keys else 0.0
                yV[i, j] = 1.0 if key in verif_keys else 0.0

        def _to_df(y: "np.ndarray") -> pd.DataFrame:
            rows = []
            for si, sname in enumerate(sites):
                r: dict = {"siteID": sname}
                for j, col in enumerate(occ_cols):
                    v = y[si, j]
                    r[col] = "" if np.isnan(v) else int(v)
                rows.append(r)
            return pd.DataFrame(rows)

        _to_df(yN).to_csv(out_dir / f"dethist_naive_{sp_safe}.csv", index=False)
        _to_df(yV).to_csv(out_dir / f"dethist_verified_{sp_safe}.csv", index=False)

        naive_det = int(np.nansum(yN == 1))
        verif_det = int(np.nansum(yV == 1))
        fp_cells  = int(np.nansum((yN == 1) & (yV == 0)))
        psi_naive = float(np.mean(
            [any(yN[i, j] == 1 for j in range(n_occ) if not np.isnan(yN[i, j]))
             for i in range(n_sites)]
        )) if n_sites else 0.0
        psi_verif = float(np.mean(
            [any(yV[i, j] == 1 for j in range(n_occ) if not np.isnan(yV[i, j]))
             for i in range(n_sites)]
        )) if n_sites else 0.0

        summary_rows.append({
            "species":              sp,
            "candidate_frames":     len(sp_cands),
            "candidate_combos":     len(naive_keys),
            "naive_detections":     naive_det,
            "verified_detections":  verif_det,
            "false_positive_cells": fp_cells,
            "psi_obs_naive":        round(psi_naive, 3),
            "psi_obs_verified":     round(psi_verif, 3),
        })

    pd.DataFrame(summary_rows).to_csv(out_dir / "verification_summary.csv", index=False)


# ─── Review effort ────────────────────────────────────────────────────────────

def build_review_effort(
    candidates: pd.DataFrame,
    decisions_dir: Path,
    config: dict,
    out_dir: Path,
) -> None:
    """Generate ``review_effort.csv``, replicating R's ``review_effort()``.

    Measures how many sequences the expert actually inspected:

    * **Confirmed cells**: cost = rank of the confirmed sequence (expert stopped
      at the first "yes").
    * **Rejected cells**: cost = maximum rank available (expert exhausted all
      sequences without confirming).

    Also reports percentages relative to the full candidate set and the original
    classified archive.

    Args:
        candidates: Full candidate manifest DataFrame.
        decisions_dir: Directory containing decision CSVs.
        config: Session configuration dict (requires keys ``camtrap_dir`` and
            ``target_species``).
        out_dir: Destination directory (created if absent).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    dec = load_all_decisions(decisions_dir) if decisions_dir.exists() else pd.DataFrame()

    conf_obs_by_key: dict[str, set[str]] = {}
    if not dec.empty and "site_occasion_key" in dec.columns:
        for key, grp in dec.groupby("site_occasion_key"):
            conf_obs_by_key[str(key)] = set(grp["observationID"].dropna())

    keys = candidates["site_occasion_key"].unique()
    n_conf = 0; n_rej = 0; ins_conf = 0; ins_rej = 0

    for key in keys:
        sub  = candidates[candidates["site_occasion_key"] == key]
        conf = conf_obs_by_key.get(str(key), set())
        if conf:
            n_conf += 1
            confirmed_ranks = sub[sub["observationID"].isin(conf)]["rank"]
            ins_conf += int(confirmed_ranks.min()) if not confirmed_ranks.empty else 1
        else:
            n_rej += 1
            ins_rej += int(sub["rank"].max())

    inspected = ins_conf + ins_rej
    n_candidates = len(candidates)
    n_cells = len(keys)

    total_media: Optional[int] = None
    target_assigned: Optional[int] = None
    obs_path = Path(config["camtrap_dir"]) / "observations.csv"
    if obs_path.exists():
        obs_all = pd.read_csv(obs_path, dtype=str)
        total_media = len(obs_all)
        target_assigned = int(
            obs_all["scientificName"].isin(config["target_species"]).sum()
        )

    def pct(x: int, d: Optional[int]) -> Optional[float]:
        return round(100 * x / d, 1) if d else None

    row = {
        "candidate_cells":         n_cells,
        "confirmed_cells":         n_conf,
        "rejected_cells":          n_rej,
        "candidate_images":        n_candidates,
        "images_inspected":        inspected,
        "inspected_in_confirmed":  ins_conf,
        "inspected_in_rejected":   ins_rej,
        "mean_per_confirmed":      round(ins_conf / n_conf, 2) if n_conf else None,
        "mean_per_rejected":       round(ins_rej  / n_rej,  2) if n_rej  else None,
        "target_assigned_images":  target_assigned,
        "total_classified_images": total_media,
        "pct_of_candidates":       pct(inspected, n_candidates),
        "pct_of_target_assigned":  pct(inspected, target_assigned),
        "pct_of_archive":          pct(inspected, total_media),
    }
    pd.DataFrame([row]).to_csv(out_dir / "review_effort.csv", index=False)
