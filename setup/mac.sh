#!/bin/bash
# Philibert by Esteef.Ai - Mac (Apple silicon and Intel).
#
# Everything lives in this folder: its own Python, its own Ollama, its own models
# and data. Nothing is installed on the Mac and nothing listens beyond it.
# The first start downloads what the drive needs (once, so it needs the Internet);
# every start after that runs offline.
#
# UNTESTED ON A MAC SO FAR - written to mirror setup/windows.ps1 step for step.
set -u
FULL=0; [ "${1:-}" = "--full" ] && FULL=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

case "$(uname -m)" in
  arm64) PYA="aarch64-apple-darwin"; RT="$ROOT/runtime/mac-arm64" ;;
  *)     PYA="x86_64-apple-darwin";  RT="$ROOT/runtime/mac-x64" ;;
esac
DL="$ROOT/runtime/_download"
PY="$RT/python/bin/python3"
OL="$RT/ollama/ollama"
APP="$ROOT/app/NeuralDock_launcher.py"

# Pinned: what this version of Philibert was tested with.
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.11.17%2B20261003-$PYA-install_only.tar.gz"
OL_VER="v0.40.4"
OL_URL="https://github.com/ollama/ollama/releases/download/$OL_VER/ollama-darwin.tgz"
PKGS="psutil==7.2.2 websockets==15.0.1 pywebview==6.2.1"

step() { echo; echo "== $1"; }
fail() { echo; echo "!! $1"; read -r -p "Press Enter to close. " _; exit 1; }
fetch() {
  curl -L --fail -C - -o "$2" "$1" \
    || fail "Could not download $(basename "$2"). The first start needs the Internet - connect and run this again."
}

echo "Philibert by Esteef.Ai - $ROOT"

# -- first run: Python -------------------------------------------------------
if [ ! -x "$PY" ]; then
  step "First start: getting Python for this drive (about 20 MB)"
  mkdir -p "$DL" "$RT"
  fetch "$PY_URL" "$DL/python.tar.gz"
  tar -xzf "$DL/python.tar.gz" -C "$RT" || fail "Could not unpack Python."
  rm -f "$DL/python.tar.gz"
fi
export PYTHONNOUSERSITE=1      # never pick up the Mac's own Python packages

STAMP="$RT/python/.philibert-packages"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$PKGS" ]; then
  step "Installing the app's Python packages onto the drive"
  # shellcheck disable=SC2086
  "$PY" -m pip install --disable-pip-version-check --no-warn-script-location $PKGS \
    || fail "Could not install the Python packages. The first start needs the Internet."
  printf '%s' "$PKGS" > "$STAMP"
fi

# -- first run: Ollama -------------------------------------------------------
OLSTAMP="$RT/ollama/.philibert-version"
if [ ! -f "$OL" ] || { [ -f "$OLSTAMP" ] && [ "$(cat "$OLSTAMP")" != "$OL_VER" ]; }; then
  step "First start: getting Ollama, which runs the AI models (about 170 MB)"
  mkdir -p "$DL" "$RT/ollama"
  fetch "$OL_URL" "$DL/ollama.tgz"
  tar -xzf "$DL/ollama.tgz" -C "$RT/ollama" || fail "Could not unpack Ollama."
  chmod +x "$RT/ollama/ollama" "$RT/ollama/llama-server" 2>/dev/null
  printf '%s' "$OL_VER" > "$OLSTAMP"
  rm -f "$DL/ollama.tgz"
fi

# -- data: created once, never overwritten -----------------------------------
DATA="$ROOT/data"
mkdir -p "$DATA/vault" "$DATA/exports" "$ROOT/secrets"
[ -f "$DATA/neuraldock_config.json" ] || cp "$ROOT/setup/default_config.json" "$DATA/neuraldock_config.json"

# -- run ---------------------------------------------------------------------
export OLLAMA_MODELS="$ROOT/models"
export OLLAMA_HOST="127.0.0.1:11435"
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_KV_CACHE_TYPE=q8_0
export OLLAMA_NOPRUNE=1          # never delete model files on start
export OLLAMA_LOAD_TIMEOUT=30m   # a USB hard drive can take minutes to load a big model

export PHILIBERT_ROOT="$ROOT"
export ND_PORTABLE=1
export ND_DATA_DIR="$DATA"
export ND_OLLAMA_URL="http://127.0.0.1:11435"
export ND_OLLAMA_EXE="$OL"
export ND_PORT=7790
if [ "$FULL" = 1 ]; then export ND_START_PATH=/full; else export ND_START_PATH=""; fi

"$OL" serve >/dev/null 2>&1 &
OLPID=$!
# Take Ollama and its model runners down with us, however we exit.
trap 'pkill -P $OLPID 2>/dev/null; kill $OLPID 2>/dev/null' EXIT

for _ in $(seq 1 60); do
  curl -s -m 2 http://127.0.0.1:11435/api/version >/dev/null && break
  sleep 0.5
done

"$PY" "$ROOT/app/nd_philibert.py" --first-run || {
  echo "Some models could not be downloaded. Philibert will start anyway;"
  echo "connect to the Internet and pick a model in the list to download it."
}

"$PY" "$APP"
