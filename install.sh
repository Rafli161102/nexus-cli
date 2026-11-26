#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/ai-hub/venv"
BIN_DIR="$HOME/.local/bin"

echo "==> Installing nexus-cli from $REPO_DIR"
mkdir -p "$(dirname "$VENV_DIR")" "$BIN_DIR"

if command -v uv >/dev/null 2>&1; then
  uv venv "$VENV_DIR" --clear
  uv pip install --python "$VENV_DIR/bin/python" -r "$REPO_DIR/requirements.txt"
else
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"
fi

chmod +x "$REPO_DIR/ai_hub.py" "$REPO_DIR/nexus_tui.py"

cat > "$BIN_DIR/ai" <<EOF
#!/bin/sh
exec python3 "$REPO_DIR/ai_hub.py" "\$@"
EOF

cat > "$BIN_DIR/nexus" <<EOF
#!/bin/sh
exec "$VENV_DIR/bin/python" "$REPO_DIR/nexus_tui.py" "\$@"
EOF

chmod +x "$BIN_DIR/ai" "$BIN_DIR/nexus"

if [ "$(uname -s)" = "Darwin" ] && command -v osacompile >/dev/null 2>&1; then
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/Nexus Terminal.app"
  osacompile -o "$HOME/Applications/Nexus Terminal.app" -e 'tell application "Terminal"
	activate
	do script "clear && exec nexus"
	try
		set bounds of front window to {120, 80, 1320, 840}
	end try
end tell' || true
  echo "==> Created macOS launcher: $HOME/Applications/Nexus Terminal.app"
fi

echo ""
echo "Done! Make sure $BIN_DIR is in your PATH:"
echo "  export PATH=\"$BIN_DIR:\$PATH\""
echo ""
echo "Run:"
echo "  nexus            # Launch Nexus Terminal TUI"
echo "  ai \"hello\"       # One-shot prompt"
echo "  ai api sync      # Pull open-source GitHub & public API catalogs"
