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

This is a matchup PREVIEW. It is almost entirely about THIS WEEK'S game:
- ~90% the matchup itself — which roster is deeper or more top-heavy at each position,
  the players who decide it, the boom/bust guys, the bye-week and injury holes, the
  positional edges. Reason about the NFL games these players are walking into from what
  you know. Lineups may not be locked yet, so talk about each team's ROSTER at a
  position (their best options, their depth), not just whoever's currently slotted.
- ~10% the guys — AT MOST one short clause about the owners, and only if it's actually
  relevant to this game (a live rivalry, a standings stake). No league-history
  storytelling, no "since 2022", no dredging up old seasons. If nothing's relevant,
  skip it entirely.

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


_POS_ORD = ["QB", "RB", "WR", "TE", "K", "D/ST"]


def _roster_block(side):
    """Full roster grouped by position, projections desc — for previews (lineups
    may not be set)."""
    by_pos = {}
    for p in side.get("players", []):
        by_pos.setdefault(p["pos"], []).append(p)
    rows = []
    for pos in _POS_ORD:
        ps = sorted(by_pos.get(pos, []), key=lambda x: -x["proj"])
        if not ps:
            continue
        rows.append(f'  {pos}: ' + ", ".join(
            f'{p["name"]} ({p["pro"]}, {p["proj"]:.0f})' for p in ps))
    return rows


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

    if phase == "preview":
        ao, ho = a.get("optimal_proj", a["projected"]), h.get("optimal_proj", h["projected"])
        lines.append(f'Best-lineup projection (from the full roster, since lineups may not '
                     f'be locked): {A} ~{ao:.0f}, {H} ~{ho:.0f} '
                     f'({A if ao >= ho else H} projects ahead by ~{abs(ao - ho):.0f}).')
        lines.append(f'\n{A} — full roster by position (proj pts, best first):')
        lines += _roster_block(a)
        lines.append(f'\n{H} — full roster by position (proj pts, best first):')
        lines += _roster_block(h)
        # positional comparison off the whole roster's top options
        def top(side, pos, n):
            ps = sorted((p for p in side["players"] if p["pos"] == pos),
                        key=lambda x: -x["proj"])[:n]
            return round(sum(p["proj"] for p in ps), 1)
        lines.append('\nTop-options-per-position (A vs H):')
        for pos, n in (("QB", 1), ("RB", 2), ("WR", 3), ("TE", 1)):
            av, hv = top(a, pos, n), top(h, pos, n)
            edge = A if av > hv else H
            lines.append(f'  {pos} (best {n}): {A} {av:.0f} vs {H} {hv:.0f} — {edge} +{abs(av-hv):.0f}')
        riv = rivalry_between(a["owner_full"], h["owner_full"])
        lines.append('\nOwner note (at most ONE short clause, only if it fits — otherwise ignore):')
        lines.append(f'  {riv}.' if riv else '  (no live rivalry between these two — skip owner talk)')
        return "\n".join(lines)

    # ---- recap: lineups are locked, use starters + actuals ----
    a_rows, a_tot = _lineup_block(a, "actual")
    h_rows, h_tot = _lineup_block(h, "actual")
    lines.append(f'FINAL: {A} {a["actual"]:.1f}, {H} {h["actual"]:.1f} — '
                 f'{m["winner"]} by {m["margin"]:.1f}.')
    lines.append(f'\n{A} starters (actual pts):')
    lines += a_rows
    lines.append(f'\n{H} starters (actual pts):')
    lines += h_rows
    lines.append('\nPosition-by-position (actual):')
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

The grade is ABSOLUTE (a real 0-100 score, not a curve): it reflects how good the
roster actually is against fixed positional benchmarks. A 90+ is a genuinely loaded
team; a mid-70s means startable but unspectacular with real holes. Tone tracks the
number — an A leads with what the roster does well and treats a flaw as a footnote;
a C is even-handed about the strengths and the gaps.

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
        f'GRADE: {t["grade"]} ({t["score"]}/100) — {t["rank"]} of 12.',
        f'This is an ABSOLUTE grade, not curved: roster quality judged against fixed '
        f'positional benchmarks ({t["roster_score"]:.0f}/100), plus a small draft-value '
        f'adjustment ({t["value_adj"]:+.1f}: {"drafted efficiently" if t["value_adj"] >= 0 else "reached more than the league norm"}).',
        f'Positional grades (each room vs a solid-starter benchmark, also absolute): {pg}.',
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
    stakes = ""
    if phase == "preview" and league["week"] > 1:
        board2 = "\n".join(f'{s["owner"]}: {s["record"]}' for s in league["standings"])
        stakes = f"\nCurrent standings:\n{board2}\n"
    user = (
        f"Week {week} {kind}. The games:\n{board}\n{stakes}\n"
        f"Write the 2-3 sentence intro for this page."
    )
    sys = _VOICE + (
        "\n\nWrite a 2-3 sentence intro for the week's matchup page. It's about THIS "
        "WEEK: the best game on the slate and why, who looks loaded and who looks thin, "
        "what's at stake in the standings if it's not Week 1. No league history, no "
        "'since 2022', no championship-count throat-clearing. Plain prose, no headline, "
        "no markdown.")
    return claude(sys, user, max_tokens=300).strip()
