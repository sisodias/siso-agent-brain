#!/bin/zsh
set -euo pipefail

SOURCE_ROOT="${0:A:h}"
INSTALL_ROOT="${SISO_AGENT_BRAIN_HOME:-$HOME/.local/lib/siso-agent-brain}"
BIN_DIR="${SISO_BIN_DIR:-$HOME/.local/bin}"

if [[ -e "$INSTALL_ROOT" ]]; then
  echo "Install target already exists: $INSTALL_ROOT" >&2
  exit 1
fi
for command in siso-brain siso-brain-server; do
  link="$BIN_DIR/$command"
  if [[ -e "$link" || -L "$link" ]]; then
    echo "Executable target already exists: $link" >&2
    exit 1
  fi
done
mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
for item in bin src migrations scripts tools docs README.md LICENSE PROVENANCE.md MIGRATION-MAP.json; do
  cp -R "$SOURCE_ROOT/$item" "$INSTALL_ROOT/$item"
done
cat > "$INSTALL_ROOT/.siso-agent-brain-install.json" <<'JSON'
{"package":"siso-agent-brain","contract_version":"1"}
JSON

for command in siso-brain siso-brain-server; do
  link="$BIN_DIR/$command"
  ln -s "$INSTALL_ROOT/bin/$command" "$link"
done
echo "Installed SISO Agent Brain code. Runtime database and tokens remain separate."
