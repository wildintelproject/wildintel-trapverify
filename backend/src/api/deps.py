from fastapi import HTTPException

from services import session_service


def require_candidates() -> None:
    """FastAPI dependency — raises 400 if no active session with candidates loaded."""
    if session_service.get_candidates() is None:
        raise HTTPException(400, "Workflow not initialized. POST /api/setup first.")
