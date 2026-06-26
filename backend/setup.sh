#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ✔  $*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠  $*${NC}"; }
err()  { echo -e "${RED}  ✘  $*${NC}"; }

echo ""
echo "==> CamTrap Verify — backend setup"
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

# ── Dependencias ──────────────────────────────────────────────────────────────

echo ""
echo "==> Instalando dependencias..."
uv sync
ok "Dependencias instaladas."

# ── Resumen ───────────────────────────────────────────────────────────────────

echo ""
echo "==> Listo. Para arrancar el backend:"
echo ""
echo "    ./start.sh dev    ← desarrollo (hot-reload)"
echo "    ./start.sh prod   ← producción"
echo "    ./start.sh debug  ← depuración (debugpy en :5678)"
echo ""
