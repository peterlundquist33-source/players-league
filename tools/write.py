"""Turn a normalized matchup into a Claude-written preview or recap."""
from lib import claude
from lore import LEAGUE_FACTS, NOTES, rivalry_between

_VOICE = """\
You are the beat writer for the Players League, a 12-team fantasy football league of
close friends now in its 5th season. You've covered every game since 2022. Your voice:
sharp, funny, a little mean in the way friends are mean to each other, confident with
the numbers, never corny. No hashtags, no emoji, no "folks", no fantasy-guru cliches
("buckle up", "must-start", "smash play", "league-winner")."""

SYSTEM_PREVIEW = _VOICE + """

This is a matchup PREVIEW. Weight it about 80/20:
- 80% the actual fantasy matchup — where the rosters win and lose it. Compare the
  lineups position by position. Call out the real edges (which RB room, which WR
  corps, the QB gap), the players who decide it, the boom/bust starters, thin spots
  and bad byes. Use the projected numbers. Reason about the NFL matchups the players
  are walking into from what you know about those teams and defenses.
- 20% the guys — a quick nod to the rivalry, a record, or one bit of team history,
  worked in naturally. Do not open with it and do not let it take over a paragraph.

Use owners' first names for the teams. Refer to NFL players by name.

Output format — EXACTLY this, nothing before or after:
HEADLINE: <4-9 words, about the matchup, punchy, no colon-subtitle format>

<body: exactly 2 short paragraphs, plain prose, no markdown, ~110-150 words total.
Separate the paragraphs with one blank line.>
"""

SYSTEM_RECAP = _VOICE + """

This is a matchup RECAP. Weight it about 75/25:
- 75% what actually happened on the field — the score, the swing, who carried the
  team, who cratered against projection, the bench points left behind, the position
  that decided it.
- 25% the guys — what the result means for them, a rivalry beat, a standings or
  history angle. Worked in, not stacked up front.

Use owners' first names. Refer to NFL players by name.

Output format — EXACTLY this, nothing before or after:
HEADLINE: <4-9 words, about the game, punchy, no colon-subtitle format>

<body: 2-3 short paragraphs, plain prose, no markdown, ~110-160 words total.
Separate paragraphs with one blank line.>
"""


def _parse(raw):
    raw = raw.strip()
    head, _, body = raw.partition("\n")
    head = head.strip()
    if head.upper().startswith("HEADLINE:"):
        head = head.split(":", 1)[1].strip()
    else:                       # model skipped the label — take first line as headline
        body = raw[len(head):]
    return {"headline": head.strip(' "'),
            "body": "\n".join(p.strip() for p in body.strip().split("\n") if p.strip())}


_GROUPS = ["QB", "RB", "WR", "TE", "FLEX", "K", "D/ST"]


def _lineup_block(side, key):
    """key = 'proj' or 'actual' — one team's starters, grouped, with a positional total."""
    rows, totals = [], {}
    for slot in _GROUPS:
        ss = [s for s in side["starters"] if s["slot"] == slot]
        for s in ss:
            rows.append(f'    {s["slot"]:<5} {s["name"]} ({s["pro"]}) {s[key]:.1f}')
        totals[slot] = round(sum(s[key] for s in ss), 1)
    return rows, totals


def _positional_edges(at, ht, label_a, label_h):
    out = []
    for slot in _GROUPS:
        av, hv = at.get(slot, 0.0), ht.get(slot, 0.0)
        if av == 0 and hv == 0:
            continue
        diff = round(av - hv, 1)
        who = label_a if diff > 0 else label_h
        tag = ""
        if abs(diff) >= 8:
            tag = "  <- decisive edge"
        elif abs(diff) >= 4:
            tag = "  <- real edge"
        out.append(f'  {slot:<5} {label_a} {av:.1f} vs {label_h} {hv:.1f}  '
                   f'({who} +{abs(diff):.1f}){tag}')
    return out


def _matchup_facts(m, phase):
    h, a = m["home"], m["away"]
    A, H = a["owner"], h["owner"]
    lines = [f'{A} ("{a["team"]}", {a["record"]}) at {H} ("{h["team"]}", {h["record"]}).']

    key = "proj" if phase == "preview" else "actual"
    a_rows, a_tot = _lineup_block(a, key)
    h_rows, h_tot = _lineup_block(h, key)

    if phase == "preview":
        lines.append(f'Projected total: {A} {a["projected"]:.1f}, {H} {h["projected"]:.1f} '
                     f'({A if a["projected"] >= h["projected"] else H} favored by '
                     f'{abs(a["projected"] - h["projected"]):.1f}).')
    else:
        lines.append(f'FINAL: {A} {a["actual"]:.1f}, {H} {h["actual"]:.1f} — '
                     f'{m["winner"]} by {m["margin"]:.1f}.')

    lines.append(f'\n{A} starters ({key} pts):')
    lines += a_rows
    lines.append(f'\n{H} starters ({key} pts):')
    lines += h_rows

    lines.append(f'\nPosition-by-position ({key}):')
    lines += _positional_edges(a_tot, h_tot, A, H)

    if phase == "recap":
        for who in (a, h):
            busts = sorted((s for s in who["starters"]
                            if s["proj"] - s["actual"] >= 6 and s["slot"] not in ("K", "D/ST")),
                           key=lambda s: s["actual"] - s["proj"])[:3]
            if busts:
                lines.append(f'{who["owner"]} underperformers: '
                             + ", ".join(f'{s["name"]} {s["actual"]:.1f} on {s["proj"]:.1f} proj'
                                         for s in busts))

    lines.append("\nOwner angle (use for ~20% of the piece, not more):")
    riv = rivalry_between(a["owner_full"], h["owner_full"])
    if riv:
        lines.append(f'  Rivalry: {riv}.')
    for who in (a, h):
        note = NOTES.get(who["owner"])
        if note:
            lines.append(f'  {who["owner"]}: {note}')
    return "\n".join(lines)


def write_matchup(m, week, phase):
    sysmsg = SYSTEM_PREVIEW if phase == "preview" else SYSTEM_RECAP
    kind = "preview" if phase == "preview" else "recap"
    user = (
        f"League background (for the ~20% owner angle only):\n{LEAGUE_FACTS}\n\n"
        f"Write the Week {week} {kind} for this matchup.\n\n"
        f"{_matchup_facts(m, phase)}\n"
    )
    out = _parse(claude(sysmsg, user, max_tokens=1000))
    if not out["headline"]:
        out["headline"] = f'{m["away"]["owner"]} at {m["home"]["owner"]}'
    return out


SYSTEM_GRADE = _VOICE + """

This is a DRAFT GRADE for one team. Weight it about 80/20:
- 80% the actual roster they built — the picks that got real value, the reaches, the
  positions they nailed or punted, roster construction (RB-heavy, zero-RB, waited on
  QB), the bye-week and depth situation. Refer to NFL players by name.
- 20% the owner — one line tying it to their history or the rivalry.
The grade is already assigned; explain it, don't re-argue it.

Output format — EXACTLY this, nothing before or after:
HEADLINE: <4-9 words about this draft, punchy, no colon-subtitle>

<body: 2 short paragraphs, plain prose, no markdown, ~100-140 words total,
one blank line between paragraphs.>
"""


def grade_team(t, season):
    picks = ", ".join(
        f'R{p["round"]} #{p["overall"]} {p["name"]} ({p["pos"]}, {p["value"]:+.0f} vs market)'
        for p in sorted(t["picks"], key=lambda p: p["overall"]) if p["counts"])
    pg = ", ".join(f'{k} {v["grade"]}' for k, v in t["pos_grades"].items()
                   if v["grade"] != "—")
    lines = [
        f'{t["owner"]} ("{t["team"]}") — draft grade {t["grade"]}, '
        f'{t["rank"]} of {12} in the league.',
        f'Positional grades: {pg}.',
        f'All skill picks (value vs consensus/ADP): {picks}.',
    ]
    if t["best"]:
        b = t["best"]
        lines.append(f'Best value: {b["name"]} at #{b["overall"]} (round {b["round"]}), '
                     f'{b["value"]:+.0f} vs where he normally goes.')
    if t["reach"]:
        r = t["reach"]
        lines.append(f'Biggest reach: {r["name"]} at #{r["overall"]} (round {r["round"]}), '
                     f'{r["value"]:+.0f}.')
    note = NOTES.get(t["owner"])
    if note:
        lines.append(f'Owner angle (~20%): {t["owner"]}: {note}')
    user = (f"League background:\n{LEAGUE_FACTS}\n\n"
            f"Write the {season} draft grade for this team.\n\n" + "\n".join(lines) + "\n")
    out = _parse(claude(SYSTEM_GRADE, user, max_tokens=900))
    if not out["headline"]:
        out["headline"] = f'{t["owner"]}: {t["grade"]}'
    return out


def grade_intro(g):
    board = "\n".join(f'{t["rank"]}. {t["grade"]}  {t["owner"]} ("{t["team"]}")' for t in g["teams"])
    sysmsg = _VOICE + (
        "\n\nWrite a 3-4 sentence intro for the draft-grades page: who nailed it, who "
        "whiffed, the theme of the draft. Mostly about the rosters. Plain prose, no "
        "headline, no markdown.")
    user = (f"{LEAGUE_FACTS}\n\n{g['season']} draft grades, best to worst:\n{board}\n")
    return claude(sysmsg, user, max_tokens=320).strip()


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
    sys = _VOICE + (
        "\n\nWrite a 2-3 sentence intro for the week's matchup page: the state of the "
        "league and the game that matters most, mostly in fantasy terms (who's loaded, "
        "who's limping in), with at most one owner/rivalry beat. Plain prose, no headline, "
        "no label, no markdown.")
    return claude(sys, user, max_tokens=300).strip()
