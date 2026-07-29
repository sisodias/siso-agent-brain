#!/bin/zsh
set -euo pipefail

INSTALL_ROOT="${SISO_AGENT_BRAIN_HOME:-$HOME/.local/lib/siso-agent-brain}"
BIN_DIR="${SISO_BIN_DIR:-$HOME/.local/bin}"
MARKER="$INSTALL_ROOT/.siso-agent-brain-install.json"

case "$INSTALL_ROOT" in ""|/|"$HOME"|"$HOME/") echo "Refusing unsafe install target: $INSTALL_ROOT" >&2; exit 1;; esac
if [[ ! -f "$MARKER" ]] || ! grep -q '"package":"siso-agent-brain"' "$MARKER"; then
  echo "Refusing to remove unmarked target: $INSTALL_ROOT" >&2
  exit 1
fi
for command in siso-brain siso-brain-server; do
  link="$BIN_DIR/$command"
  if [[ -L "$link" && "$(readlink "$link")" == "$INSTALL_ROOT/bin/$command" ]]; then
    rm "$link"
  fi
done
rm -rf -- "$INSTALL_ROOT"
echo "Uninstalled SISO Agent Brain code. Runtime database, tokens, and outbox were not removed."
