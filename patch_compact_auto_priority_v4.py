#!/usr/bin/env python3
"""V4 compact one-line board and auto priority, without removing any buttons."""
import ast
import pathlib
import shutil
import sys
from datetime import datetime, timezone

MARKER="# BOB_COMPACT_AUTO_PRIORITY_V4"
SCHEMA='''
        # BOB_COMPACT_AUTO_PRIORITY_V4
        cols={r["name"] for r in db.execute("PRAGMA table_info(timers)").fetchall()}
        if "priority_override" not in cols:
            db.execute("ALTER TABLE timers ADD COLUMN priority_override INTEGER NOT NULL DEFAULT 0")
            # Existing priorities remain unchanged until their duration is edited.
        db.execute("""CREATE TRIGGER IF NOT EXISTS bob_auto_priority_insert
          AFTER INSERT ON timers WHEN NEW.priority_override=0 BEGIN
            UPDATE timers SET priority=CASE
                WHEN (NEW.end_ts-NEW.created_ts)>=2592000 THEN 4
                WHEN (NEW.end_ts-NEW.created_ts)>=1728000 THEN 3
                WHEN (NEW.end_ts-NEW.created_ts)>=864000 THEN 2
                ELSE 1 END
            WHERE id=NEW.id;
          END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS bob_auto_priority_timer_edit
          AFTER UPDATE OF end_ts ON timers WHEN NEW.priority_override=0 BEGIN
            UPDATE timers SET priority=CASE
                WHEN (NEW.end_ts-CAST(strftime('%s','now') AS INTEGER))>=2592000 THEN 4
                WHEN (NEW.end_ts-CAST(strftime('%s','now') AS INTEGER))>=1728000 THEN 3
                WHEN (NEW.end_ts-CAST(strftime('%s','now') AS INTEGER))>=864000 THEN 2
                ELSE 1 END
            WHERE id=NEW.id;
          END""")
'''
BOARD='''
# BOB_COMPACT_AUTO_PRIORITY_V4
def make_board_embed(guild_id:int) -> discord.Embed:
    builds,research=qualifying_rows(guild_id)
    embed=discord.Embed(
        title="Bob the Builder — Helper Priority Board",
        description="🔴 Urgent · 🟠 High · 🟡 Normal · 🟢 Low  |  ✨ + Skill below",
        timestamp=datetime.now(timezone.utc),
    )
    # Respect both the per-field 1024-char and entire 6000-char Discord limits.
    remaining=5200
    overflow=[]
    for heading,rows,icon in (("Construction",builds,"🔨"),("Research",research,"🔬")):
        if not rows:
            embed.add_field(name=f"{icon} {heading} (0)",value="No qualifying timers.",inline=False)
            continue
        blocks=[]
        displayed=0
        for row in rows:
            # Each timer has only its own skill type; omit redundant project and end dates.
            priority_icon=PRIORITIES.get(int(row["priority"] or 2),PRIORITIES[2])[1]
            line=(f"{priority_icon} **#{row['id']} {row['player']}** · "
                  f"{entered_duration(row)} · {icon}{row['skills_used']}")
            if len(line)>950:
                line=line[:947]+"..."
            candidate="\\n".join(blocks+[line])
            if len(candidate)>940:
                if blocks and remaining>=len("\\n".join(blocks))+80 and len(embed.fields)<23:
                    body="\\n".join(blocks)
                    embed.add_field(name=f"{icon} {heading} ({displayed}/{len(rows)})",
                                    value=body,inline=False)
                    remaining-=len(body)+80
                    blocks=[]
                else:
                    break
            if remaining < len("\\n".join(blocks+[line]))+80 or len(embed.fields)>=23:
                break
            blocks.append(line)
            displayed+=1
        if blocks and len(embed.fields)<24:
            body="\\n".join(blocks)
            embed.add_field(name=f"{icon} {heading} ({displayed}/{len(rows)})",
                            value=body,inline=False)
            remaining-=len(body)+80
        if displayed<len(rows):
            overflow.append(f"{heading}: +{len(rows)-displayed}")
    if overflow and len(embed.fields)<25:
        embed.add_field(name="More timers",value=" · ".join(overflow)+" — use /timers for the full list.",inline=False)
    embed.set_footer(text=f"Refresh every {REFRESH_MINUTES} min · /timers for all active timers")
    return embed
'''

def find_func(source,name):
    tree=ast.parse(source)
    found=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    if len(found)!=1: raise ValueError(f"Expected exactly one {name} function; found {len(found)}")
    return found[0]

def replace_func(source,name,body):
    node=find_func(source,name)
    start=min((d.lineno for d in node.decorator_list),default=node.lineno)-1
    lines=source.splitlines(keepends=True)
    lines[start:node.end_lineno]=[body+"\n"]
    return "".join(lines)

def patch(path):
    src=path.read_text(encoding="utf-8")
    if MARKER in src:
        print("V4 already installed; no changes");return False
    if "# BOB_TIMER_VISIBILITY_V3" not in src:
        raise ValueError("V3 timer visibility must be installed before compact V4.")
    original=src
    anchor="\ndef human_remaining("
    if src.count(anchor)!=1: raise ValueError("Schema anchor missing.")
    src=src.replace(anchor,"\n"+SCHEMA+anchor,1)
    src=replace_func(src,"make_board_embed",BOARD)
    # Keep all existing persistent and ephemeral buttons; only update priority changes.
    old='db.execute("UPDATE timers SET priority=? WHERE id=?", (p, self.timer_id))'
    new='db.execute("UPDATE timers SET priority=?,priority_override=1 WHERE id=?", (p, self.timer_id))'
    if src.count(old)!=1: raise ValueError("Priority selector code mismatch.")
    src=src.replace(old,new,1)
    old2='db.execute("UPDATE timers SET priority=? WHERE id=?",(level.value,timer_id))'
    new2='db.execute("UPDATE timers SET priority=?,priority_override=1 WHERE id=?",(level.value,timer_id))'
    if src.count(old2)!=1: raise ValueError("Priority slash command code mismatch.")
    src=src.replace(old2,new2,1)
    # Do not alter HelperButtons, TimerActionsView, or /timers pages.
    ast.parse(src)
    compile(src,str(path),"exec")
    backup=path.with_name(path.name+".backup-compact-"+datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path,backup)
    path.write_text(src,encoding="utf-8")
    print("V4 compact layout and automatic priority installed. Backup:",backup)
    return True

if __name__=="__main__":
    if len(sys.argv)!=2: sys.exit("Usage: python3 patch_compact_auto_priority_v4.py /path/to/bot.py")
    try: patch(pathlib.Path(sys.argv[1]).resolve())
    except Exception as exc: sys.exit("NOT PATCHED: "+str(exc))
