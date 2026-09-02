"""Fun facts for the Teams page.

Writes js/team-facts.js:  const TEAM_FACTS = { "<Full Name>": ["fact", ...], ... }.
The Teams page shows a random one on hover, so it reads differently every visit.

Source of truth is js/teams-data.js — the exact numbers a visitor sees when they
click into a profile (career record, head-to-head, season log, best week, rival).
Facts about those never contradict the profile because they come from the same file.
Regular-season-only extras (weekly high/low scorer, streaks, blowouts, nail-biters)
are pulled from ESPN box scores and always labelled as regular season.

  1. computed, guardrailed one-liners
  2. a few AI one-liners in the league voice, fed ONLY those numbers and then
     number / week / margin / tie-checked before they're kept.

Run:  python3 tools/main.py facts --season 2026
      python3 tools/facts.py 2026
"""
import datetime
import json
import re

from lib import ROOT, claude, load_env
from lore import LEAGUE_FACTS, NOTES, OWNERS, owner as canon
from analytics import FIRST_SEASON, compute_alltime, _pull

OUT = ROOT / "js" / "team-facts.js"
TEAMS_DATA = ROOT / "js" / "teams-data.js"

FIRST_TO_FULL = {v: k for k, v in OWNERS.items()}          # "Adam" -> "Adam Stockwell"
AI_PER_TEAM = 6
POOL_CAP = 18
STALE_DAYS = 6


def _ord(n):
    return f'{n}{"th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")}'


# ---------------------------------------------------------------- teams-data.js (source of truth)

def _teams_data():
    src = TEAMS_DATA.read_text()
    src = src[src.index("const TEAM_DATA"):]
    src = src[src.index("{"):src.index("};") + 1]
    raw = json.loads(src)

    out = {}
    for full, t in raw.items():
        first = canon(full)

        h2h = {}
        for opp, rec in re.findall(
                r'<span>([^<]+)</span><span[^>]*>(\d+-\d+(?:-\d+)?)</span>', t["h2h_html"]):
            of = canon(opp.strip())
            parts = [int(x) for x in rec.split("-")]
            h2h[of] = (parts[0], parts[1], parts[2] if len(parts) > 2 else 0)

        seasons = []
        for yr, rec, pf, nm in re.findall(
                r'<span>(\d{4})</span><span[^>]*>(\d+-\d+(?:-\d+)?)</span>'
                r'<span[^>]*>([\d.]+) PF</span><span[^>]*>([^<]*)</span>', t["seasons_html"]):
            seasons.append({"year": int(yr), "record": rec, "pf": float(pf), "name": nm.strip()})

        out[first] = {
            "owner": first,
            "full_name": full,
            "career_record": f'{t["career_w"]}-{t["career_l"]}',
            "career_wins": t["career_w"],
            "career_losses": t["career_l"],
            "win_pct": t["wp"],
            "career_points": float(str(t["career_pf"]).replace(",", "")),
            "best_week_ever": {"points": float(t["best_score"]), "when": t["best_info"]},
            "biggest_rival": {"owner": canon(t["rival"]), "record_vs_them": t["rival_rec"]},
            "head_to_head": {k: f'{v[0]}-{v[1]}' + (f'-{v[2]}' if v[2] else '')
                             for k, v in h2h.items()},
            "_h2h": h2h,
            "season_log": seasons,
        }
    return out


# ---------------------------------------------------------------- ESPN box scores (regular season only)

def _rs_events(through_season):
    pulls = []
    for yr in range(FIRST_SEASON, through_season + 1):
        try:
            p = _pull(yr)
        except SystemExit:
            continue
        if p["weeks"]:
            pulls.append(p)

    # regular-season finish (wins, then PF) per season, for "finished 1st / last" facts
    finish = {}
    for p in pulls:
        tally = {o: [0, 0.0] for o in p["owners"]}
        for w in p["weeks"]:
            for o, s in p["scores"][w].items():
                tally[o][1] += s
                if p["result"][w][o] == "W":
                    tally[o][0] += 1
        for i, o in enumerate(sorted(p["owners"], key=lambda o: (-tally[o][0], -tally[o][1])), 1):
            finish.setdefault(o, {})[p["season"]] = i

    ev = {}
    for p in pulls:
        for o in p["owners"]:
            e = ev.setdefault(o, {
                "best": {"pts": 0.0}, "worst": {"pts": 1e9},
                "high_loss": {"pts": 0.0}, "low_win": {"pts": 1e9},
                "big_win": {"m": 0.0}, "worst_loss": {"m": 0.0},
                "narrow_win": {"m": 1e9}, "narrow_loss": {"m": 1e9},
                "crowns": 0, "cellars": 0, "blowouts": 0, "nailbiter_losses": 0,
                "win_streak": 0, "lose_streak": 0, "games": 0, "points": 0.0,
                "finishes": sorted(finish.get(o, {}).items()),
            })
            cw = cl = 0
            for w in p["weeks"]:
                s = p["scores"][w].get(o)
                if s is None:
                    continue
                opp = p["opp"][w][o]
                osc = p["scores"][w][opp]
                res = p["result"][w][o]
                m = round(s - osc, 2)
                e["games"] += 1
                e["points"] += s
                allsc = p["scores"][w]
                if s >= max(allsc.values()) - 1e-6:
                    e["crowns"] += 1
                if s <= min(allsc.values()) + 1e-6:
                    e["cellars"] += 1
                if s > e["best"]["pts"]:
                    e["best"] = {"pts": round(s, 1), "week": w, "year": p["season"]}
                if s < e["worst"]["pts"]:
                    e["worst"] = {"pts": round(s, 1), "week": w, "year": p["season"]}
                if res == "W":
                    cw += 1
                    cl = 0
                    if m >= 40:
                        e["blowouts"] += 1
                    if m > e["big_win"]["m"]:
                        e["big_win"] = {"m": m, "opp": opp, "week": w, "year": p["season"]}
                    if m < e["narrow_win"]["m"]:
                        e["narrow_win"] = {"m": m, "opp": opp, "week": w, "year": p["season"]}
                    if s < e["low_win"]["pts"]:
                        e["low_win"] = {"pts": round(s, 1), "opp": opp, "week": w, "year": p["season"]}
                elif res == "L":
                    cl += 1
                    cw = 0
                    if -m <= 3:
                        e["nailbiter_losses"] += 1
                    if -m > e["worst_loss"]["m"]:
                        e["worst_loss"] = {"m": round(-m, 2), "opp": opp, "week": w, "year": p["season"]}
                    if -m < e["narrow_loss"]["m"]:
                        e["narrow_loss"] = {"m": round(-m, 2), "opp": opp, "week": w, "year": p["season"]}
                    if s > e["high_loss"]["pts"]:
                        e["high_loss"] = {"pts": round(s, 1), "opp": opp, "week": w, "year": p["season"]}
                else:
                    cw = cl = 0
                e["win_streak"] = max(e["win_streak"], cw)
                e["lose_streak"] = max(e["lose_streak"], cl)
    return ev


# ---------------------------------------------------------------- merge

def _profiles(through_season):
    td = _teams_data()
    ev = _rs_events(through_season)
    n = len(td)

    at = compute_alltime(through_season) or {"rows": []}
    arow = {r["owner"]: r for r in at["rows"]}
    pf_rank = {o: i for i, o in enumerate(
        sorted(td, key=lambda o: -td[o]["career_points"]), 1)}
    luck_rank = {r["owner"]: i for i, r in enumerate(
        sorted(at["rows"], key=lambda r: -r["luck"]), 1)}
    sched_rank = {r["owner"]: i for i, r in enumerate(
        sorted((r for r in at["rows"] if r["sched"] is not None),
               key=lambda r: -r["sched"]), 1)}

    def _rb(e, mk, fk):
        if not e or "opp" not in e:
            return None
        return {mk: round(e["m"], 1), fk: e["opp"], "week": e["week"], "year": e["year"]}

    out = {}
    for first, p in td.items():
        e = ev.get(first, {})
        r = arow.get(first, {})
        h2h = p["_h2h"]

        played = {k: v for k, v in h2h.items() if sum(v) >= 4}
        nemesis = owned = None
        if played:
            wo = min(played, key=lambda k: played[k][0] - played[k][1])
            if played[wo][1] > played[wo][0]:
                nemesis = {"opp": wo, "record": f'{played[wo][0]}-{played[wo][1]}'}
            bo = max(played, key=lambda k: played[k][0] - played[k][1])
            if played[bo][0] > played[bo][1]:
                owned = {"opp": bo, "record": f'{played[bo][0]}-{played[bo][1]}'}

        wins = [s for s in p["season_log"]]
        best_season = max(wins, key=lambda s: (int(s["record"].split("-")[0]), s["pf"]))
        worst_season = min(wins, key=lambda s: (int(s["record"].split("-")[0]), s["pf"]))
        names = []
        for s in p["season_log"]:
            if s["name"] and (not names or names[-1] != s["name"]):
                names.append(s["name"])

        prof = {
            "owner": first,
            "career_record": p["career_record"],
            "win_pct": p["win_pct"],
            "career_points": p["career_points"],
            "career_points_rank": pf_rank[first],
            "seasons_played": len(p["season_log"]),
            "season_log": p["season_log"],
            "best_season": best_season,
            "worst_season": worst_season,
            "team_names_history": names,
            "best_week_ever": p["best_week_ever"],
            "biggest_rival": p["biggest_rival"],
            "head_to_head_all_time": p["head_to_head"],
            "dominates": owned,
            "cant_beat": nemesis,
            "never_lost_to": sorted(k for k, v in h2h.items() if v[1] == 0 and v[0] >= 3),
            "never_beaten": sorted(k for k, v in h2h.items() if v[0] == 0 and v[1] >= 3),
        }
        if r:
            prof.update({
                "regular_season_expected_wins": r["xw"],
                "regular_season_actual_wins": r["aw"],
                "luck_wins": r["luck"],
                "luck_rank": luck_rank.get(first),
                "schedule_difficulty_rank": sched_rank.get(first),
            })
        if e:
            prof["regular_season_only"] = {
                "avg_points_per_week": round(e["points"] / e["games"], 1) if e["games"] else 0,
                "games": e["games"],
                "weekly_high_scorer_count": e["crowns"],
                "weekly_low_scorer_count": e["cellars"],
                "wins_by_40_plus": e["blowouts"],
                "losses_by_3_or_less": e["nailbiter_losses"],
                "longest_win_streak": e["win_streak"],
                "longest_losing_streak": e["lose_streak"],
                "low_scoring_week": e["worst"] if e["worst"]["pts"] < 1e9 else None,
                "biggest_win": _rb(e["big_win"] if e["big_win"]["m"] else None, "won_by", "beat"),
                "worst_loss": _rb(e["worst_loss"] if e["worst_loss"]["m"] else None, "lost_by", "lost_to"),
                "narrowest_win": _rb(e["narrow_win"] if e["narrow_win"]["m"] < 1e9 else None, "won_by", "beat"),
                "narrowest_loss": _rb(e["narrow_loss"] if e["narrow_loss"]["m"] < 1e9 else None, "lost_by", "lost_to"),
                "highest_score_in_a_loss": ({"points": e["high_loss"]["pts"], "lost_to": e["high_loss"]["opp"],
                                             "week": e["high_loss"]["week"], "year": e["high_loss"]["year"]}
                                            if e["high_loss"]["pts"] else None),
                "lowest_score_in_a_win": ({"points": e["low_win"]["pts"], "beat": e["low_win"]["opp"],
                                           "week": e["low_win"]["week"], "year": e["low_win"]["year"]}
                                          if e["low_win"]["pts"] < 1e9 else None),
                "finishes": e.get("finishes", []),
            }
        out[first] = prof
    return out, n


# ---------------------------------------------------------------- deterministic facts

def _wk(week, year):
    return f'Week {week}, {year}'


def _m(x):
    """margin -> readable string; never '0.0' for a real, decided game."""
    if x < 0.1:
        return "under a tenth of a point"
    return f'{x:.1f}'


def _computed_facts(p, n_owners):
    f = p["owner"]
    out = []
    rs = p.get("regular_season_only", {})

    out.append(f'{f} is {p["career_record"]} all-time — a {p["win_pct"]}% clip, '
               f'{_ord(p["career_points_rank"])} of {n_owners} in career points.')

    if "luck_wins" in p:
        lw = p["luck_wins"]
        if lw <= -2.5:
            out.append(f'{f}\'s scores say {p["regular_season_expected_wins"]:.0f} regular-season wins; '
                       f'he\'s got {p["regular_season_actual_wins"]:.0f}. The schedule owes him about {abs(lw):.0f}.')
        elif lw >= 2.5:
            out.append(f'{f} has banked {lw:.1f} wins his regular-season scoring didn\'t earn. '
                       f'The bracket gods like him.')

    bw = p["best_week_ever"]
    out.append(f'{f}\'s career high is {bw["points"]:.1f} points, {bw["when"]}.')

    # head-to-head (straight from the profile's own numbers)
    if p["cant_beat"]:
        nb = p["cant_beat"]
        out.append(f'{f} still can\'t solve {nb["opp"]}: {nb["record"]} against him all-time.')
    if p["dominates"]:
        dm = p["dominates"]
        out.append(f'{f} owns {dm["opp"]} — {dm["record"]} head-to-head and counting.')
    for v in p["never_lost_to"]:
        out.append(f'{f} has never lost to {v}. Not once.')
    for v in p["never_beaten"]:
        out.append(f'{f} has never beaten {v}. Some day.')

    riv = p["biggest_rival"]
    rw, rl = (int(x) for x in riv["record_vs_them"].split("-")[:2])
    if rw > rl:
        out.append(f'{f}\'s closest rivalry is {riv["owner"]} — he holds a {riv["record_vs_them"]} edge.')
    elif rw < rl:
        out.append(f'{f}\'s pet rivalry is {riv["owner"]}, who leads it {rl}-{rw}.')
    else:
        out.append(f'{f} and {riv["owner"]} are deadlocked {riv["record_vs_them"]} — the rivalry of record.')

    bs, wsn = p["best_season"], p["worst_season"]
    gap = int(bs["record"].split("-")[0]) - int(wsn["record"].split("-")[0])
    if bs["year"] != wsn["year"] and gap >= 4:
        out.append(f'{f}\'s range: {bs["record"]} in {bs["year"]}, {wsn["record"]} in {wsn["year"]}. Same guy.')

    names = p["team_names_history"]
    if len(names) >= 3:
        out.append(f'{f} has cycled through {len(names)} team names: '
                   + ", ".join(f'"{x}"' for x in names) + '.')
    elif len(names) == 1 and p["season_log"]:
        out.append(f'{f} has been "{names[0]}" since {p["season_log"][0]["year"]} — no notes, no changes.')

    # ---- regular-season-only colour ----
    if rs:
        if rs["weekly_high_scorer_count"]:
            out.append(f'{f} has been the top scorer in the league in {rs["weekly_high_scorer_count"]} '
                       f'different regular-season weeks.')
        if rs["weekly_low_scorer_count"] >= 3:
            out.append(f'{f} has also been the week\'s lowest scorer {rs["weekly_low_scorer_count"]} times. '
                       f'It evens out. Sort of.')
        if rs["low_scoring_week"]:
            lo = rs["low_scoring_week"]
            out.append(f'{f}\'s regular-season floor is {lo["pts"]:.1f} points, {_wk(lo["week"], lo["year"])}. It happens.')
        if rs["biggest_win"] and rs["biggest_win"]["won_by"] >= 30:
            b = rs["biggest_win"]
            out.append(f'{f} once buried {b["beat"]} by {b["won_by"]:.1f}, {_wk(b["week"], b["year"])}.')
        if rs["worst_loss"] and rs["worst_loss"]["lost_by"] >= 30:
            b = rs["worst_loss"]
            out.append(f'{f} once lost by {b["lost_by"]:.1f} to {b["lost_to"]}, {_wk(b["week"], b["year"])}. '
                       f'Just close the app.')
        if rs["narrowest_loss"] and rs["narrowest_loss"]["lost_by"] <= 1.5:
            b = rs["narrowest_loss"]
            out.append(f'{f} once lost to {b["lost_to"]} by {_m(b["lost_by"])}, {_wk(b["week"], b["year"])} '
                       f'— still stings.')
        if rs["narrowest_win"] and rs["narrowest_win"]["won_by"] <= 1.5:
            b = rs["narrowest_win"]
            out.append(f'{f} once squeaked past {b["beat"]} by {_m(b["won_by"])}, {_wk(b["week"], b["year"])}. '
                       f'A win\'s a win.')
        if rs["losses_by_3_or_less"] >= 2:
            out.append(f'{f} has lost {rs["losses_by_3_or_less"]} regular-season games by a field goal or less. '
                       f'Cruel hobby.')
        if rs["highest_score_in_a_loss"]:
            h = rs["highest_score_in_a_loss"]
            out.append(f'{f} once put up {h["points"]:.1f} and still lost, {_wk(h["week"], h["year"])}. '
                       f'Nothing he could do.')
        if rs["lowest_score_in_a_win"]:
            lw = rs["lowest_score_in_a_win"]
            out.append(f'{f} once won with just {lw["points"]:.1f} points, {_wk(lw["week"], lw["year"])}. Ugly, but a W.')
        if rs["longest_win_streak"] >= 4:
            out.append(f'{f}\'s hottest regular-season run is {rs["longest_win_streak"]} straight wins.')
        if rs["longest_losing_streak"] >= 4:
            out.append(f'{f} has also dropped {rs["longest_losing_streak"]} regular-season games in a row at his lowest.')
        firsts = sum(1 for _, pos in rs["finishes"] if pos == 1)
        lasts = sum(1 for _, pos in rs["finishes"] if pos == n_owners)
        if firsts:
            out.append(f'{f} has finished the regular season in first place {firsts} '
                       f'time{"s" if firsts > 1 else ""}.')
        if lasts:
            out.append(f'{f} has also finished dead last {lasts} time{"s" if lasts > 1 else ""}. '
                       f'Someone has to.')
        out.append(f'{f} averages {rs["avg_points_per_week"]:.1f} points a week over {rs["games"]} '
                   f'regular-season games.')

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
- Career record, head-to-head records, the season log, the rival and best_week_ever
  are all-time. Anything under "regular_season_only" is regular season ONLY — if you
  use it, say "regular season" (or "in the regular season").
- If you name a specific week, cite the exact "Week N, YYYY" that appears in the DATA.
- Never call a game a tie, push or draw. A tiny margin is still a win or loss exactly
  as the DATA labels it.
- Only put a NUMBER on a game's margin if that exact won_by / lost_by value is in the
  DATA. For a margin under 1 point, say "by a whisker" / "in a photo finish" — no number.
- No playoff, championship, draft, trade or NFL-player claims unless spelled out in
  the league background.
- Each fact is ONE sentence, standalone, names the owner, ~10-24 words. Add a little spin.

Output: exactly the requested number of facts, one per line, no numbering, no blank
lines, nothing else."""


def _nums(text):
    return {float(x) for x in re.findall(r'\d+\.?\d*', text.replace(",", ""))}


def _ai_facts(profile, want):
    allowed = _nums(json.dumps(profile)) | _nums(LEAGUE_FACTS) | set(range(0, 19))
    first = profile["owner"]

    wk_year_ok = set()

    def _scan(o):
        if isinstance(o, dict):
            if o.get("week") and o.get("year"):
                wk_year_ok.add((o["week"], o["year"]))
            for v in o.values():
                _scan(v)
        elif isinstance(o, list):
            for v in o:
                _scan(v)
    _scan(profile)
    m = re.search(r'Week (\d+), (\d{4})', profile["best_week_ever"]["when"])
    if m:
        wk_year_ok.add((int(m.group(1)), int(m.group(2))))

    def week_claims_ok(line):
        for mm in re.finditer(r'Week (\d{1,2})\b', line):
            wk = int(mm.group(1))
            yr = re.search(r'(20\d\d)', line[mm.end():mm.end() + 12])
            if not yr or (wk, int(yr.group(1))) not in wk_year_ok:
                return False
        return True

    ok_margins = {round(v, 1) for k in ("biggest_win", "worst_loss", "narrowest_win", "narrowest_loss")
                  for v in [(profile.get("regular_season_only") or {}).get(k)] if v
                  for v in [v.get("won_by", v.get("lost_by"))]}

    def margins_ok(line):
        for mm in re.finditer(r'\bby (\d{1,3}(?:\.\d+)?)', line):
            if line[mm.end():mm.end() + 6].lstrip().startswith(("plus", "+", "-plus")):
                continue
            v = float(mm.group(1))
            if v < 1:
                return False                       # never a numeric sub-point margin
            if (v <= 120) and round(v, 1) not in ok_margins:
                return False
        return True

    user = (
        f"League background:\n{LEAGUE_FACTS}\n\n"
        f"Owner: {first} ({profile.get('full_name', first)}).\n"
        f"Personality (already true, for tone): {NOTES.get(first, '')}\n\n"
        f"DATA (all verified):\n{json.dumps(profile, indent=2, default=str)}\n\n"
        f"Write {want} fun facts about {first}."
    )
    raw = ""
    for attempt in range(3):
        try:
            raw = claude(_SYS, user, max_tokens=600)
            break
        except (SystemExit, Exception) as ex:      # incl. socket.timeout, SSL, conn reset
            print(f"    AI call failed for {first} (try {attempt + 1}): {ex}")
    if not raw:
        print(f"    AI facts skipped for {first} — computed facts only")
        return []

    kept = []
    for line in raw.splitlines():
        line = line.strip().lstrip("-*0123456789. ").strip()
        if len(line) < 15:
            continue
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
        for full, short in OWNERS.items():
            line = line.replace(full, short)
        kept.append(line)
    return kept


# ---------------------------------------------------------------- render

def build(through_season):
    profiles, n = _profiles(through_season)
    pools = {}
    for first, full in FIRST_TO_FULL.items():
        p = profiles.get(first)
        if not p:
            continue
        computed = _computed_facts(p, n)
        try:
            ai = _ai_facts(p, AI_PER_TEAM)
        except Exception as ex:
            print(f"    AI facts errored for {first}: {ex}")
            ai = []
        print(f"  {first:<10} {len(computed)} computed + {len(ai)} AI")
        seen, pool = set(), []
        for fact in ai + computed:
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
