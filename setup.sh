#!/bin/bash
# Установка vkteams-mcp в Claude Desktop (macOS).
# Использование: ./setup.sh 'AIMSID' 'login@company.ru' ['FETCH_URL']
set -e
AIMSID="$1"; SN="$2"; FETCH="${3:-}"
[ -n "$AIMSID" ] && [ -n "$SN" ] || { echo "Использование: $0 'AIMSID' 'login@company.ru'"; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)
"$PY" -c 'import sys; assert sys.version_info>=(3,10), "нужен Python 3.10+, сейчас "+sys.version'
"$PY" -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"

CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
mkdir -p "$(dirname "$CFG")"; [ -f "$CFG" ] || echo '{}' > "$CFG"
cp "$CFG" "$CFG.bak.$(date +%s)"
"$DIR/.venv/bin/python" - "$CFG" "$DIR" "$AIMSID" "$SN" "$FETCH" <<'PY'
import json, sys
cfg, d, aimsid, sn, fetch = sys.argv[1:6]
c = json.load(open(cfg))
c.setdefault("mcpServers", {})["vkteams"] = {
    "command": f"{d}/.venv/bin/python",
    "args": [f"{d}/vkteams_mcp.py"],
    "env": {"VKTEAMS_AIMSID": aimsid, "VKTEAMS_SN": sn, "VKTEAMS_FETCH_URL": fetch},
}
json.dump(c, open(cfg, "w"), indent=2, ensure_ascii=False)
print("vkteams добавлен в", cfg)
PY
osascript -e 'quit app "Claude"' 2>/dev/null || true; sleep 3; open -a Claude
echo "Готово, Claude Desktop перезапущен."
