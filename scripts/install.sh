#!/usr/bin/env bash
# install.sh — POSIX twin of scripts/install.ps1.
#
# Creates a venv under ~/.local/lmc-venv, installs the package into it,
# and drops a `lmc` shim under ~/.local/bin/ (which is on PATH for most
# Linux distros and modern macOS).
#
# Use this when pipx is not available. Most users on a personal machine
# should prefer `pipx install .` from the repo root.
set -euo pipefail

VENV_DIR="${LMC_VENV_DIR:-$HOME/.local/lmc-venv}"
SHIM_DIR="${LMC_SHIM_DIR:-$HOME/.local/bin}"
PYTHON="${LMC_PYTHON:-python3}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "local-mc installer"
echo "  repo:    $ROOT"
echo "  venv:    $VENV_DIR"
echo "  shim in: $SHIM_DIR"

if ! command -v "$PYTHON" >/dev/null; then
  echo "ERROR: $PYTHON not found. Install Python >= 3.10 first." >&2
  exit 1
fi

VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  python:  $(command -v "$PYTHON") (v$VERSION)"

if [[ ! -d "$VENV_DIR" ]]; then
  echo
  echo "Creating venv..."
  "$PYTHON" -m venv "$VENV_DIR"
else
  echo
  echo "Reusing existing venv at $VENV_DIR."
fi

VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip wheel
"$VENV_PYTHON" -m pip install "$ROOT"

mkdir -p "$SHIM_DIR"
SHIM_PATH="$SHIM_DIR/lmc"
LMC_ENTRY="$VENV_DIR/bin/lmc"
if [[ ! -x "$LMC_ENTRY" ]]; then
  echo "ERROR: expected $LMC_ENTRY after install — pip install failed silently?" >&2
  exit 1
fi

cat > "$SHIM_PATH" <<EOF
#!/usr/bin/env bash
exec "$LMC_ENTRY" "\$@"
EOF
chmod +x "$SHIM_PATH"

echo
echo "Installed shim at $SHIM_PATH"
if command -v lmc >/dev/null; then
  echo "  PATH lookup: $(command -v lmc)"
else
  echo "  WARNING: 'lmc' did not resolve on PATH. Add $SHIM_DIR to PATH and re-run shell."
fi

cat <<EOF

Next steps:
  lmc init
  lmc add <name> <path-to-project>
  lmc serve
EOF
