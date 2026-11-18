#!/usr/bin/env python3
"""Bob v9: fix active timer visibility for non-manager skill users.

Members may record skills on any active timer of the chosen type. They may
undo their own skill events; managers may undo all. Existing safety checks
still prevent undo after a timer was changed or received subsequent skills.
"""
import ast
import pathlib
import shutil
import sys
from datetime import datetime, timezone

MARKER="# BOB_MEMBER_SKILL_VISIBILITY_V9"

ACCESS='''def member_skill_access(interaction, timer_type, player, timer_id=None):
    """All server members can use skills on active matching build/research timers."""
    if not interaction.guild_id or timer_type not in ("build", "research"):
        return False
    now=int(datetime.now(timezone.utc).timestamp())
    with connect() as db:
        rows=db.execute("""SELECT id FROM timers WHERE guild_id=? AND timer_type=?
            AND lower(trim(player))=lower(trim(?)) AND completed=0 AND end_ts>?""",
            (interaction.guild_id,timer_type,player,now)).fetchall()
    if timer_id is not None:
        rows=[r for r in rows if r["id"]==timer_id]
    return bool(rows)
'''
EVENT='''def member_event_access(interaction, event):
    """Users can undo only their own recordings; managers may undo any."""
    if not event or not interaction.guild_id or event["guild_id"]!=interaction.guild_id:
        return False
    if can_manage(interaction):
        return True
    return event["actor_id"]==interaction.user.id
'''

def replace_function(src,name,replacement):
    tree=ast.parse(src)
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    if len(nodes)!=1:
        raise ValueError(f"Expected one {name}, found {len(nodes)}")
    node=nodes[0]
    lines=src.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno]=[replacement+"\n"]
    return "".join(lines)

def patch(path):
    old=path.read_text(encoding="utf-8")
    if MARKER in old:
        print("Bob v9 already installed");return False
    if "# BOB_MEMBER_SKILL_CONTROLS_V8" not in old:
        raise ValueError("Bob v8 not installed; nothing changed")
    src=replace_function(old,"member_skill_access",ACCESS)
    src=replace_function(src,"member_event_access",EVENT)
    # The picker already filters through member_skill_access. It now
    # lists all active timers instead of hiding other people's timers.
    src=src.replace('# BOB_MEMBER_SKILL_CONTROLS_V8',
                    MARKER+'\n# BOB_MEMBER_SKILL_CONTROLS_V8',1)
    ast.parse(src)
    compile(src,str(path),"exec")
    backup=path.with_name(path.name+".backup-v9-"+datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
    shutil.copy2(path,backup)
    path.write_text(src,encoding="utf-8")
    print("Bob v9 updated; backup:",backup)
    return True

if __name__=="__main__":
    if len(sys.argv)!=2:sys.exit("Usage: python3 patch_member_skills_v9.py /path/to/bot.py")
    try:patch(pathlib.Path(sys.argv[1]).resolve())
    except Exception as exc:sys.exit("NOT PATCHED: "+str(exc))
