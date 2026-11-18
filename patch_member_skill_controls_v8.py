#!/usr/bin/env python3
"""Bob v8: allow members to add and remove recorded timer skills.

Apply to the extracted v7 bot source (not to a ZIP archive).
The existing adjust_timer_skill function handles 15% timer reduction
and restoration; this patch intentionally leaves it unchanged.
"""
import ast
import pathlib
import shutil
import sys
from datetime import datetime, timezone

MARKER = "# BOB_MEMBER_SKILL_CONTROLS_V8"
MINUS_BUTTON = '''
    @discord.ui.button(label="- Skill", style=discord.ButtonStyle.secondary)
    async def skill_minus(self, interaction:discord.Interaction, button:discord.ui.Button):
        try:
            player,kind,total=adjust_timer_skill(
                interaction.guild_id,self.timer_id,-1,interaction.user.id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc),ephemeral=True)
            return
        await interaction.response.edit_message(
            content=f"Removed 1 {kind} skill from **#{self.timer_id} {player}**. Used: **{total}**.",
            view=None)
        await refresh_board(interaction.guild_id)
'''

def patch(path):
    original=path.read_text(encoding="utf-8")
    if MARKER in original:
        print("Member skill controls already installed."); return False
    tree=ast.parse(original)
    commands=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="skillremove"]
    if len(commands)!=1:
        raise ValueError("Expected one /skillremove slash command.")
    remove=commands[0]
    if not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
               and n.func.id=="adjust_timer_skill" for n in ast.walk(remove)):
        raise ValueError("Skill removal is not backed by the timer skill adjustment function.")
    if not any(isinstance(n,ast.Name) and n.id=="can_manage" for n in ast.walk(remove)):
        raise ValueError("Unexpected /skillremove permission layout; no changes made.")

    # Remove only the current admin gate, retaining all validation and rollback logic.
    gates=[n for n in remove.body if isinstance(n,ast.If)
           and isinstance(n.test,ast.UnaryOp)
           and isinstance(n.test.op,ast.Not)
           and isinstance(n.test.operand,ast.Call)
           and isinstance(n.test.operand.func,ast.Name)
           and n.test.operand.func.id=="can_manage"]
    if len(gates)!=1:
        raise ValueError("Cannot safely identify admin-only gate.")
    gate=gates[0]
    if any(not isinstance(n,(ast.Expr,ast.Return)) for n in gate.body):
        raise ValueError("Unexpected gate block.")
    lines=original.splitlines(keepends=True)
    # Add a - Skill button beside the existing + Skill in the timer management view.
    classes=[c for c in tree.body if isinstance(c,ast.ClassDef)
             and any(isinstance(f,ast.AsyncFunctionDef) and f.name=="skill_plus"
                     for f in c.body)]
    if len(classes)!=1: raise ValueError("Expected one timer management view with a + Skill button.")
    cls=classes[0]
    if any(isinstance(f,(ast.FunctionDef,ast.AsyncFunctionDef)) and f.name=="skill_minus" for f in cls.body):
        raise ValueError("A - Skill button is already present; inspect before applying.")
    insert_line=next(f.end_lineno for f in cls.body if isinstance(f,ast.AsyncFunctionDef) and f.name=="skill_plus")
    lines.insert(insert_line,"\n"+MINUS_BUTTON+"\n")
    # Re-parse so original line positions are not invalidated by insertion.
    interim="".join(lines)
    tree2=ast.parse(interim)
    cmd=next(n for n in tree2.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="skillremove")
    gate2=next(n for n in cmd.body if isinstance(n,ast.If)
               and isinstance(n.test,ast.UnaryOp) and isinstance(n.test.operand,ast.Call)
               and isinstance(n.test.operand.func,ast.Name) and n.test.operand.func.id=="can_manage")
    lines=interim.splitlines(keepends=True)
    del lines[gate2.lineno-1:gate2.end_lineno]
    result=MARKER+"\n"+"".join(lines)
    ast.parse(result)
    compile(result,str(path),"exec")
    backup=path.with_name(path.name+".backup-member-skills-"+datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path,backup)
    path.write_text(result,encoding="utf-8")
    print("Updated skill controls. Backup:",backup)
    return True

if __name__=="__main__":
    if len(sys.argv)!=2:
        sys.exit("Usage: python3 patch_member_skill_controls_v8.py /path/to/bot.py")
    try: patch(pathlib.Path(sys.argv[1]).resolve())
    except Exception as exc: sys.exit("NOT PATCHED: "+str(exc))
