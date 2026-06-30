#!/usr/bin/env python3
"""
generate_sample.py — Genera un subconjunto reducido (~30 imágenes, 3 cámaras) a partir de
images_2/camtrap_dp_2 y produce los tres formatos de entrada soportados por la aplicación.

Crea/reemplaza:
  examples/images/           → 30 JPEGs reales distribuidos en 3 cámaras
  examples/camtrap_dp/       → formato CamtrapDP (deployments, media, observations)
  examples/deepfaune/        → CSV formato DeepFaune (filename, date, top1, score)
  examples/custom_csv/       → CSV con columnas personalizadas distintas a los anteriores
"""

import shutil
import pandas as pd
from pathlib import Path

BASE        = Path(__file__).parent
SRC_IMAGES  = BASE / "images_2"
SRC_CAMTRAP = BASE / "camtrap_dp_2"

# ── Parámetros de muestreo ────────────────────────────────────────────────────
DEPLOYMENTS = ["r0039-dona_0067", "r0039-dona_0071", "r0039-dona_0033"]
N_PER_DEP   = 40   # imágenes por cámara

# ── Mapa científico → etiqueta DeepFaune (inverso) ───────────────────────────
REVERSE_MAP: dict[str, str] = {
    "Cervus elaphus":         "red deer",
    "Dama dama":              "fallow deer",
    "Sus scrofa":             "wild boar",
    "Vulpes vulpes":          "fox",
    "Meles meles":            "badger",
    "Genetta genetta":        "genet",
    "Canis lupus familiaris": "dog",
}

# ── Carga fuente ──────────────────────────────────────────────────────────────
obs_src = pd.read_csv(SRC_CAMTRAP / "observations.csv")
med_src = pd.read_csv(SRC_CAMTRAP / "media.csv")
dep_src = pd.read_csv(SRC_CAMTRAP / "deployments.csv")

# ── Selección de imágenes ─────────────────────────────────────────────────────
dep_sample = dep_src[dep_src["deploymentID"].isin(DEPLOYMENTS)].copy()

frames = []
for dep_id in DEPLOYMENTS:
    rows = med_src[med_src["deploymentID"] == dep_id].copy()
    rows = rows.sort_values("timestamp").head(N_PER_DEP)
    frames.append(rows)
med_sample = pd.concat(frames).reset_index(drop=True)

obs_sample = obs_src[obs_src["mediaID"].isin(med_sample["mediaID"])].copy()

print(f"Seleccionadas {len(med_sample)} imágenes de {len(DEPLOYMENTS)} cámaras")
print(f"Especies: {sorted(obs_sample['scientificName'].dropna().unique())}")

# ── Directorio de imágenes de salida ─────────────────────────────────────────
out_images = BASE / "images"
if out_images.exists():
    shutil.rmtree(out_images)
out_images.mkdir()

copied, missing = 0, []
for _, row in med_sample.iterrows():
    old_p    = Path(row["filePath"])
    dep      = row["deploymentID"]
    filename = old_p.name
    src      = SRC_IMAGES / dep / filename
    dst_dir  = out_images / dep
    dst_dir.mkdir(exist_ok=True)
    if src.exists():
        shutil.copy2(src, dst_dir / filename)
        copied += 1
    else:
        missing.append(str(src))

if missing:
    print(f"ADVERTENCIA: {len(missing)} ficheros no encontrados")
    for m in missing[:5]:
        print(f"  {m}")
print(f"Copiadas {copied} imágenes a {out_images}")

# Rutas relativas al padre de camtrap_dp/ (= examples/)
# El backend resuelve: Path(camtrap_dir).parent / filePath
def new_rel_path(old_path: str) -> str:
    p = Path(old_path)
    return f"images/{p.parent.name}/{p.name}"

med_out = med_sample.copy()
med_out["filePath"] = med_out["filePath"].apply(new_rel_path)

# ── CamtrapDP ─────────────────────────────────────────────────────────────────
out_camtrap = BASE / "camtrap_dp"
out_camtrap.mkdir(exist_ok=True)
dep_sample.to_csv(out_camtrap / "deployments.csv", index=False)
med_out.to_csv(out_camtrap    / "media.csv", index=False)
obs_sample.to_csv(out_camtrap / "observations.csv", index=False)
print(f"CamtrapDP escrito en {out_camtrap}")

# ── Tabla combinada para los otros formatos ───────────────────────────────────
# DeepFaune y custom CSV usan rutas absolutas (no tienen mecanismo de resolución relativa)
merged = med_out.merge(
    obs_sample[["mediaID", "scientificName", "classificationProbability", "observationType"]],
    on="mediaID", how="left"
)
merged["abs_path"] = merged["filePath"].apply(lambda p: str((BASE / p).resolve()))

def to_label(row) -> str:
    obs_type = row.get("observationType", "")
    if obs_type == "human":
        return "human"
    if obs_type == "blank":
        return "empty"
    sn = row.get("scientificName", "")
    if pd.isna(sn) or not sn:
        return "empty"
    return REVERSE_MAP.get(sn, sn.lower().replace(" ", "_"))

merged["label"] = merged.apply(to_label, axis=1)
merged["score"] = pd.to_numeric(merged["classificationProbability"], errors="coerce").round(2)
merged["date_str"] = merged["timestamp"].str.replace("T", " ", regex=False)

# ── DeepFaune CSV ─────────────────────────────────────────────────────────────
# Formato: filename, date, top1, score
out_deepfaune = BASE / "deepfaune"
out_deepfaune.mkdir(exist_ok=True)
deepfaune_df = pd.DataFrame({
    "filename": merged["abs_path"],
    "date":     merged["date_str"],
    "top1":     merged["label"],
    "score":    merged["score"],
})
deepfaune_df.to_csv(out_deepfaune / "deepfaune_results.csv", index=False)
print(f"DeepFaune CSV escrito en {out_deepfaune / 'deepfaune_results.csv'} ({len(deepfaune_df)} filas)")

# ── CSV personalizado ─────────────────────────────────────────────────────────
# Columnas con nombres distintos a CamtrapDP y DeepFaune para probar el mapeo
out_custom = BASE / "custom_csv"
out_custom.mkdir(exist_ok=True)
custom_df = pd.DataFrame({
    "image_path":    merged["abs_path"],
    "datetime":      merged["date_str"],
    "species_label": merged["label"],
    "probability":   merged["score"],
    "station_id":    merged["deploymentID"],
})
custom_df.to_csv(out_custom / "custom_results.csv", index=False)
print(f"Custom CSV escrito en {out_custom / 'custom_results.csv'} ({len(custom_df)} filas)")

print("\nResumen:")
print(merged.groupby("deploymentID")["label"].value_counts().to_string())
