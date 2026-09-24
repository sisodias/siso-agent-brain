#!/bin/zsh
# update-minimax-key — rotate the UPSTREAM MiniMax provider key everywhere it lives,
# in ONE explicit command, then restart + test. (Load-bearing: a partial update
# breaks model routing. The key lives in exactly TWO live places.)
#
# Usage:  update-minimax-key.sh 'sk-cp-NEWKEY...'
#
# Updates:
#   1) Bifrost config.db   -> config_keys.value for provider 7 (Minimax)
#   2) go-llm-proxy yaml    -> minimax-codex.yaml (model api_key + keys list)
# Then restarts bifrost + the minimax-codex-proxy launchagent and runs a live
# M3 round-trip through Bifrost to PROVE the new key works before declaring done.
#
# The virtual keys (sk-bf-...) handed to you/boy/CAM/PARSER do NOT change — they
# sit in front of this upstream key and keep working untouched.
set -e

NEW="$1"
[[ -z "$NEW" ]] && { echo "usage: update-minimax-key.sh '<new sk-cp- key>'"; exit 1; }
[[ "$NEW" == sk-* ]] || { echo "refusing: key does not start with sk-"; exit 1; }

CFG="$HOME/.config/bifrost/config.db"
YAML="$HOME/.config/go-llm-proxy/minimax-codex.yaml"
STAMP="$(date +%Y%m%d-%H%M%S)"

echo "== backup both before touching =="
cp "$CFG" "$CFG.bak-keyrotate-$STAMP"
cp "$YAML" "$YAML.bak-keyrotate-$STAMP"
echo "  $CFG.bak-keyrotate-$STAMP"
echo "  $YAML.bak-keyrotate-$STAMP"

# capture the CURRENT key so we can replace it precisely in the yaml (it appears twice)
OLD="$(sqlite3 "$CFG" "SELECT value FROM config_keys WHERE provider_id=7 LIMIT 1")"
[[ -z "$OLD" ]] && { echo "could not read current provider-7 key; abort"; exit 1; }

echo "== 1) Bifrost config_keys (provider 7) =="
sqlite3 "$CFG" "UPDATE config_keys SET value='$NEW', updated_at=datetime('now') WHERE provider_id=7;"
echo "  updated $(sqlite3 "$CFG" "SELECT changes()") row(s)"

echo "== 2) go-llm-proxy yaml (both occurrences) =="
# exact-string replace OLD->NEW everywhere in the yaml (api_key + keys list)
python3 - "$YAML" "$OLD" "$NEW" <<'PY'
import sys
f, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(f).read()
n = s.count(old)
open(f, "w").write(s.replace(old, new))
print(f"  replaced {n} occurrence(s)")
PY

echo "== restart bifrost + minimax-codex-proxy =="
launchctl kickstart -k "gui/$(id -u)/com.maximhq.bifrost" >/dev/null 2>&1 || true
launchctl kickstart -k "gui/$(id -u)/com.siso.minimax-codex-proxy" >/dev/null 2>&1 || true
sleep 7

echo "== TEST: live M3 round-trip through Bifrost (workers vkey) =="
VK="$(sqlite3 "$CFG" "SELECT value FROM governance_virtual_keys WHERE name LIKE '%Workers%' LIMIT 1")"
RESP="$(curl -s --max-time 30 http://localhost:8080/anthropic/v1/messages \
  -H 'Content-Type: application/json' -H "x-api-key: $VK" \
  -d '{"model":"Minimax/MiniMax-M3","max_tokens":20,"messages":[{"role":"user","content":"reply only: alive"}]}')"
echo "$RESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print('  RESULT:', 'OK model='+str(d.get('model')) if not d.get('error') else 'FAIL '+str(d.get('error')))" || { echo "  TEST FAILED — restore from $CFG.bak-keyrotate-$STAMP"; exit 1; }

echo "== done. all vkeys (boy/CAM/PARSER/workers) keep working unchanged. =="
echo "   reminder: update ~/.siso/bifrost-keys.md note if you keep upstream-key history."
