#!/usr/bin/env python3
"""V3: list every active timer in pages and show the entered duration, never relative end dates."""
import ast, pathlib, shutil, sys
from datetime import datetime, timezone

MARKER = "# BOB_TIMER_VISIBILITY_V3"
SCHEMA = '''
        # BOB_TIMER_VISIBILITY_V3: preserve the submitted/edited duration.
        cols = {r["name"] for r in db.execute("PRAGMA table_info(timers)").fetchall()}
        if "duration_seconds" not in cols:
            db.execute("ALTER TABLE timers ADD COLUMN duration_seconds INTEGER")
            db.execute("""UPDATE timers SET duration_seconds=
                MAX(0,end_ts-CAST(strftime('%s','now') AS INTEGER))
                WHERE duration_seconds IS NULL""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS bob_duration_on_insert
            AFTER INSERT ON timers BEGIN
              UPDATE timers SET duration_seconds=MAX(0,NEW.end_ts-NEW.created_ts)
              WHERE id=NEW.id;
            END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS bob_duration_on_edit
            AFTER UPDATE OF end_ts ON timers BEGIN
              UPDATE timers SET duration_seconds=
                MAX(0,NEW.end_ts-CAST(strftime('%s','now') AS INTEGER))
              WHERE id=NEW.id;
            END""")
'''
FEATURE = '''
# BOB_TIMER_VISIBILITY_V3
def entered_duration(row):
    seconds=max(0,int(row["duration_seconds"] or 0))
    days,rest=divmod(seconds,86400)
    hours,rest=divmod(rest,3600)
    minutes=rest//60
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{minutes}m"

def timer_page(guild_id,page=1,per_page=10):
    with connect() as db:
        records=db.execute("""SELECT * FROM timers
          WHERE guild_id=? AND completed=0 AND end_ts>strftime('%s','now')
          ORDER BY CASE timer_type WHEN 'build' THEN 0 ELSE 1 END,
                   priority DESC, end_ts DESC, id""",
          (guild_id,)).fetchall()
    pages=max(1,(len(records)+per_page-1)//per_page)
    page=min(max(1,page),pages)
    rows=records[(page-1)*per_page:page*per_page]
    lines=[f"**All Active Timers — {page}/{pages}** ({len(records)} total)"]
    for row in rows:
        kind="🔨 Build" if row["timer_type"]=="build" else "🔬 Research"
        lines.append(f"{kind} · **#{row['id']} {row['player']}** · "
                     f"{priority_text(row['priority'])}\\n"
                     f"{row['project']} · {entered_duration(row)} · "
                     f"{timer_skill_label(row)}")
    content="\\n\\n".join(lines)
    return content[:1950],page,pages

class TimerPagesView(discord.ui.View):
    def __init__(self,guild_id,page,total):
        super().__init__(timeout=180)
        self.guild_id=guild_id
        self.page=page
        self.previous.disabled=page==1
        self.next.disabled=page==total

    async def change(self,interaction,page):
        if interaction.guild_id!=self.guild_id:
            await interaction.response.send_message("Different server.",ephemeral=True)
            return
        text,page,total=timer_page(self.guild_id,page)
        await interaction.response.edit_message(
            content=text,view=TimerPagesView(self.guild_id,page,total))

    @discord.ui.button(label="Previous",style=discord.ButtonStyle.secondary)
    async def previous(self,interaction,button):
        await self.change(interaction,self.page-1)

    @discord.ui.button(label="Next",style=discord.ButtonStyle.primary)
    async def next(self,interaction,button):
        await self.change(interaction,self.page+1)

def make_board_embed(guild_id:int) -> discord.Embed:
    builds,research=qualifying_rows(guild_id)
    embed=discord.Embed(
        title="Bob the Builder — Helper Priority Board",
        description=(f"Season Skill targets: **builds over {BUILD_THRESHOLD_DAYS:g} days** "
                     f"and **research over {RESEARCH_THRESHOLD_DAYS:g} days**.\\n"
                     "Priority overrides timer length, then longest timers appear first."),
        timestamp=datetime.now(timezone.utc))
    total_chars=len(embed.title)+len(embed.description)+120
    for heading,rows in (("Construction Priority",builds),("Research Priority",research)):
        if not rows:
            embed.add_field(name=heading,value="No qualifying timers.",inline=False)
            continue
        current=[]
        field_number=1
        displayed=0
        for row in rows:
            line=(f"{priority_text(row['priority'])} **#{row['id']} · {row['player']}** "
                  f"— {entered_duration(row)}\\n"
                  f"{row['project']} · {timer_skill_label(row)}")
            if len(line)>900:
                line=line[:897]+"..."
            joined="\\n\\n".join(current+[line])
            if len(joined)>940:
                field="\\n\\n".join(current)
                if total_chars+len(field)>5350 or len(embed.fields)>=23:
                    break
                embed.add_field(name=(heading if field_number==1 else f"{heading} ({field_number})"),
                                value=field,inline=False)
                total_chars+=len(field)+len(heading)+24
                field_number+=1
                current=[]
            if total_chars+len("\\n\\n".join(current+[line]))>5350 or len(embed.fields)>=23:
                break
            current.append(line)
            displayed+=1
        if current and len(embed.fields)<24:
            field="\\n\\n".join(current)
            embed.add_field(name=heading if field_number==1 else f"{heading} ({field_number})",
                            value=field,inline=False)
            total_chars+=len(field)+len(heading)+24
        if displayed<len(rows) and len(embed.fields)<25:
            embed.add_field(name=f"More {heading}",
                value=f"{len(rows)-displayed} additional timers — use /timers to browse every active timer.",
                inline=False)
    embed.set_footer(text=f"Auto-refresh: {REFRESH_MINUTES} min · /timers shows the complete active list")
    return embed

'''
CMD = '''
@app_commands.guild_only()
@bot.tree.command(name="timers",description="Browse all active timers, including below-threshold timers")
async def timers(interaction:discord.Interaction):
    content,page,pages=timer_page(interaction.guild_id)
    await interaction.response.send_message(
        content,view=TimerPagesView(interaction.guild_id,page,pages),ephemeral=True)
'''

def replace_function(src,name,replacement):
    tree=ast.parse(src)
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    if len(nodes)!=1: raise ValueError(f"Unexpected {name} function count: {len(nodes)}")
    n=nodes[0]
    start=min((d.lineno for d in n.decorator_list),default=n.lineno)-1
    lines=src.splitlines(keepends=True)
    lines[start:n.end_lineno]=[replacement+"\n"]
    return "".join(lines)

def patch(path):
    src=path.read_text(encoding="utf-8")
    if MARKER in src:
        print("V3 already installed.");return False
    if "# BOB_SKILL_TRACKER_V2" not in src:
        raise ValueError("First install V2 skill tracker; V3 does not change unsupported code.")
    anchor="\ndef human_remaining("
    if src.count(anchor)!=1: raise ValueError("Missing DB placement anchor.")
    src=src.replace(anchor,"\n"+SCHEMA+anchor,1)
    src=replace_function(src,"make_board_embed","")
    src=replace_function(src,"timers","")
    point="\nclass TimerModal(discord.ui.Modal):"
    if src.count(point)!=1: raise ValueError("Missing modal anchor.")
    src=src.replace(point,"\n"+FEATURE+point,1)
    # New /timers command must appear after the bot instance exists.
    tree=ast.parse(src)
    node=next((n for n in tree.body if isinstance(n,ast.Assign)
         and any(isinstance(t,ast.Name) and t.id=="bot" for t in n.targets)),None)
    if node is None: raise ValueError("Missing bot variable.")
    lines=src.splitlines(keepends=True)
    lines.insert(node.end_lineno,"\n"+CMD+"\n")
    src="".join(lines)
    ast.parse(src)
    compile(src,str(path),"exec")
    backup=path.with_name(path.name+".backup-visibility-"+datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path,backup)
    path.write_text(src,encoding="utf-8")
    print("V3 installed. Original saved to",backup)
    return True

if __name__=="__main__":
    if len(sys.argv)!=2: sys.exit("Usage: python3 patch_timer_visibility_v3.py /path/to/bot.py")
    try: patch(pathlib.Path(sys.argv[1]).resolve())
    except Exception as exc: sys.exit("NOT PATCHED: "+str(exc))
