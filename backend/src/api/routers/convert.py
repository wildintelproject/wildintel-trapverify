import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from camtrap_workflow import deepfaune_to_camtrapdp, generic_csv_to_camtrapdp, DEEPFAUNE_LABEL_MAP

router = APIRouter(prefix="/api/convert", tags=["convert"])
logger = logging.getLogger(__name__)


class DeepfauneConvertRequest(BaseModel):
    csv_path: str
    image_base_dir: str | None = None
    min_score: float = 0.0


def _detect_deepfaune_columns(df: pd.DataFrame) -> tuple[str, str]:
    """Return (label_col, score_col) by inspecting the CSV headers."""
    cols = set(df.columns)
    if "top1" in cols:
        return "top1", "score" if "score" in cols else "top1"
    if "predictionbase" in cols:
        return "predictionbase", "scorebase" if "scorebase" in cols else "predictionbase"
    # Fallback: look for any column that might be a label
    for c in ("label", "species", "class", "prediction"):
        if c in cols:
            for s in ("score", "confidence", "prob"):
                if s in cols:
                    return c, s
            return c, c
    raise ValueError(
        f"No se reconoce el formato DeepFaune. Columnas encontradas: {sorted(cols)}"
    )


@router.post("/deepfaune")
def convert_deepfaune(req: DeepfauneConvertRequest) -> dict:
    """Convert a DeepFaune CSV to CamtrapDP format.

    Returns the path to the generated CamtrapDP directory so the caller can
    inspect it with ``/api/fs/inspect`` and continue the normal setup flow.
    """
    csv_path = Path(req.csv_path)
    if not csv_path.exists():
        raise HTTPException(400, f"No se encontró el fichero: {req.csv_path}")
    if not csv_path.is_file():
        raise HTTPException(400, f"La ruta no es un fichero: {req.csv_path}")

    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception as exc:
        raise HTTPException(400, f"Error al leer el CSV: {exc}") from exc

    required = {"filename", "date"}
    missing = required - set(df.columns)
    if missing:
        raise HTTPException(
            400,
            f"El CSV no contiene las columnas obligatorias: {sorted(missing)}. "
            f"Columnas disponibles: {sorted(df.columns)}",
        )

    try:
        label_col, score_col = _detect_deepfaune_columns(df)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if score_col != label_col and score_col in df.columns:
        df = df.rename(columns={score_col: "score"})

    image_base = Path(req.image_base_dir) if req.image_base_dir else None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path.home() / "Documents" / "camtrap_verify" / "conversions" / f"deepfaune_{ts}"

    try:
        deepfaune_to_camtrapdp(
            df=df,
            species_map=DEEPFAUNE_LABEL_MAP,
            out_dir=out_dir,
            image_base_dir=image_base,
            label_col=label_col,
            min_score=req.min_score,
        )
    except Exception as exc:
        logger.exception("Error converting DeepFaune CSV: %s", exc)
        raise HTTPException(500, f"Error en la conversión: {exc}") from exc

    logger.info("DeepFaune conversion complete: %s → %s", csv_path, out_dir)
    return {"camtrap_dir": str(out_dir)}


class CsvConvertRequest(BaseModel):
    csv_path: str
    col_filename: str
    col_datetime: str
    col_label: str
    col_score: str | None = None
    col_site: str | None = None
    species_map: dict[str, str] = {}
    image_base_dir: str | None = None


@router.post("/csv")
def convert_csv(req: CsvConvertRequest) -> dict:
    """Convert any classifier CSV to CamtrapDP using user-supplied column mapping."""
    csv_path = Path(req.csv_path)
    if not csv_path.exists() or not csv_path.is_file():
        raise HTTPException(400, f"No se encontró el fichero: {req.csv_path}")
    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception as exc:
        raise HTTPException(400, f"Error al leer el CSV: {exc}") from exc

    required = {req.col_filename, req.col_datetime, req.col_label}
    missing = required - set(df.columns)
    if missing:
        raise HTTPException(400, f"Columnas no encontradas en el CSV: {sorted(missing)}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path.home() / "Documents" / "camtrap_verify" / "conversions" / f"csv_{ts}"
    image_base = Path(req.image_base_dir) if req.image_base_dir else None

    try:
        generic_csv_to_camtrapdp(
            df=df,
            out_dir=out_dir,
            col_filename=req.col_filename,
            col_datetime=req.col_datetime,
            col_label=req.col_label,
            col_score=req.col_score,
            col_site=req.col_site,
            species_map=req.species_map,
            image_base_dir=image_base,
        )
    except Exception as exc:
        logger.exception("Error converting custom CSV: %s", exc)
        raise HTTPException(500, f"Error en la conversión: {exc}") from exc

    logger.info("Custom CSV conversion complete: %s → %s", csv_path, out_dir)
    return {"camtrap_dir": str(out_dir)}
