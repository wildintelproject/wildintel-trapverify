#!/usr/bin/env bash
# frontend/setup.sh — preflight check and dependency install
set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()  { echo -e "${GREEN}✔  $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠  $*${NC}"; }
error() { echo -e "${RED}✘  $*${NC}" >&2; exit 1; }

echo -e "\n${BOLD}CamTrap Verify — frontend setup${NC}\n"

# ── Node.js ──────────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
    error "Node.js not found. Install it from https://nodejs.org/ (v18+)"
fi

NODE_VERSION=$(node -e "process.stdout.write(process.versions.node)")
NODE_MAJOR=${NODE_VERSION%%.*}
if (( NODE_MAJOR < 18 )); then
    error "Node.js ${NODE_VERSION} is too old. Version 18+ is required."
fi
info "Node.js ${NODE_VERSION}"

# ── npm ──────────────────────────────────────────────────────────────────────
if ! command -v npm &>/dev/null; then
    error "npm not found. It should come bundled with Node.js."
fi
info "npm $(npm --version)"

# ── Install dependencies ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo ""
echo "Installing npm dependencies..."
npm install
echo ""
info "Frontend ready. Run: uv run cli frontend dev"
