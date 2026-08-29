"""Turn a normalized matchup into a Claude-written preview or recap."""
import json
from lib import claude
from lore import LEAGUE_FACTS, NOTES, rivalry_between

SYSTEM = """\
You are the beat writer for the Players League, a 12-team fantasy football league of
close friends now in its 5th season. You've covered every game since 2022. Your voice:
sharp, funny, a little mean in the way friends are mean to each other, confident with
the numbers, never corny. No hashtags, no emoji, no "folks", no fantasy-guru cliches
("buckle up", "must-start", "smash play"). Reference league history and rivalries when
they fit — don't force them. Use owners' first names.

Return ONLY valid JSON: {"headline": "...", "body": "..."}
- headline: 4-9 words, punchy, specific to this matchup. No colon-subtitle format.
- body: 2 short paragraphs (preview) or 2-3 short paragraphs (recap), plain text,
  no markdown. ~90-150 words.
"""


def _matchup_facts(m, phase):
    h, a = m["home"], m["away"]
    lines = [
        f'{a["owner"]} ("{a["team"]}", {a["record"]}) at {h["owner"]} ("{h["team"]}", {h["record"]}).',
    ]
    riv = rivalry_between(a["owner_full"], h["owner_full"])
    if riv:
        lines.append(f"Rivalry: {riv}.")
    for who in (a, h):
        note = NOTES.get(who["owner"])
        if note:
            lines.append(f'{who["owner"]}: {note}')
    if phase == "preview":
        lines.append(f'Projected: {a["owner"]} {a["projected"]}, {h["owner"]} {h["projected"]}.')
        for who in (a, h):
            tops = sorted(who["starters"], key=lambda s: -s["proj"])[:3]
            lines.append(f'{who["owner"]} leans on: '
                         + ", ".join(f'{s["name"]} ({s["proj"]})' for s in tops))
    else:
        lines.append(f'Final: {m["winner"]} won by {m["margin"]}.')
        lines.append(f'{a["owner"]} {a["actual"]}, {h["owner"]} {h["actual"]}.')
        for who in (a, h):
            tops = sorted(who["starters"], key=lambda s: -s["actual"])[:3]
            busts = [s for s in who["starters"]
                     if s["proj"] - s["actual"] >= 6 and s["slot"] != "K"][:2]
            lines.append(f'{who["owner"]} best: '
                         + ", ".join(f'{s["name"]} {s["actual"]}' for s in tops))
            if busts:
                lines.append(f'{who["owner"]} let down by: '
                             + ", ".join(f'{s["name"]} ({s["actual"]} on {s["proj"]} proj)'
                                         for s in busts))
    return "\n".join(lines)


def write_matchup(m, week, phase):
    kind = "preview" if phase == "preview" else "recap"
    user = (
        f"{LEAGUE_FACTS}\n\n"
        f"Write a Week {week} {kind} for this matchup.\n\n"
        f"{_matchup_facts(m, phase)}\n"
    )
    raw = claude(SYSTEM, user, max_tokens=700, temperature=0.85)
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        obj = json.loads(raw[start:end])
        return {"headline": obj["headline"].strip(), "body": obj["body"].strip()}
    except Exception:
        return {"headline": f'{m["away"]["owner"]} at {m["home"]["owner"]}',
                "body": raw}


def write_intro(league, week, phase):
    kind = "preview" if phase == "preview" else "recap"
    board = "\n".join(
        f'{m["away"]["owner"]} at {m["home"]["owner"]}'
        + (f' — proj {m["away"]["projected"]}-{m["home"]["projected"]}' if phase == "preview"
           else f' — {m["away"]["actual"]}-{m["home"]["actual"]}, {m["winner"]} won')
        for m in league["matchups"]
    )
    user = (
        f"{LEAGUE_FACTS}\n\n"
        f"Write a 2-3 sentence intro for the Week {week} {kind} page — the state of the "
        f"league, the game that matters most, the storyline to watch. Plain text only.\n\n"
        f"This week:\n{board}\n"
    )
    return claude(SYSTEM.replace('Return ONLY valid JSON: {"headline": "...", "body": "..."}',
                                 "Return plain text, no JSON, no headline."),
                  user, max_tokens=300, temperature=0.8)
