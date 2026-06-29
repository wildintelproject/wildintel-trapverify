#!/usr/bin/env bash
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ✔  $*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠  $*${NC}"; }
err()  { echo -e "${RED}  ✘  $*${NC}" >&2; }

echo ""
echo -e "${BOLD}==> CamTrap Verify — setup${NC}"
echo ""

# ── Docker ────────────────────────────────────────────────────────────────────

if command -v docker &>/dev/null; then
    ok "Docker $(docker --version | awk '{print $3}' | tr -d ',')"
else
    err "Docker no encontrado."
    warn "Instálalo desde https://docs.docker.com/get-docker/ para poder usar el modo producción."
fi

# ── uv ────────────────────────────────────────────────────────────────────────

if command -v uv &>/dev/null; then
    ok "uv $(uv --version)"
else
    warn "uv no encontrado. Instalando..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv &>/dev/null; then
        ok "uv $(uv --version) instalado correctamente."
        warn "Reinicia el terminal (o ejecuta: source ~/.bashrc) para que uv esté disponible en nuevas sesiones."
    else
        err "No se pudo instalar uv. Visita https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
fi

# ── Backend — dependencias Python ─────────────────────────────────────────────

echo ""
echo "==> Instalando dependencias del backend..."
uv sync
ok "Dependencias del backend instaladas."

# ── Node.js / npm ─────────────────────────────────────────────────────────────

echo ""
if ! command -v node &>/dev/null; then
    err "Node.js no encontrado. Instálalo desde https://nodejs.org/ (v18+)"
    warn "Saltando instalación del frontend."
else
    NODE_VERSION=$(node -e "process.stdout.write(process.versions.node)")
    NODE_MAJOR=${NODE_VERSION%%.*}
    if (( NODE_MAJOR < 18 )); then
        err "Node.js ${NODE_VERSION} es demasiado antiguo. Se requiere v18+."
        warn "Saltando instalación del frontend."
    else
        ok "Node.js ${NODE_VERSION}"

        if ! command -v npm &>/dev/null; then
            err "npm no encontrado. Debe venir incluido con Node.js."
        else
            ok "npm $(npm --version)"
            echo ""
            echo "==> Instalando dependencias del frontend..."
            npm install --prefix frontend
            ok "Dependencias del frontend instaladas."
        fi
    fi
fi

# ── Resumen ───────────────────────────────────────────────────────────────────

echo ""
echo "==> Listo. Para arrancar la aplicación:"
echo ""
echo "    uv run cli dev                  ← backend + frontend (desarrollo)"
echo "    uv run cli backend serve dev    ← solo backend"
echo "    uv run cli frontend dev         ← solo frontend"
echo ""
