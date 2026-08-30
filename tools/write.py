"""Turn a normalized matchup into a Claude-written preview or recap."""
from lib import claude
from lore import LEAGUE_FACTS, NOTES, RIVALRIES, rivalry_between

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

This is a DRAFT GRADE for one team. Write it like a scout's evaluation, not a roast.
Dial the sarcasm WAY back from your default — one dry aside for the whole piece is
plenty. Same balance as a good matchup preview.

Weight it about 80/20:
- 80% the actual NFL players and the roster: who anchors each position, what the
  specific players bring, how the starting lineup shapes up, where it's deep and
  where it's one injury from trouble, the roster-construction plan (RB-early,
  zero-RB, waited on QB), the value picks and the reaches. Name players. Be concrete.
- 20% the owner: one line tying it to their history or rivalry. One line of shit talk
  is fine.

ACCURACY — this matters, people in the league will read it:
- Every factual claim about an NFL player must be either (a) present in the DATA
  block below, or (b) genuinely common knowledge about that player. Do NOT invent a
  team's offensive scheme, a player's exact snap/target share, injury timelines,
  rookie/veteran status, or depth-chart position. If you're not sure of a player's
  role, describe him by his draft cost / consensus rank / position rank instead.
- The data labels each pick VALUE (+) or REACH (−). A VALUE pick is a GOOD pick (got
  him cheaper than consensus); a REACH was taken too early. Never call a VALUE pick a
  reach or vice versa. Use the given numbers, don't invent slot counts.
- You only see ONE team. BANNED phrases (you cannot verify them): "best/worst pick
  anyone made", "best value in/of the draft", "the single best/worst", "best bargain
  all weekend", "the class of the draft", "biggest reach of the draft". For a pick on
  THIS team say "his best value", "his worst pick", "the steal of his draft" instead.
  The ONLY league-wide claim allowed: the DATA block names the real league-wide
  biggest reach and best value — you may state that verbatim ONLY if that exact player
  is on this team.
- Bye weeks are in the data. Only cite a bye-week stack if the numbers actually show one.
- The head-to-head record line in the data is already written from THIS owner's point
  of view — state it exactly as given, do not flip it.
- Don't editorialize a player's decline, "lost step", target share, or scheme fit
  unless it's flatly common knowledge. Prefer the draft-cost / rank framing.

Tone tracks the grade: an A/A+ leads with what the roster does well, flaw as a
footnote; a D/F is direct about the problems but stays specific.

Output format — EXACTLY this, nothing before or after:
HEADLINE: <4-9 words about the roster or the draft plan, not a punchline>

<body: 2 short paragraphs, plain prose, no markdown, ~120-160 words total,
one blank line between paragraphs.>
"""


def _pick_line(p):
    tag = f'VALUE +{p["value"]:.0f}' if p["value"] > 0 else \
          (f'REACH {p["value"]:.0f}' if p["value"] < 0 else 'about market')
    pr = f', {p["pos_rank"]}' if p.get("pos_rank") else ''
    bye = f', bye {p["bye"]}' if p.get("bye") else ''
    return (f'  R{p["round"]:<2} #{p["overall"]:<3} {p["name"]} — {p["pos"]}{pr}, '
            f'{p.get("pro","?")}{bye} · {tag}')


def _owner_rivalry(owner_name):
    for lead, trail, rec, flav in RIVALRIES:
        if owner_name not in (lead, trail):
            continue
        w, l = rec.split("-")
        other = trail if owner_name == lead else lead
        if w == l:
            s = f"{owner_name} and {other} are dead even {w}-{l} all-time head-to-head"
        elif owner_name == lead:
            s = f"{owner_name} leads the all-time head-to-head with {other} {w}-{l}"
        else:
            s = f"{owner_name} trails the all-time head-to-head with {other} {l}-{w}"
        return s + (f" ({flav})" if flav else "")
    return None


def grade_team(t, season, extremes=None):
    skill = [p for p in sorted(t["picks"], key=lambda p: p["overall"]) if p["counts"]]
    kdst = [p for p in sorted(t["picks"], key=lambda p: p["overall"]) if not p["counts"]]
    pg = ", ".join(f'{k} {v["grade"]}' for k, v in t["pos_grades"].items()
                   if v["grade"] != "—")
    lines = [
        f'TEAM: {t["owner"]} ("{t["team"]}")',
        f'GRADE: {t["grade"]} — {t["rank"]} of 12 overall.',
        f'The grade = 65% roster quality + 35% draft-value efficiency. '
        f'Roster-strength score {t["strength"]} (higher is better). '
        f'Draft-efficiency score {t["efficiency"]:+.0f} (negative = paid at/above market to get it).',
        f'Positional grades (strength of each room vs the rest of the league): {pg}.',
        '',
        'SKILL-POSITION PICKS (round, overall pick, player — position, NFL team, bye · value tag):',
    ]
    lines += [_pick_line(p) for p in skill]
    if kdst:
        lines.append('K / D-ST (not graded): '
                     + ", ".join(f'{p["name"]} R{p["round"]}' for p in kdst))
    if t.get("best"):
        b = t["best"]
        lines.append(f'\nHis best value of the draft: {b["name"]} (round {b["round"]}, #{b["overall"]}, +{b["value"]:.0f}).')
    if t.get("reach"):
        r = t["reach"]
        lines.append(f'His worst pick: {r["name"]} (round {r["round"]}, #{r["overall"]}, {r["value"]:.0f}).')
    if extremes:
        br, bv = extremes["biggest_reach"], extremes["best_value"]
        owns_reach = f'({t["owner"]},' in br
        owns_value = f'({t["owner"]},' in bv
        lines.append('')
        if owns_reach:
            lines.append(f'NOTE: {br.split(" (")[0]} on this team IS the biggest reach of the '
                         f'entire draft — you may say so.')
        if owns_value:
            lines.append(f'NOTE: {bv.split(" (")[0]} on this team IS the best value of the '
                         f'entire draft — you may say so.')
        if not owns_reach and not owns_value:
            lines.append('NOTE: this team does NOT have the draft\'s biggest reach or best '
                         'value. Do NOT call any of their picks the best/worst "in the draft", '
                         '"in the league", "of the weekend", or "anyone made" — say "his '
                         'best/worst" only. (For reference, elsewhere in the league the biggest '
                         f'reach was {br} and the best value was {bv}.)')
    riv = _owner_rivalry(t["owner"])
    note = NOTES.get(t["owner"])
    lines.append('\nOWNER (use one line, ~20% of the piece):')
    if note:
        lines.append(f'  {note}')
    if riv:
        lines.append(f'  {riv}')
    user = (f"League background:\n{LEAGUE_FACTS}\n\n"
            f"Write the {season} draft grade for this team.\n\nDATA:\n" + "\n".join(lines) + "\n")

    import re
    _BANNED = re.compile(
        r"(best|worst|biggest|ugliest|lowest|highest)[^.]{0,40}"
        r"(in the (draft|league)|of the (draft|league|weekend|year)|all (weekend|draft|year)|"
        r"anyone (made|found|got)|whole draft|entire (draft|league))", re.I)
    allow = ((extremes and f'({t["owner"]},' in extremes.get("biggest_reach", "")) or
             (extremes and f'({t["owner"]},' in extremes.get("best_value", "")))
    for attempt in range(3):
        out = _parse(claude(SYSTEM_GRADE, user, max_tokens=1100))
        if allow or not _BANNED.search(out["body"]):
            break
        user += ("\n\nREWRITE: your last draft used a banned league-wide superlative "
                 "('best/worst ... in the draft/league/weekend'). This team has no "
                 "draft-wide extreme. Say 'his best/worst pick' instead. Try again.")
    if not out["headline"]:
        out["headline"] = f'{t["owner"]}: {t["grade"]}'
    return out


def grade_intro(g):
    board = "\n".join(f'{t["rank"]}. {t["grade"]}  {t["owner"]} ("{t["team"]}")' for t in g["teams"])
    sysmsg = _VOICE + (
        "\n\nWrite a 3-4 sentence intro for the draft-grades page: the shape of the "
        "draft, which rosters came out loaded and which came out thin, one position "
        "run worth noting. Mostly about the rosters and players, light on the snark "
        "(one line of it, tops). Plain prose, no headline, no markdown.")
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
