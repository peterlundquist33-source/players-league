"""Fun facts for the Teams page.

Writes js/team-facts.js:  const TEAM_FACTS = { "<Full Name>": ["fact", ...], ... }.
The Teams page shows a random one on hover, so the page reads differently every
visit. Two sources, both grounded in the same numbers:

  1. computed, guardrailed one-liners derived straight from ESPN box scores,
     2022 -> present (head-to-head, weekly crowns, blowouts, luck, streaks, ...)
  2. a handful of AI one-liners in the league voice, fed ONLY those same numbers
     and number-checked before they're kept.

Run:  python3 tools/main.py facts --season 2026
      python3 tools/facts.py 2026
"""
import datetime
import json
import re

from lib import ROOT, claude, load_env
from lore import LEAGUE_FACTS, NOTES, OWNERS, owner as canon
from analytics import FIRST_SEASON, _aggregate, _pull

OUT = ROOT / "js" / "team-facts.js"

FIRST_TO_FULL = {v: k for k, v in OWNERS.items()}          # "Adam" -> "Adam Stockwell"
AI_PER_TEAM = 6
POOL_CAP = 18
STALE_DAYS = 6


# ---------------------------------------------------------------- compute

def _ord(n):
    return f'{n}{"th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")}'


def _wk(week, year):
    return f'Week {week}, {year}'


def _profiles(through_season):
    """One dict per owner of verified numbers, plus the raw pulls for finishes."""
    pulls = []
    for yr in range(FIRST_SEASON, through_season + 1):
        try:
            p = _pull(yr)
        except SystemExit:
            continue
        if p["weeks"]:
            pulls.append(p)

    agg = _aggregate(pulls)
    arow = {r["owner"]: r for r in agg["rows"]}
    owners = agg["owners"]
    n = len(owners)

    # regular-season finish (wins, then PF) per season
    finish = {}
    for p in pulls:
        tally = {o: [0, 0.0] for o in p["owners"]}
        for w in p["weeks"]:
            for o, s in p["scores"][w].items():
                tally[o][1] += s
                if p["result"][w][o] == "W":
                    tally[o][0] += 1
        order = sorted(p["owners"], key=lambda o: (-tally[o][0], -tally[o][1]))
        for i, o in enumerate(order, 1):
            finish.setdefault(o, {})[p["season"]] = i

    sched_rank = {r["owner"]: i for i, r in enumerate(
        sorted((r for r in agg["rows"] if r["sched"] is not None),
               key=lambda r: -r["sched"]), 1)}
    luck_rank = {r["owner"]: i for i, r in enumerate(
        sorted(agg["rows"], key=lambda r: -r["luck"]), 1)}
    pf_rank = {r["owner"]: i for i, r in enumerate(
        sorted(agg["rows"], key=lambda r: -r["pf"]), 1)}

    out = {}
    for o in owners:
        r = arow[o]
        seasons, nicknames = [], []
        best = {"pts": 0.0}
        worst = {"pts": 1e9}
        high_loss = {"pts": 0.0}
        low_win = {"pts": 1e9}
        big_win = {"margin": 0.0}
        worst_loss = {"margin": 0.0}
        narrow_win = {"margin": 1e9}
        narrow_loss = {"margin": 1e9}
        crowns = cellars = 0
        blowout_wins = heartbreak_losses = 0
        longest_w = longest_l = 0
        h2h = {}
        total_pts = games = wins = losses = ties = 0

        for p in pulls:
            if o not in p["owners"]:
                continue
            yr = p["season"]
            nm = (p["tname"].get(o) or "").strip()
            if nm and (not nicknames or nicknames[-1][1] != nm):
                nicknames.append((yr, nm))
            sw = sl = st = 0
            spf = 0.0
            cw = cl = 0
            for w in p["weeks"]:
                s = p["scores"][w].get(o)
                if s is None:
                    continue
                opp = p["opp"][w][o]
                osc = p["scores"][w][opp]
                res = p["result"][w][o]
                margin = round(s - osc, 1)
                spf += s
                total_pts += s
                games += 1
                allsc = p["scores"][w]
                if s >= max(allsc.values()) - 1e-6:
                    crowns += 1
                if s <= min(allsc.values()) + 1e-6:
                    cellars += 1
                if s > best["pts"]:
                    best = {"pts": round(s, 1), "week": w, "year": yr, "opp": opp}
                if s < worst["pts"]:
                    worst = {"pts": round(s, 1), "week": w, "year": yr, "opp": opp}
                d = h2h.setdefault(opp, [0, 0, 0])
                if res == "W":
                    sw += 1
                    wins += 1
                    d[0] += 1
                    cw += 1
                    cl = 0
                    if margin >= 40:
                        blowout_wins += 1
                    if margin > big_win["margin"]:
                        big_win = {"margin": margin, "opp": opp, "week": w, "year": yr}
                    if margin < narrow_win["margin"]:
                        narrow_win = {"margin": margin, "opp": opp, "week": w, "year": yr}
                    if s < low_win["pts"]:
                        low_win = {"pts": round(s, 1), "week": w, "year": yr, "opp": opp}
                elif res == "L":
                    sl += 1
                    losses += 1
                    d[1] += 1
                    cl += 1
                    cw = 0
                    if -margin <= 3:
                        heartbreak_losses += 1
                    if -margin > worst_loss["margin"]:
                        worst_loss = {"margin": round(-margin, 1), "opp": opp, "week": w, "year": yr}
                    if -margin < narrow_loss["margin"]:
                        narrow_loss = {"margin": round(-margin, 1), "opp": opp, "week": w, "year": yr}
                    if s > high_loss["pts"]:
                        high_loss = {"pts": round(s, 1), "week": w, "year": yr, "opp": opp}
                else:
                    st += 1
                    ties += 1
                    d[2] += 1
                    cw = cl = 0
                longest_w = max(longest_w, cw)
                longest_l = max(longest_l, cl)
            seasons.append({"year": yr, "record": f'{sw}-{sl}' + (f'-{st}' if st else ''),
                            "pf": round(spf, 1), "name": nm,
                            "finish": finish.get(o, {}).get(yr)})

        # head-to-head extremes (min 4 meetings)
        played = {k: v for k, v in h2h.items() if sum(v) >= 4}
        nemesis = owned = None
        if played:
            worst_opp = min(played, key=lambda k: (played[k][0] - played[k][1]))
            if played[worst_opp][1] > played[worst_opp][0]:
                w_, l_, _ = played[worst_opp]
                nemesis = {"opp": worst_opp, "w": w_, "l": l_}
            best_opp = max(played, key=lambda k: (played[k][0] - played[k][1]))
            if played[best_opp][0] > played[best_opp][1]:
                w_, l_, _ = played[best_opp]
                owned = {"opp": best_opp, "w": w_, "l": l_}
        sweeps = sorted(k for k, v in h2h.items() if v[1] == 0 and v[0] >= 3)
        swept_by = sorted(k for k, v in h2h.items() if v[0] == 0 and v[1] >= 3)
        h2h_record = {k: f'{v[0]}-{v[1]}' + (f'-{v[2]}' if v[2] else '')
                      for k, v in sorted(h2h.items())}

        best_season = max(seasons, key=lambda s: (int(s["record"].split("-")[0]), s["pf"]))
        worst_season = min(seasons, key=lambda s: (int(s["record"].split("-")[0]), s["pf"]))

        def _rb(e, margin_key, foe_key):
            if not e or "opp" not in e:
                return None
            return {margin_key: e["margin"], foe_key: e["opp"],
                    "week": e["week"], "year": e["year"]}

        out[o] = {
            "owner": o,
            "career_record": f'{wins}-{losses}' + (f'-{ties}' if ties else ''),
            "win_pct": round(100 * (wins + 0.5 * ties) / games) if games else 0,
            "games": games,
            "avg_points": round(total_pts / games, 1) if games else 0,
            "career_pf": round(total_pts, 1),
            "career_pf_rank": pf_rank[o],
            "expected_wins": r["xw"],
            "actual_wins": r["aw"],
            "luck": r["luck"],
            "luck_rank": luck_rank[o],
            "schedule_difficulty_rank": sched_rank.get(o),
            "seasons_played": len(seasons),
            "seasons": seasons,
            "best_season": best_season,
            "worst_season": worst_season,
            "team_names": [nm for _, nm in nicknames],
            "team_names_debut_year": nicknames[0][0] if nicknames else None,
            "best_week": best,
            "worst_week": worst,
            "highest_score_in_a_loss": ({"points": high_loss["pts"], "lost_to": high_loss["opp"],
                                         "week": high_loss["week"], "year": high_loss["year"]}
                                        if high_loss["pts"] else None),
            "lowest_score_in_a_win": ({"points": low_win["pts"], "beat": low_win["opp"],
                                       "week": low_win["week"], "year": low_win["year"]}
                                      if low_win["pts"] < 1e9 else None),
            "biggest_win": _rb(big_win if big_win["margin"] else None, "won_by", "beat"),
            "worst_loss": _rb(worst_loss if worst_loss["margin"] else None, "lost_by", "lost_to"),
            "narrowest_win": _rb(narrow_win if narrow_win["margin"] < 1e9 else None, "won_by", "beat"),
            "narrowest_loss": _rb(narrow_loss if narrow_loss["margin"] < 1e9 else None, "lost_by", "lost_to"),
            "weekly_high_scorer_count": crowns,
            "weekly_low_scorer_count": cellars,
            "blowout_wins_40plus": blowout_wins,
            "losses_by_3_or_less": heartbreak_losses,
            "longest_win_streak": longest_w,
            "longest_losing_streak": longest_l,
            "nemesis": nemesis,
            "owns": owned,
            "never_lost_to": sweeps,
            "swept_by": swept_by,
            "head_to_head": h2h_record,
        }
    return out, n


# ---------------------------------------------------------------- deterministic facts

def _computed_facts(p, n_owners):
    f = p["owner"]
    out = []

    out.append(f'{f} is {p["career_record"]} all-time — a {p["win_pct"]}% clip, '
               f'{_ord(p["career_pf_rank"])} of {n_owners} in career points.')

    if p["luck"] <= -2.5:
        out.append(f'{f} has {p["actual_wins"]:.0f} real wins against {p["expected_wins"]:.0f} '
                   f'expected — the schedule owes him about {abs(p["luck"]):.0f}.')
    elif p["luck"] >= 2.5:
        out.append(f'{f} has banked {p["luck"]:.1f} more wins than his scores deserved. '
                   f'The bracket gods like him.')

    bw = p["best_week"]
    out.append(f'{f}\'s career high is {bw["pts"]:.1f} points, {_wk(bw["week"], bw["year"])}.')
    ww = p["worst_week"]
    out.append(f'{f}\'s floor game: {ww["pts"]:.1f} points, {_wk(ww["week"], ww["year"])}. It happens.')

    if p["nemesis"]:
        ne = p["nemesis"]
        out.append(f'{f} cannot solve {ne["opp"]}: {ne["w"]}-{ne["l"]} against him all-time.')
    if p["owns"]:
        ow = p["owns"]
        out.append(f'{f} owns {ow["opp"]} — {ow["w"]}-{ow["l"]} head-to-head and counting.')
    for v in p["never_lost_to"]:
        out.append(f'{f} has never lost to {v}. Not once.')
    for v in p["swept_by"]:
        out.append(f'{f} has never beaten {v}. Some day.')

    if p["weekly_high_scorer_count"]:
        out.append(f'{f} has been the single highest-scoring team in the league '
                   f'{p["weekly_high_scorer_count"]} different weeks.')
    if p["weekly_low_scorer_count"] >= 3:
        out.append(f'{f} has also been the week\'s lowest scorer {p["weekly_low_scorer_count"]} times. '
                   f'It evens out. Sort of.')

    def _m(x):
        return "under 0.1" if x < 0.1 else f'{x:.1f}'

    if p["biggest_win"] and p["biggest_win"]["won_by"] >= 30:
        b = p["biggest_win"]
        out.append(f'{f}\'s most lopsided beatdown: {b["beat"]} by {b["won_by"]:.1f}, '
                   f'{_wk(b["week"], b["year"])}.')
    if p["worst_loss"] and p["worst_loss"]["lost_by"] >= 30:
        b = p["worst_loss"]
        out.append(f'{f} once lost by {b["lost_by"]:.1f} to {b["lost_to"]} — '
                   f'{_wk(b["week"], b["year"])}. Just close the app.')
    if p["narrowest_loss"] and p["narrowest_loss"]["lost_by"] <= 1.5:
        b = p["narrowest_loss"]
        out.append(f'{f} lost to {b["lost_to"]} by {_m(b["lost_by"])} in {_wk(b["week"], b["year"])} '
                   f'— still the one that stings.')
    if p["narrowest_win"] and p["narrowest_win"]["won_by"] <= 1.5:
        b = p["narrowest_win"]
        out.append(f'{f} squeaked past {b["beat"]} by {_m(b["won_by"])}, {_wk(b["week"], b["year"])}. '
                   f'Style points don\'t count.')

    if p["losses_by_3_or_less"] >= 2:
        out.append(f'{f} has lost {p["losses_by_3_or_less"]} games by a field goal or less. '
                   f'Fantasy football is a cruel hobby.')
    if p["highest_score_in_a_loss"]:
        h = p["highest_score_in_a_loss"]
        out.append(f'{f} once put up {h["points"]:.1f} and still lost, {_wk(h["week"], h["year"])}. '
                   f'Nothing he could do.')
    if p["lowest_score_in_a_win"]:
        lw = p["lowest_score_in_a_win"]
        out.append(f'{f} once won with just {lw["points"]:.1f} points, {_wk(lw["week"], lw["year"])}. '
                   f'A W is a W.')

    if p["longest_win_streak"] >= 4:
        out.append(f'{f}\'s hottest run is {p["longest_win_streak"]} straight wins.')
    if p["longest_losing_streak"] >= 4:
        out.append(f'{f} has also dropped {p["longest_losing_streak"]} in a row at his lowest.')

    names = p["team_names"]
    if len(names) >= 3:
        out.append(f'{f} has cycled through {len(names)} team names: '
                   + ", ".join(f'"{x}"' for x in names) + '.')
    elif len(names) == 1 and p["team_names_debut_year"]:
        out.append(f'{f} has been "{names[0]}" since {p["team_names_debut_year"]} — '
                   f'no notes, no changes.')

    bs, wsn = p["best_season"], p["worst_season"]
    gap = int(bs["record"].split("-")[0]) - int(wsn["record"].split("-")[0])
    if bs["year"] != wsn["year"] and gap >= 4:
        out.append(f'{f}\'s range: {bs["record"]} in {bs["year"]}, {wsn["record"]} in {wsn["year"]}. '
                   f'Same guy.')

    if p["schedule_difficulty_rank"] == 1:
        out.append(f'{f} has faced the softest schedule in league history. Lucky man.')
    elif p["schedule_difficulty_rank"] == n_owners:
        out.append(f'{f} has run the toughest gauntlet of anyone — hardest all-time schedule.')

    out.append(f'{f} averages {p["avg_points"]:.1f} points a week across {p["games"]} career games.')

    fin = [s["finish"] for s in p["seasons"] if s["finish"]]
    if fin and fin.count(1):
        out.append(f'{f} has finished the regular season in first place {fin.count(1)} time'
                   f'{"s" if fin.count(1) > 1 else ""}.')
    if fin and fin.count(n_owners):
        out.append(f'{f} has also finished dead last {fin.count(n_owners)} time'
                   f'{"s" if fin.count(n_owners) > 1 else ""}. Someone has to.')

    return out


# ---------------------------------------------------------------- AI facts

_SYS = """\
You write short, funny "fun facts" about one owner's fantasy-football history, for a
card that pops up when someone hovers that owner's tile on the league website. The
Players League is 12 close friends, 5th season. Voice: sharp, group-chat funny, a
little mean the way friends are mean, confident with numbers, never corny. No
hashtags, no emoji, no "folks", no fantasy-guru cliches.

HARD RULES:
- Every number, score, margin, week, season, matchup and result MUST come straight
  from the DATA block or the league background. Do NOT invent or estimate anything.
- Season records, career totals, head-to-head records, luck, streaks and the named
  record-book games (best/worst week, biggest win, worst loss, narrowest win/loss,
  etc.) are all fair game. If you name a specific week, cite the exact week AND year
  from the DATA — never a week that isn't in a record-book entry.
- The DATA has no playoff, championship, draft, trade or NFL-player detail. Do not
  mention any of that unless it's spelled out in the league background.
- Never call a game a tie, push or draw. A margin near zero in the DATA is still a
  win or a loss exactly as labelled.
- Only state a game's margin ("won by 5.3", "lost by 12") if that exact number is a
  won_by / lost_by value in the DATA. Otherwise don't put a number on the margin.
- Each fact is ONE sentence, standalone, names the owner, ~10-24 words.
- Don't just restate a stat — give it a little spin.

Output: exactly the requested number of facts, one per line, no numbering, no blank
lines, nothing else."""


def _nums(text):
    return {float(x) for x in re.findall(r'\d+\.?\d*', text.replace(",", ""))}


def _ai_facts(profile, want):
    allowed = _nums(json.dumps(profile)) | _nums(LEAGUE_FACTS) | set(range(0, 19))
    first = canon(profile["owner"])

    # every (week, year) the model is allowed to name comes from a record-book entry
    wk_year_ok = set()
    for key in ("best_week", "worst_week", "biggest_win", "worst_loss", "narrowest_win",
                "narrowest_loss", "highest_score_in_a_loss", "lowest_score_in_a_win"):
        e = profile.get(key)
        if e and e.get("week") and e.get("year"):
            wk_year_ok.add((e["week"], e["year"]))

    def week_claims_ok(line):
        # "Week N" (capitalised) is how both generators cite a specific game
        for m in re.finditer(r'Week (\d{1,2})\b', line):
            wk = int(m.group(1))
            tail = line[m.end():m.end() + 12]
            yr = re.search(r'(20\d\d)', tail)
            if not yr or (wk, int(yr.group(1))) not in wk_year_ok:
                return False
        return True

    # the only game margins the model may state are the record-book ones
    ok_margins = {0.0}
    for key in ("biggest_win", "worst_loss", "narrowest_win", "narrowest_loss"):
        e = profile.get(key)
        if e:
            ok_margins.add(round(e.get("won_by", e.get("lost_by", 0.0)), 1))

    def margins_ok(line):
        for m in re.finditer(r'\bby (\d{1,3}(?:\.\d)?)\b', line):
            if line[m.end():m.end() + 5].lstrip().startswith(("plus", "+")):
                continue                       # "by 40-plus" / "by 40+" is a count, not a score
            v = float(m.group(1))
            if (v < 40 or "." in m.group(1)) and round(v, 1) not in ok_margins:
                return False
        return True

    user = (
        f"League background:\n{LEAGUE_FACTS}\n\n"
        f"Owner: {first} ({profile['owner']}).\n"
        f"Personality (already true, for tone): {NOTES.get(first, '')}\n\n"
        f"DATA (all verified):\n{json.dumps(profile, indent=2)}\n\n"
        f"Write {want} fun facts about {first}."
    )
    try:
        raw = claude(_SYS, user, max_tokens=600)
    except SystemExit as e:
        print(f"    AI facts skipped for {first}: {e}")
        return []

    kept = []
    for line in raw.splitlines():
        line = line.strip().lstrip("-*0123456789. ").strip()
        if not line or len(line) < 15:
            continue
        # flag numbers that look like a box score or a margin (not e.g. a .518 pct)
        bad = [x for x in _nums(line)
               if ((40 <= x <= 230) or (x >= 40 and x != int(x))) and x not in allowed]
        if bad:
            print(f"    dropped (unverified number {bad}): {line}")
            continue
        if not week_claims_ok(line):
            print(f"    dropped (unverified week): {line}")
            continue
        if not margins_ok(line):
            print(f"    dropped (unverified margin): {line}")
            continue
        if profile["career_record"].count("-") < 2 \
                and re.search(r'\b(tie|tied|ties|push|pushed|draw|stalemate)\b', line, re.I):
            print(f"    dropped (invented tie): {line}")
            continue
        for full, short in OWNERS.items():                # "Adam Stockwell" -> "Adam"
            line = line.replace(full, short)
        kept.append(line)
    return kept


# ---------------------------------------------------------------- render

def build(through_season):
    profiles, n = _profiles(through_season)
    pools = {}
    for first, full in FIRST_TO_FULL.items():
        p = profiles.get(canon(full))
        if not p:
            continue
        computed = _computed_facts(p, n)
        ai = _ai_facts(p, AI_PER_TEAM)
        print(f"  {first:<10} {len(computed)} computed + {len(ai)} AI")
        seen, pool = set(), []
        for fact in ai + computed:                       # AI first, then top up
            key = re.sub(r'\W+', '', fact.lower())[:60]
            if key in seen:
                continue
            seen.add(key)
            pool.append(fact)
        pools[full] = pool[:POOL_CAP]
    return pools


def _js(pools):
    lines = [
        "// Generated by tools/facts.py — do not hand-edit.",
        "// Refreshed by the weekly matchups workflow. Each owner has a pool of",
        "// verified one-liners; the Teams page shows a random one per hover.",
        f"// last built: {datetime.date.today().isoformat()}",
        "const TEAM_FACTS = {",
    ]
    for name, pool in pools.items():
        lines.append(f'  {json.dumps(name)}: [')
        for fact in pool:
            lines.append(f'    {json.dumps(fact)},')
        lines.append("  ],")
    lines.append("};")
    return "\n".join(lines) + "\n"


def update(season, force=False):
    load_env()
    if OUT.exists() and not force:
        age = (datetime.datetime.now()
               - datetime.datetime.fromtimestamp(OUT.stat().st_mtime)).days
        if age < STALE_DAYS:
            print(f"team-facts.js is {age}d old — fresh, skipping (use --force to rebuild)")
            return
    pools = build(season)
    if not pools:
        print("no fact pools built — leaving team-facts.js as-is")
        return
    OUT.write_text(_js(pools))
    print(f"wrote {OUT.relative_to(ROOT)} — {sum(len(v) for v in pools.values())} facts "
          f"across {len(pools)} teams")


if __name__ == "__main__":
    import sys
    yr = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    update(yr, force="--force" in sys.argv or "-f" in sys.argv)
