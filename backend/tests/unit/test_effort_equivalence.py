"""The vectorised effort counters must equal the per-cell walk they replaced."""
import numpy as np
import pandas as pd
import pytest

from camtrap_workflow import _effort_accumulate


def _reference(sp_df, conf_ids, unc_ids, done):
    """The original cell-by-cell implementation (kept here as the specification)."""
    acc = {"det": 0, "non": 0, "unv": 0, "events": 0, "insp": 0, "photos": 0, "unc": 0, "unc_cells": 0,
           "photos_insp": 0, "insp_det": 0, "insp_non": 0, "before": [], "rej_scores": [], "conf_scores": []}
    for _, cell in sp_df.groupby("site_occasion_key"):
        ev = cell.groupby("burst_id").agg(rank=("rank", "first"), score=("_score", "max"))
        acc["events"] += len(ev)
        acc["photos"] += len(cell)
        n_unc = cell.loc[cell["observationID"].isin(unc_ids), "burst_id"].nunique()
        acc["unc"] += n_unc
        conf_rank = cell.loc[cell["observationID"].isin(conf_ids), "rank"]
        if not conf_rank.empty:
            cr = int(conf_rank.min())
            seen = ev[ev["rank"] <= cr]
            before = ev[ev["rank"] < cr]
            acc["det"] += 1
            acc["insp_det"] += len(seen)
            acc["before"].append(len(before))
            acc["rej_scores"] += before["score"].dropna().tolist()
            acc["conf_scores"] += ev[ev["rank"] == cr]["score"].dropna().tolist()
        else:
            seen = ev if done is None else ev[ev["rank"] <= done]
            if len(seen) < len(ev):
                acc["unv"] += 1
            else:
                acc["non"] += 1
                acc["unc_cells"] += 1 if n_unc else 0
            acc["insp_non"] += len(seen)
            acc["rej_scores"] += seen["score"].dropna().tolist()
        acc["insp"] += len(seen)
        acc["photos_insp"] += int(cell["burst_id"].isin(cell[cell["rank"].isin(seen["rank"])]["burst_id"]).sum())
    return acc


def _fresh():
    return {"det": 0, "non": 0, "unv": 0, "events": 0, "insp": 0, "photos": 0, "unc": 0, "unc_cells": 0,
            "photos_insp": 0, "insp_det": 0, "insp_non": 0, "before": [], "rej_scores": [], "conf_scores": []}


def _random_species(seed: int, n_cells: int = 25) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows, oid = [], 0
    for c in range(n_cells):
        n_events = int(rng.integers(1, 6))
        scores = rng.uniform(0.3, 1, n_events)
        order = np.argsort(-scores)
        for rank, e in enumerate(order, start=1):
            for _ in range(int(rng.integers(1, 4))):
                oid += 1
                rows.append({"observationID": f"o{oid}", "site_occasion_key": f"cell{c}", "burst_id": int(e),
                             "rank": rank, "_score": float(scores[e]) if rng.random() > 0.05 else np.nan})
    return pd.DataFrame(rows)


def _canon(acc):
    out = dict(acc)
    for k in ("before", "rej_scores", "conf_scores"):
        out[k] = sorted(out[k])
    return out


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("done", [None, 0, 1, 2, 3, 9])
def test_vectorised_effort_matches_the_cell_walk(seed, done):
    df = _random_species(seed)
    rng = np.random.default_rng(seed + 100)
    ids = df["observationID"].tolist()
    conf = set(rng.choice(ids, size=len(ids) // 10, replace=False))
    unc = set(rng.choice(ids, size=len(ids) // 8, replace=False)) - conf
    assert _canon(_effort_accumulate(df, conf, unc, done, _fresh())) == _canon(_reference(df, conf, unc, done))


def test_no_confirmations_and_no_unsure():
    df = _random_species(1)
    assert _canon(_effort_accumulate(df, set(), set(), 2, _fresh())) == _canon(_reference(df, set(), set(), 2))


def _burst_reference(joined: pd.DataFrame, gap_seconds: int) -> pd.DataFrame:
    """The original per-cell loop."""
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
    return pd.concat(records, ignore_index=True)


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("gap", [0, 30, 60, 600])
def test_vectorised_burst_ids_match_the_cell_walk(seed, gap):
    from camtrap_workflow import _assign_burst_ids
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(15):
        t = pd.Timestamp("2025-01-01") + pd.Timedelta(hours=int(rng.integers(0, 100)))
        for _ in range(int(rng.integers(1, 30))):
            t += pd.Timedelta(seconds=int(rng.choice([0, 5, 30, 59, 60, 61, 300, 4000])))
            rows.append({"site_occasion_key": f"c{c}", "ts": t, "mediaID": f"m{len(rows)}"})
    df = pd.DataFrame(rows)
    pd.testing.assert_frame_equal(_assign_burst_ids(df, gap), _burst_reference(df, gap))


def test_burst_ids_of_an_empty_frame():
    from camtrap_workflow import _assign_burst_ids
    assert _assign_burst_ids(pd.DataFrame(), 60).empty


def _review_effort_reference(candidates, dec):
    conf_obs_by_key = {}
    if not dec.empty:
        for key, grp in dec.groupby("site_occasion_key"):
            conf_obs_by_key[str(key)] = set(grp["observationID"].dropna())
    n_conf = n_rej = ins_conf = ins_rej = 0
    for key in candidates["site_occasion_key"].unique():
        sub = candidates[candidates["site_occasion_key"] == key]
        conf = conf_obs_by_key.get(str(key), set())
        if conf:
            n_conf += 1
            cr = sub[sub["observationID"].isin(conf)]["rank"]
            ins_conf += int(cr.min()) if not cr.empty else 1
        else:
            n_rej += 1
            ins_rej += int(sub["rank"].max())
    return n_conf, n_rej, ins_conf, ins_rej


@pytest.mark.parametrize("seed", range(6))
def test_review_effort_matches_the_cell_walk(seed, tmp_path):
    from camtrap_workflow import build_review_effort
    df = _random_species(seed, 30)
    rng = np.random.default_rng(seed + 7)
    cells = df["site_occasion_key"].unique()
    conf_rows = []
    for c in rng.choice(cells, size=10, replace=False):
        sub = df[df["site_occasion_key"] == c]
        pick = sub.sample(1, random_state=int(rng.integers(0, 1000)))
        conf_rows.append({"observationID": pick["observationID"].iloc[0], "site_occasion_key": c})
    # a confirmation that is not among the candidates, and an empty-observation row
    conf_rows.append({"observationID": "ghost", "site_occasion_key": cells[0]})
    dec_dir = tmp_path / "decisions"
    dec_dir.mkdir()
    dec = pd.DataFrame(conf_rows)
    dec.to_csv(dec_dir / "decisions_x_iter1.csv", index=False)
    out = tmp_path / "out"
    build_review_effort(df, dec_dir, {"camtrap_dir": str(tmp_path / "none"), "target_species": []}, out)
    row = pd.read_csv(out / "review_effort.csv").iloc[0]
    n_conf, n_rej, ins_conf, ins_rej = _review_effort_reference(df, dec)
    assert (row["confirmed_cells"], row["rejected_cells"], row["inspected_in_confirmed"], row["inspected_in_rejected"]) == (n_conf, n_rej, ins_conf, ins_rej)
