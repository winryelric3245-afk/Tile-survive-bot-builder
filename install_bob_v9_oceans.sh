#!/usr/bin/env bash
# Bob v9 permission/visibility fix for the verified live installation.
set -euo pipefail
BOT="/opt/bob/x/Tile_Survivor_Helper_Bot/bot.py"
REPO="https://raw.githubusercontent.com/winryelric3245-afk/Tile-survive-bot-builder/main"
echo "Installing Bob v9 member skill visibility correction..."
if [[ ! -f "$BOT" ]]; then echo "Live bot file not found; no changes made.";exit 1;fi
if ! grep -q 'BOB_MEMBER_SKILL_CONTROLS_V8' "$BOT"; then
 echo "Bob v8 not detected; leaving existing bot unchanged.";exit 1
fi
DIR="$(dirname "$BOT")"
STAMP="$(date +%Y%m%d-%H%M%S)"
cp -p "$BOT" "$BOT.backup-before-v9-$STAMP"
DB="$DIR/helper_bot.db"
if [[ -f "$DIR/.env" ]]; then
  DBSETTING="$(sed -n 's/^DB_PATH=//p' "$DIR/.env" | tail -1 | tr -d '\042\047')"
  if [[ -n "$DBSETTING" ]]; then
    if [[ "$DBSETTING" = /* ]]; then DB="$DBSETTING"; else DB="$DIR/$DBSETTING";fi
  fi
fi
if [[ -f "$DB" ]]; then cp -p "$DB" "$DB.backup-before-v9-$STAMP";echo "Database backed up.";fi
curl -fsSL "$REPO/patch_member_skills_v9.py" -o /tmp/patch_member_skills_v9.py
if ! python3 /tmp/patch_member_skills_v9.py "$BOT" || ! python3 -m py_compile "$BOT"; then
 cp -p "$BOT.backup-before-v9-$STAMP" "$BOT"
 echo "Update failed; previous source restored.";exit 1
fi
systemctl restart bob.service
if systemctl is-active --quiet bob.service; then
  echo "SUCCESS: bob.service running with Bob v9 member skill visibility fix."
else
  cp -p "$BOT.backup-before-v9-$STAMP" "$BOT"
  systemctl restart bob.service || true
  echo "ERROR: v9 restart failed. Restored v8 source; review service logs."
  exit 1
fi
