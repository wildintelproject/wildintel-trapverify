import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from services import session_service

router = APIRouter(prefix="/api", tags=["media"])
logger = logging.getLogger(__name__)


@router.get("/image/{media_id}")
def serve_image(media_id: str) -> FileResponse:
    """Serve a camera-trap image from the local filesystem by mediaID."""
    candidates = session_service.get_candidates()
    if candidates is None:
        raise HTTPException(404, "No data loaded")
    row = candidates[candidates["mediaID"] == media_id]
    if row.empty:
        logger.warning("Image not found: mediaId=%s", media_id)
        raise HTTPException(404, f"Media {media_id} not found")
    file_path = Path(str(row.iloc[0]["filePath"]))
    if not file_path.is_absolute():
        config = session_service.get_config()
        # relative paths are stored relative to the camtrap_dir parent (package root)
        file_path = (Path(config["camtrap_dir"]).parent / file_path).resolve()
    if not file_path.exists():
        logger.warning("Image file missing on disk: %s", file_path)
        raise HTTPException(404, f"File not found: {file_path}")
    return FileResponse(str(file_path))


def _error_image(label: str) -> Response:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240">
  <rect width="320" height="240" fill="#e8e8e8"/>
  <text x="160" y="110" text-anchor="middle" font-family="sans-serif"
        font-size="13" fill="#999">Image unavailable</text>
  <text x="160" y="130" text-anchor="middle" font-family="sans-serif"
        font-size="11" fill="#bbb">{label}</text>
</svg>"""
    return Response(content=svg.encode(), media_type="image/svg+xml")


@router.get("/proxy-image")
async def proxy_image(url: str) -> Response:
    """Proxy a remote image URL to bypass browser CORS restrictions."""
    logger.debug("Proxying image: %s", url)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=30)
        if resp.status_code != 200:
            logger.warning("Proxy image HTTP %d: %s", resp.status_code, url)
            return _error_image(f"HTTP {resp.status_code}")
        return Response(
            content=resp.content,
            media_type=resp.headers.get("content-type", "image/jpeg"),
        )
    except Exception as exc:
        logger.warning("Proxy image failed (%s): %s", type(exc).__name__, url)
        return _error_image("Network error")
