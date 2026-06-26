"""
Application settings for CamTrap Verify.

Priority order (highest to lowest):
  1. Environment variables        CAMTRAP_PORT=9000 ./camtrap-verify-backend
  2. ~/.config/camtrap_verify/.env   ← config del usuario
  3. <directorio del binario>/.env   ← fallback junto al ejecutable

All fields have sensible defaults so the app works out of the box.

Example .env
------------
CAMTRAP_PORT=8765
CAMTRAP_LOG_LEVEL=INFO
CAMTRAP_CORS_ORIGINS=["http://localhost:5173","http://localhost:8765"]
CAMTRAP_DEFAULT_OUTPUT_DIR=/home/user/Documents/camtrap_verify
"""
import logging
import sys
from pathlib import Path

from platformdirs import user_config_dir, user_documents_dir
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_files() -> tuple[Path, ...]:
    """Return .env search paths in ascending priority order.

    pydantic-settings applies files left-to-right, later files win,
    so the highest-priority location must come last.
    """
    # Directorio junto al binario (PyInstaller frozen) o junto a este módulo
    if getattr(sys, "frozen", False):
        binary_dir = Path(sys.executable).parent
    else:
        binary_dir = Path(__file__).parent

    config_dir = Path(user_config_dir("camtrap_verify"))

    return (
        binary_dir / ".env",    # prioridad más baja
        config_dir / ".env",    # prioridad más alta (sobrescribe la anterior)
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_prefix="CAMTRAP_",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
    )

    # ── Server ────────────────────────────────────────────────────────────────
    port: int = 8765
    log_level: str = "INFO"

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost",
        "http://localhost:8765",
    ]

    # ── Paths ─────────────────────────────────────────────────────────────────
    app_dir: Path = Path(user_config_dir("camtrap_verify"))
    default_output_dir: Path = Path(user_documents_dir()) / "camtrap_verify"

    # ── Validators ────────────────────────────────────────────────────────────
    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, v: str) -> str:
        level = v.upper()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError(f"Invalid log level: {v!r}")
        return level


settings = Settings()


def configure_logging() -> None:
    """Apply settings.log_level to the root Python logger."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
