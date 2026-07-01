#!/usr/bin/env bash
# ============================================================================
# setup.sh
# Prerequisites for upserting schema_enriched.json to Pinecone.
#
# - Validates .env (PINECONE_API_KEY)
# - Activates .venv + installs pinecone, python-dotenv, ollama if missing
# - Pulls Ollama model nomic-embed-text if missing
#
# Then the Python script (upsert_to_pinecone.py) performs the actual upsert.
# Compatible with: Git Bash (Windows), WSL, macOS, Linux.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Colors ─────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

step() { printf "\n${CYAN}[%s] %s${NC}\n" "$1" "$2"; }
ok()   { printf "  ${GREEN}[OK]${NC} %s\n" "$1"; }
warn() { printf "  ${YELLOW}[!]${NC} %s\n" "$1"; }
fail() { printf "  ${RED}[X]${NC} %s\n" "$1"; exit 1; }

# ─── Detect Python / venv path per OS ───────────────────────────────────────
case "$OSTYPE" in
    msys*|win32*|cygwin*) PY=".venv/Scripts/python.exe" ;;
    *)                    PY=".venv/bin/python" ;;
esac

# ─── 1. Validate .env ───────────────────────────────────────────────────────
step "1/3" "Validating .env"
[[ -f .env ]] || fail ".env not found in project root"

API_KEY="$(grep -E '^[[:space:]]*PINECONE_API_KEY[[:space:]]*=' .env \
            | head -n1 \
            | sed -E 's/^[[:space:]]*PINECONE_API_KEY[[:space:]]*=[[:space:]]*//' \
            | tr -d '\"'\''[:space:]')"

[[ -n "$API_KEY" ]]                                    || fail "PINECONE_API_KEY missing in .env"
[[ "$API_KEY" != "your-pinecone-api-key-here" ]]        || fail "PINECONE_API_KEY is still the placeholder"
ok "PINECONE_API_KEY present"

# ─── 2. Activate venv + install deps ─────────────────────────────────────────
step "2/3" "Activating virtualenv and verifying dependencies"
[[ -x "$PY" ]] || fail ".venv not found at $PY. Run: python -m venv .venv"
ok "venv found at $PY"

for dep in pinecone python-dotenv ollama; do
    if "$PY" -m pip show "$dep" >/dev/null 2>&1; then
        ok "$dep already installed"
    else
        warn "Installing $dep"
        "$PY" -m pip install "$dep" >/dev/null 2>&1 || fail "pip install $dep failed"
        ok "Installed $dep"
    fi
done

# ─── 3. Pull Ollama model ────────────────────────────────────────────────────
step "3/3" "Checking Ollama model: nomic-embed-text"
if ! command -v ollama >/dev/null 2>&1; then
    warn "Ollama CLI not on PATH. Install from https://ollama.com/download"
    warn "Skipping model check -- ensure 'nomic-embed-text' is pulled before running."
else
    if ! ollama list >/dev/null 2>&1; then
        warn "Cannot reach Ollama daemon. Start it with 'ollama serve'"
    else
        if ollama list | grep -q "nomic-embed-text"; then
            ok "nomic-embed-text already pulled"
        else
            warn "Pulling nomic-embed-text (this may take a moment)..."
            ollama pull nomic-embed-text || fail "ollama pull nomic-embed-text failed"
            ok "nomic-embed-text ready"
        fi
    fi
fi

# ─── Done ────────────────────────────────────────────────────────────────────
printf "\n${GREEN}================================================${NC}\n"
printf "${GREEN}  Prerequisites OK -- run the upsert next:${NC}\n"
printf "${GREEN}    %s upsert_to_pinecone.py${NC}\n" "$PY"
printf "${GREEN}================================================${NC}\n"