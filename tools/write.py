"""Turn a normalized matchup into a Claude-written preview or recap."""
import re
from lib import claude, PRO
from lore import LEAGUE_FACTS, NOTES, OWNERS, RIVALRIES, rivalry_between

_VOICE = """\
You are the beat writer for the Players League, a 12-team fantasy football league of
close friends now in its 5th season. You've covered every game since 2022. Your voice:
sharp, funny, a little mean in the way friends are mean to each other, confident with
the numbers, never corny. No hashtags, no emoji, no "folks", no fantasy-guru cliches
("buckle up", "must-start", "smash play", "league-winner")."""

SYSTEM_PREVIEW = _VOICE + """

This is a matchup PREVIEW and it is TRASH TALK. Chirp both teams the way you'd roast
your buddies in the group chat — mean, funny, no mercy. Pick a side and bury the
other one. Crude is fine.

But the smack talk has to be ABOUT THE FOOTBALL — roughly:
- ~80% the actual matchup: which roster is thin or top-heavy at each position, the
  players who decide it, the boom/bust guys, bad byes and injuries, the positional
  mismatches. Roast the weak spots by name. Lineups may not be locked, so talk about
  each team's ROSTER at a position (best options, depth), not just who's slotted.
- ~20% the guys: go at the owners too — a live rivalry, a reach they made, whatever's
  fair game. No long league-history lectures, but a jab at someone's track record is
  fine if it lands.

Use owners' first names for the teams. Refer to NFL players by name.

Output format — EXACTLY this, nothing before or after:
HEADLINE: <4-9 words, punchy, has some bite>

<body: exactly 2 short paragraphs, plain prose, no markdown, ~110-150 words total.
Separate the paragraphs with one blank line.>

PICK: <owner first name> by <whole number>

The PICK is a real prediction and it gets graded in next week's recap, so commit to
it. It has to agree with what you just argued. Margins are usually 5-25 points.
"""

SYSTEM_RECAP = _VOICE + """

This is a matchup RECAP and it is TRASH TALK. The winner gets a victory lap, the
loser gets roasted. Mean, funny, group-chat energy. Crude is fine.

The smack talk is ABOUT THE FOOTBALL — roughly:
- ~75% what actually happened: the score, the swing, who carried it, who face-planted
  against projection, the points left rotting on the bench, the position that lost it.
  Name names. Roast the busts.
- ~25% the guys: what the L means for them, a rivalry beat, a standings jab.

Use owners' first names. Refer to NFL players by name.

Output format — EXACTLY this, nothing before or after:
HEADLINE: <4-9 words, punchy, has some bite>

<body: 2-3 short paragraphs, plain prose, no markdown, ~110-160 words total.
Separate paragraphs with one blank line.>
"""


def _parse(raw, valid_owners=None):
    raw = raw.strip()
    head, _, body = raw.partition("\n")
    head = head.strip()
    if head.upper().startswith("HEADLINE:"):
        head = head.split(":", 1)[1].strip()
    else:                       # model skipped the label — take first line as headline
        body = raw[len(head):]

    # pull a trailing "PICK: Adam by 12" off the body, if there is one
    pick, keep = None, []
    for line in body.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith("PICK:"):
            mt = re.match(r"\s*([A-Za-z]+)\s+by\s+(\d+)", line.split(":", 1)[1].strip())
            if mt and (valid_owners is None or mt.group(1) in valid_owners):
                pick = {"owner": mt.group(1), "margin": int(mt.group(2))}
            continue
        keep.append(line)
    return {"headline": head.strip(' "'), "body": "\n".join(keep), "pick": pick}


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


def _roster_block(side, nfl_games=None):
    """Full roster grouped by position, projections desc — for previews (lineups
    may not be set). Injury tags and the player's real NFL game are included."""
    by_pos = {}
    for p in side.get("players", []):
        by_pos.setdefault(p["pos"], []).append(p)
    rows = []
    for pos in _POS_ORD:
        ps = sorted(by_pos.get(pos, []), key=lambda x: -x["proj"])
        if not ps:
            continue
        bits = []
        for p in ps:
            s = f'{p["name"]} ({p["pro"]}, {p["proj"]:.0f}'
            if p.get("injury"):
                s += f', {p["injury"]}'
            s += ')'
            bits.append(s)
        rows.append(f'  {pos}: ' + ", ".join(bits))
    return rows


def _season_block(o, ctx, label=""):
    """One owner's season form — record, scoring, all-play, luck, streak, power rank."""
    if not ctx:
        return []
    res = (ctx.get("results") or {}).get("by_owner", {}).get(o) or {}
    pb = (ctx.get("power") or {}).get(o) or {}
    out = []
    if res.get("gp"):
        rk = res.get("ranks", {})
        line = f'  {o}: {res["record"]}'
        if res.get("streak"):
            line += f' ({res["streak"]})'
        line += f', {res["pf_pg"]:.1f} pts/game'
        if "pf_pg" in rk:
            line += f' ({rk["pf_pg"]})'
        out.append(line)
        out.append(f'    all-play {res["allplay"][0]}-{res["allplay"][1]} '
                   f'({res["allplay_pct"]}%'
                   + (f', {rk["allplay_pct"]}' if "allplay_pct" in rk else '')
                   + f') — their record if they played everyone every week')
        out.append(f'    luck {res["luck"]:+.1f} wins vs expected'
                   + (' — winning more than they have earned'
                      if res["luck"] >= 0.5 else
                      ' — scoring well and losing anyway' if res["luck"] <= -0.5
                      else ''))
        if res.get("last3"):
            out.append(f'    last {len(res["last3"])} weeks: '
                       + ", ".join(f'{s:.1f}' for s in res["last3"]))
        if res.get("best_week"):
            out.append(f'    season high {res["best_week"][1]:.1f} (wk {res["best_week"][0]}), '
                       f'low {res["worst_week"][1]:.1f} (wk {res["worst_week"][0]})')
    if pb.get("rank"):
        out.append(f'    {o} power ranking: #{pb["rank"]} of 12 going into this week')
    return out


def _h2h_block(a, b, ctx):
    """EARLIER meetings between these two this season — never the game at hand."""
    res = ctx.get("results") if ctx else None
    if not res or not res.get("opp"):
        return []
    this_week = (ctx or {}).get("week")
    met = []
    for w in res["weeks"]:
        if this_week is not None and w >= this_week:
            continue
        if res["opp"].get(w, {}).get(a) == b:
            met.append((w, res["scores"][w][a], res["scores"][w][b]))
    if not met:
        return []
    out = ['\nThey have already met this season:']
    for w, sa, sb in met:
        win = a if sa > sb else b if sb > sa else "nobody"
        out.append(f'  Week {w}: {a} {sa:.1f}, {b} {sb:.1f} — {win} won')
    return out


def _nfl_block(sides, ctx, top_n=6):
    """Real NFL game context (spread, total) for the players who actually matter."""
    games = (ctx or {}).get("nfl") or {}
    if not games:
        return []
    import nfl as NF
    pros = []
    for side in sides:
        for p in sorted(side.get("players", []), key=lambda x: -x["proj"])[:top_n]:
            if p["pro"] in games and p["pro"] not in pros:
                pros.append(p["pro"])
    if not pros:
        return []
    out = ['\nThe real NFL games these points come from (betting lines — a big total '
           'means a shootout, a big underdog may be chasing points late):']
    for t in pros:
        out.append(f'  {t}: {NF.describe(t, games[t])}')
    return out


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


def _bench_block(side):
    """Points left rotting on the bench — the most quotable stat in any recap."""
    bench = [p for p in side.get("players", []) if not p.get("started")]
    if not bench:
        return []
    misses = []
    for b in sorted(bench, key=lambda x: -x["actual"])[:3]:
        worst = min((s for s in side["starters"] if s["pos"] == b["pos"]
                     or (b["pos"] in ("RB", "WR", "TE") and s["slot"] == "FLEX")),
                    key=lambda s: s["actual"], default=None)
        if worst and b["actual"] - worst["actual"] >= 5:
            misses.append(f'{b["name"]} scored {b["actual"]:.1f} on the bench while '
                          f'{worst["name"]} started and scored {worst["actual"]:.1f}')
    if not misses:
        return []
    return [f'  {side["owner"]} left points on the bench: ' + "; ".join(misses)]


def _matchup_facts(m, phase, ctx=None):
    h, a = m["home"], m["away"]
    A, H = a["owner"], h["owner"]
    lines = [f'{A} ("{a["team"]}", {a["record"]}) at {H} ("{h["team"]}", {h["record"]}).']

    season_a = _season_block(A, ctx)
    season_h = _season_block(H, ctx)
    if season_a or season_h:
        lines.append('\nWhere they stand this season (all comparisons in parentheses are '
                     'verified league ranks — those are the only ones you may claim):')
        lines += season_a + season_h
    lines += _h2h_block(A, H, ctx)

    if phase == "preview":
        ao, ho = a.get("optimal_proj", a["projected"]), h.get("optimal_proj", h["projected"])
        lines.append(f'\nBest-lineup projection (from the full roster, since lineups may not '
                     f'be locked): {A} ~{ao:.0f}, {H} ~{ho:.0f} '
                     f'({A if ao >= ho else H} projects ahead by ~{abs(ao - ho):.0f}).')
        games = (ctx or {}).get("nfl") or {}
        lines.append(f'\n{A} — full roster by position (proj pts, best first):')
        lines += _roster_block(a, games)
        lines.append(f'\n{H} — full roster by position (proj pts, best first):')
        lines += _roster_block(h, games)
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
        lines += _nfl_block((a, h), ctx)
        riv = rivalry_between(a["owner_full"], h["owner_full"])
        lines.append('\nOwner note (at most ONE short clause, only if it fits — otherwise ignore):')
        lines.append(f'  {riv}.' if riv else '  (no live rivalry between these two — skip owner talk)')
        return "\n".join(lines)

    # ---- recap: lineups are locked, use starters + actuals ----
    a_rows, a_tot = _lineup_block(a, "actual")
    h_rows, h_tot = _lineup_block(h, "actual")
    lines.append(f'\nFINAL: {A} {a["actual"]:.1f}, {H} {h["actual"]:.1f} — '
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
        bench = _bench_block(a) + _bench_block(h)
        if bench:
            lines.append('\nBench regrets:')
            lines += bench
        if m.get("predicted"):
            p = m["predicted"]
            hit = p.get("owner") == m["winner"]
            lines.append(f'\nOur Week {m.get("week","")} preview picked {p.get("owner")} '
                         f'to win by {p.get("margin")} — that pick was '
                         + ('RIGHT.' if hit else 'WRONG.')
                         + ' One short clause about it, only if it lands.')

    lines.append("\nOwner angle (use for ~20% of the piece, not more):")
    riv = rivalry_between(a["owner_full"], h["owner_full"])
    if riv:
        lines.append(f'  Rivalry: {riv}.')
    for who in (a, h):
        note = NOTES.get(who["owner"])
        if note:
            lines.append(f'  {who["owner"]}: {note}')
    return "\n".join(lines)


# ---------------------------------------------------------------- verification

def _misattributed(body, m, ctx):
    """Players named in the copy who are rostered by someone ELSE in this league.

    Shape-based "is this a real name" checks can't tell "Coin Flip" from "Josh
    Jacobs", so don't try. The damaging error is attributing another manager's
    player to this matchup, and that we can check exactly: every roster in the
    league is known, so a name that belongs to a third team is unambiguously wrong.
    """
    pool = (ctx or {}).get("all_players") or {}
    if not pool:
        return []
    here = {m["away"]["owner"], m["home"]["owner"]}
    bad = []
    for name, holder in pool.items():
        if holder in here or len(name) < 6 or " " not in name:
            continue
        if re.search(r"\b" + re.escape(name) + r"\b", body):
            bad.append(f"{name} (rostered by {holder})")
    return sorted(set(bad))


def _bad_scores(body, allowed):
    """Score-shaped numbers (xx.x) in the copy that aren't in the data."""
    out = []
    for tok in re.findall(r"\b\d{2,3}\.\d\b", body):
        if tok not in allowed:
            out.append(tok)
    return sorted(set(out))


def write_matchup(m, week, phase, ctx=None):
    sysmsg = SYSTEM_PREVIEW if phase == "preview" else SYSTEM_RECAP
    kind = "preview" if phase == "preview" else "recap"
    facts = _matchup_facts(m, phase, ctx)
    user = (
        f"League background (for the ~20% owner angle only):\n{LEAGUE_FACTS}\n\n"
        f"Write the Week {week} {kind} for this matchup.\n\n"
        f"{facts}\n"
    )
    allowed_scores = set(re.findall(r"\b\d{2,3}\.\d\b", facts))
    sides = {m["away"]["owner"], m["home"]["owner"]}

    out = None
    for attempt in range(2):
        out = _parse(claude(sysmsg, user, max_tokens=1000), sides)
        text = out["body"] + " " + out["headline"]
        bad_names = _misattributed(text, m, ctx)
        bad_nums = _bad_scores(out["body"], allowed_scores)
        if not bad_names and not bad_nums:
            break
        fix = "\n\nREWRITE — your last draft failed fact-checking:"
        if bad_names:
            fix += ("\n- These players are on a DIFFERENT team in this league, not in "
                    "this matchup: " + ", ".join(bad_names)
                    + ". Only write about players in the DATA block above.")
        if bad_nums:
            fix += ("\n- These numbers do not appear in the data: "
                    + ", ".join(bad_nums)
                    + ". Quote scores and projections exactly as given, or don't cite them.")
        user += fix + "\nWrite it again, same format."
        print(f"      fact-check retry: " + "; ".join(bad_names + bad_nums)[:110])
    if not out["headline"]:
        out["headline"] = f'{m["away"]["owner"]} at {m["home"]["owner"]}'
    return out


SYSTEM_GRADE = _VOICE + """

This is a DRAFT GRADE for one team, and the tone is COMPLIMENTARY. You're hyping this
draft up. Lead hard with what they got right — the vision, the value, the upside, the
positions they nailed. Find something genuinely good to say about every team. Drop
the sarcasm entirely; this reads like a proud analyst who sees the plan.

Weight it about 80/20:
- 80% the actual NFL players and the roster: the anchors, the value picks, the depth,
  the smart construction (RB-early, zero-RB, waited on QB and it worked), the upside
  bets. Name players. Be concrete and be positive.
- 20% the owner: one warm line tying it to their history or the league.

Flaws: mention at most ONE, briefly, framed as "the one thing to watch" — and always
follow it with why it might not matter (a late-round upside guy, a good bye, waivers).
Never dwell on it. Every owner should finish reading and feel good about their draft.

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

The grade is an absolute 0-100 score. Whatever the number, the writeup stays upbeat:
a 90+ draft is a masterclass; a mid-70s draft is "a real foundation with a clear
identity and room to grow." Sell the strengths either way.

Output format — EXACTLY this, nothing before or after:
HEADLINE: <4-9 words about the roster or the draft plan — positive, not a punchline>

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
        "\n\nWrite a 3-4 sentence intro for the draft-grades page, and keep it "
        "COMPLIMENTARY — this was a strong draft class top to bottom. Hype the teams "
        "that crushed it, and frame the rest as loaded-in-their-own-way rather than "
        "thin. One position run worth noting. Upbeat, no snark. Plain prose, no "
        "headline, no markdown.")
    user = (f"{LEAGUE_FACTS}\n\n{g['season']} draft grades, best to worst:\n{board}\n")
    return claude(sysmsg, user, max_tokens=320).strip()


SYSTEM_POWER = _VOICE + """

These are the weekly POWER RANKINGS. The register is HONEST WITH BITE — you're the
guy who actually watched the tape and isn't going to pretend a 6-8 team is good
because they got lucky. Praise the top of the board like they earned it, and be
blunt about the bottom without being cruel for its own sake. Funny, not nasty.
Every roast has to be backed by a number.

Roughly 75% football, 25% the guy. Use owners' first names. Refer to NFL players
by name.

ACCURACY — people in this league read these and will check:
- Every number you cite must appear in the DATA block. Never invent a score, a
  record, a rank, a projection, or a stat.
- Only name NFL players who appear in that team's roster list in the DATA block.
- You are shown ONE team, not the whole league. The ONLY comparisons you may make
  are the ones the data states as a league rank — "3rd of 12", "T-5th of 12".
  If the data doesn't give you a rank for something, you cannot claim it's the
  best, worst, most, least, highest or lowest in the league. Say what it is, not
  where it sits.
- The power score, the draft grade, and the results/roster indexes are four
  different numbers. Don't blend them, and don't quote an index as "X/100" — an
  index is league-relative, 50 is average.
- "All-play" means their record if they'd played every team every week — it's the
  truest measure of how well they've actually scored. "Luck" is real wins minus
  expected wins: positive = winning games their scores didn't earn, negative =
  scoring well and losing anyway. Use these correctly or not at all.
- The ranking is already decided and given to you. Do not argue for a different
  rank, and do not say a team is ranked too high or too low.
- Don't invent NFL context: no snap shares, no scheme takes, no injury timelines
  beyond an injury tag that's in the data.
- Don't invent things the owner said or did. Roast their team and their results,
  which are on the record; don't put words in their mouth.

Output format — EXACTLY this, nothing before or after:
HEADLINE: <4-9 words, punchy, specific to this team>

<body: ONE paragraph, plain prose, no markdown, 70-95 words.>
"""

SYSTEM_NUDGE = _VOICE + """

You are reviewing a statistical model's power-ranking board before it publishes.
The model is good — it weighs all-play record, points per game, recent form and
roster strength. Your job is NOT to rewrite it. Your job is to catch the handful
of things a formula structurally cannot see.

Legitimate reasons to move a team:
- A key player just got hurt, or is back, and the roster list shows it.
- The model is still being dragged by one fluke week that no longer reflects them.
- A team's scoring is trending hard in one direction inside the form window.
- Points-per-game flatters a team that piled on in blowouts, or hides one that
  keeps losing shootouts.

NOT legitimate: a hunch, reputation, league history, "they always figure it out",
or disagreeing with how the model weighs things.

Rules:
- You may move a team at most 2 spots, up or down.
- Most weeks you should move ZERO to TWO teams. Moving lots of teams means you're
  second-guessing the model, which is wrong.
- Every move needs a concrete reason grounded in the data you were given.

Output format — EXACTLY this, nothing else. One line per move:
<Owner first name>: <+1 | +2 | -1 | -2> — <short reason, under 15 words>

If nothing should move, output exactly:
NONE
"""


def power_nudge(board, board_text):
    """Ask for small, justified ordering adjustments. Returns ({owner: delta}, [reasons])."""
    valid = {r["owner"] for r in board["rows"]}
    wk = board["week"]
    when = (f"after Week {wk}" if wk else "preseason, before any games")
    user = (
        f"Players League power rankings, {when}. The model's board, best to worst:\n\n"
        f"{board_text}\n\n"
        "Per-team detail:\n\n"
        + "\n\n".join(_pw_facts(r, board) for r in board["rows"])
        + "\n\nReview this board. Which teams, if any, are misplaced for a reason the "
          "model cannot see?"
    )
    raw = claude(SYSTEM_NUDGE, user, max_tokens=500).strip()
    deltas, reasons = {}, []
    if raw.upper().startswith("NONE"):
        return deltas, reasons
    for line in raw.splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name = name.strip()
        if name not in valid:
            continue
        rest = rest.strip()
        sign = 1 if rest.startswith("+") else -1 if rest.startswith("-") else 0
        digits = "".join(ch for ch in rest[:3] if ch.isdigit())
        if not sign or not digits:
            continue
        delta = sign * int(digits[0])
        if abs(delta) > 2:
            delta = 2 * sign
        deltas[name] = delta
        why = ""
        for sep in ("—", "–", " - "):
            if sep in rest:
                why = rest.split(sep, 1)[1].strip()
                break
        reasons.append(f'{name} {delta:+d}' + (f': {why}' if why else ''))
    return deltas, reasons


def _pw_facts(r, board):
    import power as PW
    return PW.team_facts(r, board)


def power_team(r, board):
    """One team's power-ranking blurb."""
    wk = board["week"]
    when = (f"Week {wk}" if wk else "the preseason")
    frame = ("No games have been played yet — judge them on the roster they drafted "
             "and what it projects to do."
             if not board["gp"] else
             "Judge them on what they've actually done, with the roster as context.")
    user = (f"League background (for the ~25% owner angle only):\n{LEAGUE_FACTS}\n\n"
            f"Write the {when} power-rankings blurb for this team. {frame}\n\n"
            f"DATA:\n{_pw_facts(r, board)}\n")
    out = _parse(claude(SYSTEM_POWER, user, max_tokens=700))
    if not out["headline"]:
        out["headline"] = f'#{r["rank"]} {r["owner"]}'
    return out


def power_intro(board, board_text, nudge_reasons):
    wk = board["week"]
    when = (f"after Week {wk}" if wk else "preseason")
    rows = board["rows"]
    movers = [r for r in rows if r.get("move")]
    movers.sort(key=lambda r: -abs(r["move"]))
    mv = "\n".join(f'{r["owner"]}: #{r["prev_rank"]} -> #{r["rank"]}' for r in movers[:5])
    extra = f"\nBiggest movers since last week:\n{mv}\n" if mv else ""
    if nudge_reasons:
        extra += ("\nThe model's raw order was overridden on review for these teams, which is "
                  "why their scores don't run in a straight line down the board:\n  "
                  + "\n  ".join(nudge_reasons) + "\n")
    user = (f"Players League power rankings, {when}. Final board, best to worst:\n\n"
            f"{board_text}\n{extra}\n"
            f"Write the 3-4 sentence intro for this page.")
    sysmsg = _VOICE + (
        "\n\nWrite a 3-4 sentence intro for the weekly power-rankings page. HONEST WITH "
        "BITE — name the team at the top and why they're there, the team at the bottom "
        "and why, and the most interesting mover. Back every claim with a number from "
        "the board — and when two teams look tied, check the decimals before saying so. "
        "Don't invent schedule facts (how many weeks are left, who plays whom, playoff "
        "dates) — you haven't been told any of that. No league history lectures. Plain "
        "prose, no headline, no markdown.")
    return claude(sysmsg, user, max_tokens=340).strip()


def write_intro(league, week, phase):
    kind = "preview" if phase == "preview" else "recap"

    def _line(m):
        a, h = m["away"], m["home"]
        if phase != "preview":
            return (f'{a["owner"]} {a["actual"]} at {h["owner"]} {h["actual"]} — '
                    f'{m["winner"]} won by {m["margin"]}')
        # spell out who is favored; given only two bare numbers the direction
        # gets flipped about half the time
        ap, hp = a["projected"], h["projected"]
        fav, dog, gap = ((h["owner"], a["owner"], hp - ap) if hp >= ap
                         else (a["owner"], h["owner"], ap - hp))
        return (f'{a["owner"]} at {h["owner"]} — projected {a["owner"]} {ap}, '
                f'{h["owner"]} {hp}. {fav} is FAVORED by {abs(gap):.1f} over {dog}.')

    board = "\n".join(_line(m) for m in league["matchups"])
    stakes = ""
    if phase == "preview" and league["week"] > 1:
        board2 = "\n".join(f'{s["owner"]}: {s["record"]}' for s in league["standings"])
        stakes = f"\nCurrent standings:\n{board2}\n"
    user = (
        f"Week {week} {kind}. The games:\n{board}\n{stakes}\n"
        f"Write the 2-3 sentence intro for this page."
    )
    sys = _VOICE + (
        "\n\nWrite a 2-3 sentence intro for the week's matchup page, and make it SMACK "
        "TALK — group-chat energy, mean and funny. It's about THIS WEEK: hype the best "
        "game on the slate, then call out who's walking into a beating and who padded "
        "their schedule. What's at stake in the standings if it's not Week 1. No league "
        "history, no 'since 2022', no championship-count throat-clearing. "
        "Get the direction right: the board tells you who is FAVORED in each game — "
        "never say the underdog is winning by the margin. Plain prose, no headline, "
        "no markdown.")
    return claude(sys, user, max_tokens=300).strip()
