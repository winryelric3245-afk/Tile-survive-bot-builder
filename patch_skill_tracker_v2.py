#!/usr/bin/env python3
"""Upgrade Bob's global V1 skill tracker to per-timer skill tracking."""
import ast
import pathlib
import shutil
import sys
from datetime import datetime, timezone
import patch_skill_tracker as old

VERSION="# BOB_SKILL_TRACKER_V2"
SCHEMA='''
        # BOB_SKILL_TRACKER_V2: Non-destructive schema upgrade.
        columns={r["name"] for r in db.execute("PRAGMA table_info(timers)").fetchall()}
        upgrading="skills_used" not in columns
        if upgrading:
            db.execute("ALTER TABLE timers ADD COLUMN skills_used INTEGER NOT NULL DEFAULT 0")
        db.execute("""CREATE TABLE IF NOT EXISTS timer_skill_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, timer_id INTEGER NOT NULL,
            delta INTEGER NOT NULL, actor_id INTEGER NOT NULL,
            created_ts INTEGER NOT NULL)""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS cleanup_timer_skill_history
          AFTER DELETE ON timers BEGIN
            DELETE FROM timer_skill_history WHERE timer_id=OLD.id;
          END""")
        # Correct unambiguous research projects entered under Add Build.
        db.execute("""UPDATE timers SET timer_type='research'
                      WHERE timer_type='build' AND lower(project) LIKE '%research%'""")
        db.execute("""UPDATE timers SET timer_type='build'
                      WHERE timer_type='research' AND (
                      lower(project) LIKE '%power plant%' OR
                      lower(project) LIKE '%construction%' OR
                      lower(project) LIKE '%building%')""")
        # Carry over V1 counts only when the old player/type maps to a
        # single active timer; never spread one count across multiple timers.
        tables={r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if upgrading and "skill_usage" in tables:
            for old_record in db.execute("""SELECT guild_id,player_key,kind,count
                                    FROM skill_usage WHERE count>0""").fetchall():
                matches=db.execute("""SELECT id FROM timers
                    WHERE guild_id=? AND lower(trim(player))=? AND timer_type=?
                    AND completed=0 AND end_ts>strftime('%s','now')""",
                    (old_record["guild_id"],old_record["player_key"],old_record["kind"])).fetchall()
                if len(matches)==1:
                    db.execute("UPDATE timers SET skills_used=? WHERE id=?",
                        (old_record["count"],matches[0]["id"]))
'''
FEATURE='''
# BOB_SKILL_TRACKER_V2
def timer_skill_label(row):
    icon="🔨" if row["timer_type"]=="build" else "🔬"
    return f"{icon} {row['skills_used']} skills"

def adjust_timer_skill(guild_id,timer_id,delta,actor_id):
    if not isinstance(delta,int) or delta==0 or abs(delta)>10000:
        raise ValueError("Invalid skill amount.")
    with connect() as db:
        row=db.execute("SELECT * FROM timers WHERE guild_id=? AND id=?",
                       (guild_id,timer_id)).fetchone()
        if not row or row["completed"] or row["end_ts"]<=int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("This timer is missing, expired, or finished.")
        total=int(row["skills_used"])+delta
        if total<0:
            raise ValueError(f"Timer #{timer_id} only has {row['skills_used']} skills recorded.")
        db.execute("UPDATE timers SET skills_used=? WHERE guild_id=? AND id=?",
                   (total,guild_id,timer_id))
        db.execute("""INSERT INTO timer_skill_history
            (guild_id,timer_id,delta,actor_id,created_ts) VALUES(?,?,?,?,?)""",
            (guild_id,timer_id,delta,actor_id,int(datetime.now(timezone.utc).timestamp())))
    return row["player"],row["timer_type"],total

class SkillTimerSelect(discord.ui.Select):
    def __init__(self,rows):
        options=[discord.SelectOption(
            label=f"#{r['id']} {r['player']}"[:100],
            description=f"{r['timer_type'].title()} · {r['project']} · {r['skills_used']} skills"[:100],
            value=str(r["id"])) for r in rows[:25]]
        super().__init__(placeholder="Select a timer to add +1 skill",options=options)

    async def callback(self,interaction:discord.Interaction):
        timer_id=int(self.values[0])
        try:
            player,kind,total=adjust_timer_skill(interaction.guild_id,timer_id,1,interaction.user.id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc),ephemeral=True)
            return
        await interaction.response.edit_message(
            content=f"+1 {kind} skill for **#{timer_id} {player}**. Used: **{total}**.",view=None)
        await refresh_board(interaction.guild_id)

class SkillTimerPicker(discord.ui.View):
    def __init__(self,rows):
        super().__init__(timeout=120)
        self.add_item(SkillTimerSelect(rows))

async def open_skill_picker(interaction:discord.Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("Server only.",ephemeral=True)
        return
    with connect() as db:
        rows=db.execute("""SELECT * FROM timers WHERE guild_id=? AND completed=0
            AND end_ts>strftime('%s','now') ORDER BY priority DESC,end_ts DESC LIMIT 25""",
            (interaction.guild_id,)).fetchall()
    if not rows:
        await interaction.response.send_message("No active timers.",ephemeral=True)
        return
    await interaction.response.send_message(
        "Choose the timer that received one 15% skill:",view=SkillTimerPicker(rows),ephemeral=True)

'''
BOARD='''
    @discord.ui.button(label="+ Skill",emoji="✨",style=discord.ButtonStyle.success,
                       custom_id="helper:skill_add_v2")
    async def add_skill(self,interaction:discord.Interaction,button:discord.ui.Button):
        await open_skill_picker(interaction)

'''
MANAGE='''
    @discord.ui.button(label="+ Skill",style=discord.ButtonStyle.success)
    async def skill_plus(self,interaction:discord.Interaction,button:discord.ui.Button):
        try:
            player,kind,total=adjust_timer_skill(
                interaction.guild_id,self.timer_id,1,interaction.user.id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc),ephemeral=True)
            return
        await interaction.response.edit_message(
            content=f"+1 {kind} skill for **#{self.timer_id} {player}**. Used: **{total}**.",view=None)
        await refresh_board(interaction.guild_id)

'''
COMMANDS='''
@app_commands.guild_only()
@bot.tree.command(name="skilladd",description="Add a skill to a specific timer")
async def skilladd(interaction:discord.Interaction,timer_id:int,amount:app_commands.Range[int,1,100]=1):
    try:
        player,kind,total=adjust_timer_skill(interaction.guild_id,timer_id,int(amount),interaction.user.id)
    except ValueError as exc:
        await interaction.response.send_message(str(exc),ephemeral=True);return
    await interaction.response.send_message(
        f"Added {amount} {kind} skill(s) to #{timer_id} {player}; used: {total}.",ephemeral=True)
    await refresh_board(interaction.guild_id)

@app_commands.guild_only()
@bot.tree.command(name="skillremove",description="Admin: correct skill usage on a timer")
async def skillremove(interaction:discord.Interaction,timer_id:int,amount:app_commands.Range[int,1,100]=1):
    if not can_manage(interaction):
        await interaction.response.send_message("Only server managers can remove skills.",ephemeral=True);return
    try:
        player,kind,total=adjust_timer_skill(interaction.guild_id,timer_id,-int(amount),interaction.user.id)
    except ValueError as exc:
        await interaction.response.send_message(str(exc),ephemeral=True);return
    await interaction.response.send_message(
        f"Removed {amount} {kind} skill(s) from #{timer_id} {player}; remaining: {total}.",ephemeral=True)
    await refresh_board(interaction.guild_id)

@app_commands.guild_only()
@bot.tree.command(name="skills",description="Show skill counts for individual active timers")
async def skills(interaction:discord.Interaction):
    with connect() as db:
        rows=db.execute("""SELECT id,player,timer_type,skills_used FROM timers
            WHERE guild_id=? AND completed=0 AND end_ts>strftime('%s','now')
            ORDER BY timer_type,priority DESC,end_ts DESC LIMIT 50""",
            (interaction.guild_id,)).fetchall()
    report="\\n".join(f"#{r['id']} {r['player']} · {timer_skill_label(r)}" for r in rows)
    await interaction.response.send_message(report[:1900] if report else "No active timers.",ephemeral=True)

'''

def replace_once(src,needle,replacement,description):
    n=src.count(needle)
    if n!=1: raise ValueError(f"Unexpected bot layout for {description}: {n} matches. No changes.")
    return src.replace(needle,replacement,1)

def patch(path):
    source=path.read_text(encoding="utf-8")
    if VERSION in source:
        print("V2 already installed");return False
    if "class HelperButtons(discord.ui.View):" not in source:
        raise ValueError("Bob bot file not found.")
    out=source
    if old.MARKER in source:
        for block,description in [(old.SCHEMA,"V1 database"),(old.FEATURE,"V1 tracker"),
                                  (old.BUTTONS,"V1 buttons"),(old.COMMANDS,"V1 commands")]:
            out=replace_once(out,block,"",description)
        old_display=" · 🔨 {skill_count(guild_id, r['player'], 'build')}  🔬 {skill_count(guild_id, r['player'], 'research')}"
        out=replace_once(out,old_display," · {timer_skill_label(r)}","V1 board")
    else:
        base="ends <t:{r['end_ts']}:R>"
        out=replace_once(out,base,base+" · {timer_skill_label(r)}","board")
    out=replace_once(out,"\ndef human_remaining(", "\n"+SCHEMA+"\ndef human_remaining(","database")
    out=replace_once(out,"class HelperButtons(discord.ui.View):",
                     FEATURE+"\nclass HelperButtons(discord.ui.View):","methods")
    anchor="class HelperButtons(discord.ui.View):\n    def __init__(self):\n        super().__init__(timeout=None)"
    out=replace_once(out,anchor,anchor+"\n"+BOARD,"board button")
    anchor='    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary)'
    out=replace_once(out,anchor,MANAGE+"\n"+anchor,"manage timer button")
    nodes=ast.parse(out)
    assignment=next((node for node in nodes.body if isinstance(node,(ast.Assign,ast.AnnAssign))
        and any(isinstance(t,ast.Name) and t.id=="bot"
          for t in (node.targets if isinstance(node,ast.Assign) else [node.target]))),None)
    if assignment is None: raise ValueError("Bot instance not found.")
    lines=out.splitlines(keepends=True)
    lines.insert(assignment.end_lineno,"\n"+COMMANDS+"\n")
    out="".join(lines)
    ast.parse(out)
    compile(out,str(path),"exec")
    backup=path.with_name(path.name+".backup-skills-v2-"+datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path,backup)
    path.write_text(out,encoding="utf-8")
    print("V2 updated; timer data preserved. Backup:",backup)
    return True

if __name__=="__main__":
    if len(sys.argv)!=2: sys.exit("Usage: python3 patch_skill_tracker_v2.py /path/to/bot.py")
    try: patch(pathlib.Path(sys.argv[1]).resolve())
    except Exception as exc: sys.exit("NOT PATCHED: "+str(exc))
