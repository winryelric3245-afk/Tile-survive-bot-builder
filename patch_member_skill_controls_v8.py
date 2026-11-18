#!/usr/bin/env python3
"""Enable safe member self-service for Bob v7's existing +Skill/-Skill workflow."""
import ast, pathlib, shutil, sys
from datetime import datetime,timezone

MARKER="# BOB_MEMBER_SKILL_CONTROLS_V8"
HELPERS='''
# BOB_MEMBER_SKILL_CONTROLS_V8
def member_skill_access(interaction, timer_type, player, timer_id=None):
    """Managers can modify any matching timer; members only their own."""
    if can_manage(interaction):
        return True
    if not interaction.guild_id or timer_type not in ("build", "research"):
        return False
    now=int(datetime.now(timezone.utc).timestamp())
    with connect() as db:
        rows=db.execute("""SELECT * FROM timers WHERE guild_id=? AND timer_type=?
            AND player=? COLLATE NOCASE AND completed=0 AND end_ts>?""",
            (interaction.guild_id,timer_type,player,now)).fetchall()
    if timer_id is not None:
        rows=[r for r in rows if r["id"]==timer_id]
    return bool(rows) and all(
        r["owner_id"]==interaction.user.id or r["created_by"]==interaction.user.id
        for r in rows)

def member_event_access(interaction, event):
    if not event:
        return False
    if can_manage(interaction):
        return True
    if event["guild_id"]!=interaction.guild_id or event["actor_id"]!=interaction.user.id:
        return False
    entries=json.loads(event["before_json"])
    if not entries:
        return False
    with connect() as db:
        for entry in entries:
            row=db.execute("SELECT * FROM timers WHERE id=? AND guild_id=?",
                           (entry[0],interaction.guild_id)).fetchone()
            if not row or not (row["owner_id"]==interaction.user.id or
                               row["created_by"]==interaction.user.id):
                return False
    return True

'''
def replace_once(s,old,new):
    n=s.count(old)
    if n!=1:
        raise ValueError(f"Expected one anchor, found {n}: {old[:95]!r}")
    return s.replace(old,new,1)

def patch(path):
    original=path.read_text(encoding="utf-8")
    if MARKER in original:
        print("Already updated");return False
    required=["class HelperButtons(discord.ui.View):","class SkillPercentView(discord.ui.View):",
              "class UndoSkillSelect(discord.ui.Select):","async def undoskill(",
              "async def skill("]
    for item in required:
        if item not in original: raise ValueError("Unsupported Bob version: "+item)
    s=original
    # Add permission checks before changes are made, not just in the UI.
    s=replace_once(s,"def row_accessible(",HELPERS+"def row_accessible(")
    s=replace_once(s,'''        if not can_manage(interaction):
            await interaction.response.send_message("Only managers can apply skills.", ephemeral=True)
            return
        event_id, count = apply_skill''','''        if not member_skill_access(interaction,self.timer_type,self.player):
            await interaction.response.send_message("You can only use skills on your own timers.",ephemeral=True)
            return
        event_id, count = apply_skill''')
    s=replace_once(s,'''        if not can_manage(interaction):
            await interaction.response.send_message("Only managers can apply skills.", ephemeral=True)
            return
        player = self.players[int(self.values[0])]''','''        player = self.players[int(self.values[0])]
        if not member_skill_access(interaction,self.timer_type,player):
            await interaction.response.send_message("You can only use skills on your own timers.",ephemeral=True)
            return''')
    s=replace_once(s,'''        players = [r["player"] for r in rows]''','''        players = [r["player"] for r in rows if member_skill_access(interaction,timer_type,r["player"])]''')
    s=replace_once(s,'''        if not can_manage(interaction):
            await interaction.response.send_message("Only managers can apply skills.", ephemeral=True); return
        await interaction.response.send_message("Which skill was used?"''','''        await interaction.response.send_message("Which skill was used?"''')
    s=replace_once(s,'''        if not can_manage(interaction):
            await interaction.response.send_message("Only managers can undo skills.", ephemeral=True); return
        with connect() as db:''','''        with connect() as db:''')
    s=replace_once(s,'''            events = db.execute("SELECT * FROM skill_events WHERE guild_id=? AND undone=0 ORDER BY id DESC LIMIT 25", (interaction.guild_id,)).fetchall()
        if not events:''','''            events = db.execute("SELECT * FROM skill_events WHERE guild_id=? AND undone=0 ORDER BY id DESC LIMIT 250", (interaction.guild_id,)).fetchall()
        events=[e for e in events if member_event_access(interaction,e)][:25]
        if not events:''')
    s=replace_once(s,'''        if not can_manage(interaction):
            await interaction.response.send_message("Only managers can undo skills.", ephemeral=True); return
        event_id = int(self.values[0])''','''        event_id = int(self.values[0])''')
    # UI and slash command both re-check access at the moment of use.
    s=replace_once(s,'''            before = json.loads(ev["before_json"])
            for entry in before:''','''            if not member_event_access(interaction,ev):
                await interaction.response.edit_message(content="You can only undo your own skill events.",view=None); return
            before = json.loads(ev["before_json"])
            for entry in before:''')
    s=replace_once(s,'''    if not can_manage(interaction):
        await interaction.response.send_message("Only managers can record skill usage.",ephemeral=True); return
    if percent not in (5, 10, 15):''','''    if percent not in (5, 10, 15):''')
    s=replace_once(s,'''    event_id,count=apply_skill(interaction.guild_id,interaction.user.id,timer_type.value,player,percent,timer_id or None)''','''    if not member_skill_access(interaction,timer_type.value,player,timer_id or None):
        await interaction.response.send_message("You can only record skills on your own matching timers.",ephemeral=True); return
    event_id,count=apply_skill(interaction.guild_id,interaction.user.id,timer_type.value,player,percent,timer_id or None)''')
    s=replace_once(s,'''        if not ev: await interaction.response.send_message("Event not found or already undone.",ephemeral=True); return
        # Refuse unsafe undo''','''        if not ev: await interaction.response.send_message("Event not found or already undone.",ephemeral=True); return
        if not member_event_access(interaction,ev):
            await interaction.response.send_message("You can only undo your own skill events.",ephemeral=True); return
        # Refuse unsafe undo''')
    ast.parse(s)
    compile(s,str(path),"exec")
    backup=path.with_suffix(path.suffix+".backup-before-v8-"+datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
    shutil.copy2(path,backup)
    path.write_text(s,encoding="utf-8")
    print("Updated member skill controls; backup:",backup)
    return True

if __name__=="__main__":
    if len(sys.argv)!=2: sys.exit("Usage: python patch_member_skill_controls_v8.py /path/to/bot.py")
    try: patch(pathlib.Path(sys.argv[1]).resolve())
    except Exception as exc: sys.exit("NOT PATCHED: "+str(exc))
