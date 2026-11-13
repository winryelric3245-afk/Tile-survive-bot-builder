#!/usr/bin/env python3
"""Safely add build/research skill-use tracking to Bob the Builder (discord.py)."""
import ast
import pathlib
import re
import shutil
import sys
import time

MARKER = "# BOB_SKILL_TRACKER_V1"
FEATURE = '''
# BOB_SKILL_TRACKER_V1
def skill_count(guild_id, player, kind):
    with connect() as db:
        row = db.execute(
            "SELECT count FROM skill_usage WHERE guild_id=? AND player_key=? AND kind=?",
            (guild_id, player.strip().casefold(), kind),
        ).fetchone()
    return int(row["count"]) if row else 0


def skill_change(guild_id, player, kind, delta, actor_id):
    player = player.strip()
    if not player or kind not in ("build", "research") or not isinstance(delta, int) or delta == 0:
        raise ValueError("Invalid skill usage update")
    now = int(datetime.now(timezone.utc).timestamp())
    with connect() as db:
        old = db.execute(
            "SELECT count FROM skill_usage WHERE guild_id=? AND player_key=? AND kind=?",
            (guild_id, player.casefold(), kind),
        ).fetchone()
        current = int(old["count"]) if old else 0
        if current + delta < 0:
            raise ValueError(f"Only {current} {kind} skills recorded for {player}.")
        db.execute("""
            INSERT INTO skill_usage(guild_id,player_key,player_name,kind,count)
            VALUES(?,?,?,?,?)
            ON CONFLICT(guild_id,player_key,kind) DO UPDATE SET
              count=excluded.count, player_name=excluded.player_name
        """, (guild_id, player.casefold(), player, kind, current + delta))
        db.execute("""
            INSERT INTO skill_history(guild_id,player_name,kind,delta,actor_id,created_ts)
            VALUES(?,?,?,?,?,?)
        """, (guild_id, player, kind, delta, actor_id, now))
    return current + delta


class SkillTargetSelect(discord.ui.Select):
    def __init__(self, kind, names):
        self.kind = kind
        options = [
            discord.SelectOption(
                label=name[:100],
                value=name,
                description=f"Recorded: {skill_count_dummy} skills" if False else f"Add one {kind} skill",
            )
            for name in names[:25]
        ]
        super().__init__(placeholder=f"Who received a {kind} skill?", options=options)

    async def callback(self, interaction):
        player = self.values[0]
        try:
            new_total = skill_change(interaction.guild_id, player, self.kind, 1, interaction.user.id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.edit_message(
            content=f"Added 1 {self.kind} skill to **{player}**. Total: **{new_total}**.",
            view=None,
        )
        await refresh_board(interaction.guild_id)


class SkillTargetView(discord.ui.View):
    def __init__(self, kind, names):
        super().__init__(timeout=120)
        self.add_item(SkillTargetSelect(kind, names))


async def open_skill_picker(interaction, kind):
    if not interaction.guild_id:
        await interaction.response.send_message("Use this inside the server.", ephemeral=True)
        return
    now = int(datetime.now(timezone.utc).timestamp())
    with connect() as db:
        rows = db.execute(
            """SELECT DISTINCT player FROM timers
               WHERE guild_id=? AND completed=0 AND end_ts>?
               AND timer_type=?
               ORDER BY player COLLATE NOCASE LIMIT 25""",
            (interaction.guild_id, now, kind),
        ).fetchall()
    names = [row["player"] for row in rows]
    if not names:
        await interaction.response.send_message(
            f"No active {kind} timers. Add a timer first, or use /skilladd.",
            ephemeral=True,
        )
        return
    await interaction.response.send_message(
        f"Select a player to record **one {kind} skill (15% reduction)**:",
        view=SkillTargetView(kind, names),
        ephemeral=True,
    )

'''
SCHEMA = '''
        db.execute("""
            CREATE TABLE IF NOT EXISTS skill_usage (
                guild_id INTEGER NOT NULL,
                player_key TEXT NOT NULL,
                player_name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('build','research')),
                count INTEGER NOT NULL DEFAULT 0 CHECK(count >= 0),
                PRIMARY KEY(guild_id,player_key,kind)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS skill_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                player_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                delta INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,
                created_ts INTEGER NOT NULL
            )
        """)
'''
BUTTONS = '''
    @discord.ui.button(label="Build Skill +1", emoji="🔨", style=discord.ButtonStyle.success,
                       row=1, custom_id="helper:skill_build")
    async def skill_build(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_skill_picker(interaction, "build")

    @discord.ui.button(label="Research Skill +1", emoji="🔬", style=discord.ButtonStyle.success,
                       row=1, custom_id="helper:skill_research")
    async def skill_research(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_skill_picker(interaction, "research")

'''
COMMANDS = '''
# Skill tracking commands (registered on the existing Discord bot)
@bot.tree.command(name="skillremove", description="Admin: remove mistakenly recorded skills")
@app_commands.describe(player="Player name", skill_type="build or research", amount="Number to remove")
async def skillremove(interaction: discord.Interaction, player: str, skill_type: str, amount: int = 1):
    if not can_manage(interaction):
        await interaction.response.send_message("Only server managers can remove skills.", ephemeral=True)
        return
    if skill_type.lower() not in ("build", "research") or amount < 1 or amount > 10000:
        await interaction.response.send_message("Use build or research and a positive amount.", ephemeral=True)
        return
    try:
        total = skill_change(interaction.guild_id, player, skill_type.lower(), -amount, interaction.user.id)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    await interaction.response.send_message(
        f"Removed {amount} {skill_type} skill(s) from **{player}**. Remaining: **{total}**.",
        ephemeral=True,
    )
    await refresh_board(interaction.guild_id)


@bot.tree.command(name="skilladd", description="Record skill use for any player (including no active timer)")
@app_commands.describe(player="Player name", skill_type="build or research", amount="Number used")
async def skilladd(interaction: discord.Interaction, player: str, skill_type: str, amount: int = 1):
    if not interaction.guild_id or skill_type.lower() not in ("build", "research") or amount < 1 or amount > 10000:
        await interaction.response.send_message("Use a server, build/research, and a positive amount.", ephemeral=True)
        return
    total = skill_change(interaction.guild_id, player, skill_type.lower(), amount, interaction.user.id)
    await interaction.response.send_message(
        f"Added {amount} {skill_type} skill(s) to **{player}**. Total: **{total}**.",
        ephemeral=True,
    )
    await refresh_board(interaction.guild_id)


@bot.tree.command(name="skills", description="Show recorded build and research skill usage")
async def skills(interaction: discord.Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("Use this inside the server.", ephemeral=True)
        return
    with connect() as db:
        rows = db.execute("""
            SELECT player_key, MAX(player_name) AS player_name,
                   SUM(CASE WHEN kind='build' THEN count ELSE 0 END) AS build_count,
                   SUM(CASE WHEN kind='research' THEN count ELSE 0 END) AS research_count
            FROM skill_usage WHERE guild_id=?
            GROUP BY player_key ORDER BY player_name COLLATE NOCASE LIMIT 50
        """, (interaction.guild_id,)).fetchall()
    body = "\\n".join(
        f"🔨 **{r['build_count']}**  🔬 **{r['research_count']}** — {r['player_name']}"
        for r in rows
    )
    await interaction.response.send_message(body[:1900] if body else "No skills recorded yet.", ephemeral=True)

'''

def patch(path):
    original = path.read_text(encoding="utf-8")
    if MARKER in original:
        print("Already installed; no file changes made.")
        return False
    if "def init_db():" not in original or "class HelperButtons(discord.ui.View):" not in original:
        raise RuntimeError("Unexpected bot version: missing database or board button anchors.")
    if "def human_remaining(" not in original:
        raise RuntimeError("Unexpected bot version: missing timer anchor.")
    doc = ast.parse(original)
    bot_assign = None
    for node in doc.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "bot" for t in targets):
                bot_assign = node
                break
    if not bot_assign:
        raise RuntimeError("Could not locate bot initialization; no changes made.")

    updated = original
    # Add schema inside the existing init_db database transaction.
    pos = updated.index("\ndef human_remaining(")
    updated = updated[:pos] + SCHEMA + "\n" + updated[pos:]
    # Add small persistent tracker helpers and ephemeral per-player picker.
    updated = updated.replace("class HelperButtons(discord.ui.View):", FEATURE + "\nclass HelperButtons(discord.ui.View):", 1)
    # Place controls on the second action row without disturbing existing buttons.
    anchor = "class HelperButtons(discord.ui.View):\n    def __init__(self):\n        super().__init__(timeout=None)"
    if anchor not in updated:
        raise RuntimeError("Unexpected HelperButtons layout; no changes made.")
    updated = updated.replace(anchor, anchor + "\n" + BUTTONS, 1)

    # Counters displayed on every qualifying build/research player timer.
    token = "ends <t:{r['end_ts']}:R>"
    if token not in updated:
        raise RuntimeError("Timer display template not found; no changes made.")
    updated = updated.replace(token, token + " · 🔨 {skill_count(guild_id, r['player'], 'build')}  🔬 {skill_count(guild_id, r['player'], 'research')}", 1)

    # Insert commands immediately after bot initialization, before startup.
    parsed = ast.parse(updated)
    assign = None
    for node in parsed.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "bot" for t in targets):
                assign = node
                break
    if assign is None:
        raise RuntimeError("Could not locate bot initialization after edit.")
    lines = updated.splitlines(keepends=True)
    lines.insert(assign.end_lineno, "\n" + COMMANDS + "\n")
    updated = "".join(lines)
    ast.parse(updated)
    compile(updated, str(path), "exec")

    backup = path.with_name(path.name + ".backup-skills-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, backup)
    path.write_text(updated, encoding="utf-8")
    print("Installed skill tracker. Backup:", backup)
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 patch_skill_tracker.py /absolute/path/to/bot.py")
    try:
        patch(pathlib.Path(sys.argv[1]).resolve())
    except Exception as exc:
        sys.exit(f"NOT PATCHED: {exc}")
