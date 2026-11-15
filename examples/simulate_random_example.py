#!/usr/bin/env python3
"""
simulate_random_example.py — Ejemplo de `uv run cli simulate-random` con el dataset de ejemplo.

Construye una sesión de muestra a partir de examples/camtrap_dp y compara la
verificación dirigida con submuestras aleatorias del mismo tamaño.

IMPORTANTE: no hay un revisor real en el ejemplo. Para tener decisiones se usa un
"revisor" automático que confirma un evento de detección cuando la probabilidad del
clasificador es >= 0.8. Solo sirve para ilustrar el formato; con una sesión real,
apunta el comando a la carpeta de la sesión:

    uv run cli simulate-random <carpeta-de-sesión> --draws 1000 --seed 42

Uso:
    uv run python examples/simulate_random_example.py [carpeta_de_salida]   (por defecto, en el directorio temporal)
"""
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

import pandas as pd  # noqa: E402
from camtrap_workflow import build_candidates, load_camtrapdp, save_decisions  # noqa: E402
from random_subsample import simulate_random_subsample  # noqa: E402

SPECIES = ["Cervus elaphus", "Sus scrofa"]
CONFIRM_AT = 0.8      # umbral del revisor automático de ejemplo


def make_session(out: Path) -> Path:
    """Write a small session folder (config, candidate manifest, decisions)."""
    dep, med, obs = load_camtrapdp(ROOT / "examples" / "camtrap_dp")
    cand = build_candidates(
        dep, med, obs, target_species=SPECIES,
        study_start=date(2025, 11, 1), study_end=date(2025, 11, 14),
        occasion_days=2, total_iterations=100_000, gap_seconds=60,
    )
    out.mkdir(parents=True, exist_ok=True)
    cand.to_csv(out / "candidate_manifest.csv", index=False)
    (out / "config.json").write_text(json.dumps({"target_species": SPECIES, "occasion_days": 2}))

    decisions = out / "decisions"
    for sp_safe, g in cand.groupby("species_safe"):
        resolved: set[str] = set()
        for rank in range(1, int(g["rank"].max()) + 1):
            ev = g[(g["rank"] == rank) & ~g["site_occasion_key"].isin(resolved)]
            ev = ev.assign(_p=pd.to_numeric(ev["classificationProbability"], errors="coerce"))
            ev = ev.sort_values("_p", ascending=False).drop_duplicates("site_occasion_key")
            ok = ev[ev["_p"] >= CONFIRM_AT]
            save_decisions(decisions, cand, sp_safe, rank, ok["observationID"].tolist())
            resolved |= set(ok["site_occasion_key"])
    return out


if __name__ == "__main__":
    session = make_session(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "camtrap_verify_sample_session")
    from random_subsample import load_session
    candidates, decisions_dir = load_session(session)
    df = simulate_random_subsample(candidates, decisions_dir, draws=1000, seed=42)
    df.to_csv(session / "random_subsample_simulation.csv", index=False)
    print(df.to_string(index=False))
    print(f"\nSession and results in: {session}")
