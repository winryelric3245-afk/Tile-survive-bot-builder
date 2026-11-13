#!/usr/bin/env bash
set -euo pipefail
REPO="https://raw.githubusercontent.com/winryelric3245-afk/Tile-survive-bot-builder/main"
PATCH="/tmp/bob_patch_skill_tracker.py"
echo "Locating the existing Bob the Builder installation..."
mapfile -d '' CANDIDATES < <(
  find /opt /root /home /srv -type f -name bot.py \
    ! -path '*/.venv/*' ! -path '*/venv/*' \
    ! -path '*/site-packages/*' 2>/dev/null -print0 || true
)
MATCHES=()
for path in "${CANDIDATES[@]}"; do
  if grep -q 'class HelperButtons(discord.ui.View):' "$path" \
     && grep -q 'def init_db():' "$path"; then
    MATCHES+=("$path")
  fi
done
if [ "${#MATCHES[@]}" -ne 1 ]; then
  echo "Expected exactly one Bob bot.py; found ${#MATCHES[@]}."
  printf 'Candidate: %s\n' "${MATCHES[@]}"
  echo "No changes were made."
  exit 1
fi
BOT="${MATCHES[0]}"
BOT_DIR="$(dirname "$BOT")"
echo "Found Bob bot: $BOT"
DBFILE="$BOT_DIR/helper_bot.db"
if [ -f "$BOT_DIR/.env" ]; then
  DBNAME="$(sed -n 's/^DB_PATH=//p' "$BOT_DIR/.env" | tail -1 | tr -d '"' | tr -d "'")"
  if [ -n "$DBNAME" ]; then
    if [[ "$DBNAME" = /* ]]; then DBFILE="$DBNAME"; else DBFILE="$BOT_DIR/$DBNAME"; fi
  fi
fi
if [ -f "$DBFILE" ]; then
  cp -p "$DBFILE" "$DBFILE.backup-skills-$(date +%Y%m%d-%H%M%S)"
  echo "Backed up existing player/timer database."
fi
curl -fsSL "$REPO/patch_skill_tracker.py" -o "$PATCH"
python3 "$PATCH" "$BOT"
python3 -m py_compile "$BOT"
SERVICES=()
while read -r service; do
  [ -z "$service" ] && continue
  execstart="$(systemctl show "$service" -p ExecStart --value 2>/dev/null || true)"
  if [[ "$execstart" == *"$BOT"* ]]; then SERVICES+=("$service"); fi
done < <(systemctl list-units --all --type=service --no-legend --plain 2>/dev/null | awk '{print $1}')
if [ "${#SERVICES[@]}" -eq 1 ]; then
  echo "Restarting ${SERVICES[0]}..."
  systemctl restart "${SERVICES[0]}"
  systemctl --no-pager --full status "${SERVICES[0]}" | head -20
elif [ "${#SERVICES[@]}" -eq 0 ]; then
  echo "Code updated, but no matching systemd service found. Restart Bob using its current process manager."
else
  printf 'More than one matching service: %s\n' "${SERVICES[*]}"
  echo "No restart performed; choose the correct Bob service."
fi
echo "Check /skills, /skilladd and /skillremove in Discord."
