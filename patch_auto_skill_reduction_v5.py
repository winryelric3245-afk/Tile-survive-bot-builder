#!/usr/bin/env python3
"""V5: + Skill automatically reduces only the chosen timer's remaining time by 15% per skill."""
import ast
import pathlib
import shutil
import sys
from datetime import datetime, timezone

MARKER="# BOB_AUTO_SKILL_REDUCTION_V5"
SCHEMA='''
        # BOB_AUTO_SKILL_REDUCTION_V5: retain auditable automatic time adjustments.
        db.execute("""CREATE TABLE IF NOT EXISTS timer_skill_effects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            timer_id INTEGER NOT NULL,
            count INTEGER NOT NULL,
            before_seconds INTEGER NOT NULL,
            after_seconds INTEGER NOT NULL,
            actor_id INTEGER NOT NULL,
            created_ts INTEGER NOT NULL,
            undone_count INTEGER NOT NULL DEFAULT 0
        )""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS cleanup_timer_skill_effects
          AFTER DELETE ON timers BEGIN
            DELETE FROM timer_skill_effects WHERE timer_id=OLD.id;
          END""")
'''
FEATURE='''
# BOB_AUTO_SKILL_REDUCTION_V5
def adjust_timer_skill(guild_id,timer_id,delta,actor_id):
    """Add applies 0.85 per skill; remove reverses only V5-tracked skills.
    For older V2 counters, removing the count does not change time because
    no V5 reduction was applied to those older records.
    """
    import math
    if not isinstance(delta,int) or delta==0 or abs(delta)>100:
        raise ValueError("Skill amount must be between 1 and 100.")
    now=int(datetime.now(timezone.utc).timestamp())
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT * FROM timers WHERE guild_id=? AND id=?",
                       (guild_id,timer_id)).fetchone()
        if not row or row["completed"] or row["end_ts"]<=now:
            raise ValueError("This timer is missing, expired, or finished.")
        previous=int(row["skills_used"])
        total=previous+delta
        if total<0:
            raise ValueError(f"Timer #{timer_id} only has {previous} skills recorded.")
        remaining=max(1,int(row["end_ts"])-now)
        revised=remaining
        if delta>0:
            # Each 15% skill works on the time remaining after earlier skills.
            for _ in range(delta):
                revised=max(1,math.ceil(revised*0.85))
            db.execute("""INSERT INTO timer_skill_effects
              (guild_id,timer_id,count,before_seconds,after_seconds,actor_id,created_ts)
              VALUES(?,?,?,?,?,?,?)""",
              (guild_id,timer_id,delta,remaining,revised,actor_id,now))
        else:
            # Undo latest V5 tracked reductions, without altering time for
            # imported/older skill counts that had no recorded time reduction.
            undo=-delta
            effects=db.execute("""SELECT * FROM timer_skill_effects
                 WHERE guild_id=? AND timer_id=? AND undone_count<count
                 ORDER BY id DESC""",(guild_id,timer_id)).fetchall()
            for effect in effects:
                if not undo:
                    break
                available=effect["count"]-effect["undone_count"]
                count=min(undo,available)
                for _ in range(count):
                    revised=math.ceil(revised/0.85)
                db.execute("UPDATE timer_skill_effects SET undone_count=undone_count+? WHERE id=?",
                           (count,effect["id"]))
                undo-=count
        if revised!=remaining:
            # Existing V3 duration and V4 auto-priority triggers update
            # automatically, while manual priority overrides remain intact.
            db.execute("UPDATE timers SET end_ts=? WHERE guild_id=? AND id=?",
                       (now+revised,guild_id,timer_id))
        db.execute("UPDATE timers SET skills_used=? WHERE guild_id=? AND id=?",
                   (total,guild_id,timer_id))
        db.execute("""INSERT INTO timer_skill_history
            (guild_id,timer_id,delta,actor_id,created_ts) VALUES(?,?,?,?,?)""",
            (guild_id,timer_id,delta,actor_id,now))
    return row["player"],row["timer_type"],total

'''

def replace_func(source,name,code):
    tree=ast.parse(source)
    matches=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    if len(matches)!=1:
        raise ValueError(f"Expected one {name} function, found {len(matches)}.")
    node=matches[0]
    lines=source.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno]=[code+"\n"]
    return "".join(lines)

def patch(path):
    original=path.read_text(encoding="utf-8")
    if MARKER in original:
        print("V5 already installed");return False
    if "# BOB_COMPACT_AUTO_PRIORITY_V4" not in original:
        raise ValueError("Install compact V4 first; V5 did not change the bot.")
    if original.count("\ndef human_remaining(")!=1:
        raise ValueError("Database schema anchor missing.")
    updated=original.replace("\ndef human_remaining(", "\n"+SCHEMA+"\ndef human_remaining(",1)
    updated=replace_func(updated,"adjust_timer_skill",FEATURE)
    ast.parse(updated)
    compile(updated,str(path),"exec")
    backup=path.with_name(path.name+".backup-skill-time-"+datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path,backup)
    path.write_text(updated,encoding="utf-8")
    print("V5 skill timer reduction installed; backup:",backup)
    return True

if __name__=="__main__":
    if len(sys.argv)!=2:
        sys.exit("Usage: python3 patch_auto_skill_reduction_v5.py /path/to/bot.py")
    try:
        patch(pathlib.Path(sys.argv[1]).resolve())
    except Exception as exc:
        sys.exit("NOT PATCHED: "+str(exc))
