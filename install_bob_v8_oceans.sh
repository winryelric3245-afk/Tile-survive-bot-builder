#!/usr/bin/env bash
# Install Bob v8 on the existing DigitalOcean host without replacing timer data.
set -euo pipefail
BASE="https://raw.githubusercontent.com/winryelric3245-afk/Tile-survive-bot-builder/main"
PATCH="/tmp/patch_member_skill_controls_v8.py"
echo "Locating Bob's live bot.py..."
mapfile -d '' CANDIDATES < <(find /opt /root /home /srv /app /workspace \( -type d \( -name backups -o -name backup -o -name .venv -o -name venv -o -name site-packages \) -prune \) -o \( -type f -name bot.py -print0 \) 2>/dev/null || true)
MATCHES=()
for f in "${CANDIDATES[@]}"; do
  if grep -q 'class HelperButtons(discord.ui.View):' "$f" && grep -q 'def apply_skill(' "$f" && grep -q 'class UndoSkillSelect(' "$f"; then
    MATCHES+=("$f")
  fi
done
if [[ ${#MATCHES[@]} -ne 1 ]]; then
  echo "Expected exactly one compatible Bob installation; found ${#MATCHES[@]}. Nothing changed."
  printf 'Candidate: %s\n' "${MATCHES[@]}"
  exit 1
fi
BOT="${MATCHES[0]}"
DIR="$(dirname "$BOT")"
echo "Bot: $BOT"
TS="$(date +%Y%m%d-%H%M%S)"
cp -p "$BOT" "$BOT.backup-v8-$TS"
DB="$DIR/helper_bot.db"
if [[ -f "$DIR/.env" ]]; then
  DBSETTING="$(sed -n 's/^DB_PATH=//p' "$DIR/.env" | tail -1 | tr -d '\042\047')"
  if [[ -n "$DBSETTING" ]]; then
    if [[ "$DBSETTING" = /* ]]; then DB="$DBSETTING"; else DB="$DIR/$DBSETTING"; fi
  fi
fi
if [[ -f "$DB" ]]; then
  cp -p "$DB" "$DB.backup-v8-$TS"
  echo "Timer database backed up."
fi
curl -fsSL "$BASE/patch_member_skill_controls_v8.py" -o "$PATCH"
if ! python3 "$PATCH" "$BOT" || ! python3 -m py_compile "$BOT"; then
  cp -p "$BOT.backup-v8-$TS" "$BOT"
  echo "Update failed; restored original bot.py."
  exit 1
fi
echo "Code updated. Looking for service..."
SERVICES=()
while read -r service; do
  [[ -z "$service" ]] && continue
  execstart="$(systemctl show "$service" -p ExecStart --value 2>/dev/null || true)"
  if [[ "$execstart" == *"$BOT"* ]] || [[ "$execstart" == *"$DIR"* && "$execstart" == *"python"* ]]; then
    SERVICES+=("$service")
  fi
done < <(systemctl list-units --all --type=service --no-legend --plain 2>/dev/null | awk '{print $1}')
if [[ ${#SERVICES[@]} -eq 1 ]]; then
  systemctl restart "${SERVICES[0]}"
  systemctl is-active --quiet "${SERVICES[0]}" || { echo "WARNING: service did not start; restore from $BOT.backup-v8-$TS"; exit 1; }
  echo "SUCCESS: ${SERVICES[0]} is running Bob v8."
else
  echo "Bot code updated, but service not restarted (matching services: ${#SERVICES[@]})."
  printf 'Matching service: %s\n' "${SERVICES[@]}"
  echo "Restart only the Bob service through your existing process manager."
fi
