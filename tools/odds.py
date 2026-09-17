"""Playoff & Dress odds — Monte Carlo the rest of the regular season.

Inputs: the season schedule (played + unplayed) from ESPN, and each team's strength
(recent scoring blended with the power model's roster projection). Every remaining
game is simulated by drawing each team's score from a normal distribution; the
season is then seeded with the league's rules: 7 playoff teams, #1 seed gets the
bye, tiebreakers = record then points for. Last place = the Dress.

    python3 tools/main.py odds [--week N]        # runs after the Tuesday recap
"""
import json, math, random, statistics
from lib import espn, load_env, ROOT
from lore import owner

DATA = ROOT / "tools" / "data"
PLAYOFF_TEAMS = 7
BYES = 1
SIMS = 10000
PRIOR_GAMES = 4          # how many "games" of roster projection to blend with real scoring
LEAGUE_SD = 22.0         # typical week-to-week spread of a team's score, early-season default
SD_BLEND_GAMES = 6       # after this many games a team's own spread gets full weight


# ---------------------------------------------------------------- schedule

def pull_schedule(season):
    """All regular-season games: [{week, home, away, hp, ap, played}] keyed by owner."""
    d = espn(["mMatchupScore", "mTeam", "mSettings"], season)
    mpc = d.get("settings", {}).get("scheduleSettings", {}).get("matchupPeriodCount", 14)
    mem = {m["id"]: owner(f'{m.get("firstName","")} {m.get("lastName","")}') for m in d.get("members", [])}
    tmap, tname = {}, {}
    for t in d.get("teams", []):
        o = mem.get(t.get("primaryOwner")) or mem.get((t.get("owners") or [None])[0])
        if o:
            tmap[t["id"]] = o
            tname[o] = (t.get("name") or "").strip()
    games = []
    for s in d.get("schedule", []):
        if s.get("matchupPeriodId", 99) > mpc or s.get("playoffTierType") not in (None, "NONE"):
            continue
        h, a = s.get("home"), s.get("away")
        if not h or not a:
            continue
        ho, ao = tmap.get(h["teamId"]), tmap.get(a["teamId"])
        if not ho or not ao:
            continue
        hp, ap = round(h.get("totalPoints", 0.0) or 0.0, 2), round(a.get("totalPoints", 0.0) or 0.0, 2)
        games.append({"week": s["matchupPeriodId"], "home": ho, "away": ao,
                      "hp": hp, "ap": ap, "played": bool(hp or ap)})
    return {"season": season, "games": games, "owners": sorted(tname), "tname": tname, "weeks": mpc}


# ---------------------------------------------------------------- strength

def strengths(sched, board=None):
    """{owner: (mean, sd)} from real scoring blended with the power board's projection."""
    scores = {o: [] for o in sched["owners"]}
    for g in sched["games"]:
        if g["played"]:
            scores[g["home"]].append(g["hp"]); scores[g["away"]].append(g["ap"])
    proj = {}
    if board:
        for r in board.get("rows", []):
            proj[r["owner"]] = r.get("proj_avg") or r.get("proj_next") or None
    league_avg = statistics.mean([s for v in scores.values() for s in v]) if any(scores.values()) else 115.0
    out = {}
    for o in sched["owners"]:
        n = len(scores[o])
        prior = proj.get(o) or league_avg
        mean = (sum(scores[o]) + PRIOR_GAMES * prior) / (n + PRIOR_GAMES)
        own_sd = statistics.pstdev(scores[o]) if n >= 2 else LEAGUE_SD
        w = min(1.0, n / SD_BLEND_GAMES)
        sd = w * own_sd + (1 - w) * LEAGUE_SD
        out[o] = (mean, max(sd, 12.0))
    return out


# ---------------------------------------------------------------- simulation

def _standings(wins, pf, owners):
    return sorted(owners, key=lambda o: (-wins[o], -pf[o]))


def simulate(sched, strength, sims=SIMS, seed=None):
    rng = random.Random(seed)
    owners = sched["owners"]
    base_w = {o: 0.0 for o in owners}
    base_pf = {o: 0.0 for o in owners}
    for g in sched["games"]:
        if g["played"]:
            base_pf[g["home"]] += g["hp"]; base_pf[g["away"]] += g["ap"]
            if g["hp"] > g["ap"]: base_w[g["home"]] += 1
            elif g["ap"] > g["hp"]: base_w[g["away"]] += 1
            else: base_w[g["home"]] += 0.5; base_w[g["away"]] += 0.5
    todo = [g for g in sched["games"] if not g["played"]]
    next_week = min((g["week"] for g in todo), default=None)
    next_games = [g for g in todo if g["week"] == next_week]

    tally = {o: {"playoff": 0, "bye": 0, "one": 0, "dress": 0, "wins": 0.0, "seed": [0] * len(owners)} for o in owners}
    # leverage: for each next-week game, outcomes conditioned on who wins it
    lev = {i: {"home_win": {"n": 0, "dress": {o: 0 for o in owners}, "playoff": {o: 0 for o in owners}},
               "away_win": {"n": 0, "dress": {o: 0 for o in owners}, "playoff": {o: 0 for o in owners}}}
           for i in range(len(next_games))}

    for _ in range(sims):
        w = dict(base_w); pf = dict(base_pf)
        first = {}
        for i, g in enumerate(todo):
            hs = rng.gauss(*strength[g["home"]]); as_ = rng.gauss(*strength[g["away"]])
            pf[g["home"]] += hs; pf[g["away"]] += as_
            if hs > as_: w[g["home"]] += 1
            else: w[g["away"]] += 1
            if g["week"] == next_week:
                first[i] = "home_win" if hs > as_ else "away_win"
        order = _standings(w, pf, owners)
        for seed_i, o in enumerate(order):
            t = tally[o]
            t["wins"] += w[o]; t["seed"][seed_i] += 1
            if seed_i < PLAYOFF_TEAMS: t["playoff"] += 1
            if seed_i < BYES: t["bye"] += 1
            if seed_i == 0: t["one"] += 1
        dress = order[-1]
        tally[dress]["dress"] += 1
        made = set(order[:PLAYOFF_TEAMS])
        for i, res in first.items():
            j = next_games.index(todo[i])
            L = lev[j][res]; L["n"] += 1
            L["dress"][dress] += 1
            for o in made: L["playoff"][o] += 1

    rows = []
    for o in owners:
        t = tally[o]
        rows.append({"owner": o, "team": sched["tname"].get(o, o),
                     "record": _rec(sched, o), "pf": round(base_pf[o], 1),
                     "playoff": round(100 * t["playoff"] / sims, 1), "bye": round(100 * t["bye"] / sims, 1),
                     "one": round(100 * t["one"] / sims, 1), "dress": round(100 * t["dress"] / sims, 1),
                     "avg_wins": round(t["wins"] / sims, 1),
                     "mean": round(strength[o][0], 1), "sd": round(strength[o][1], 1)})
    rows.sort(key=lambda r: (-r["playoff"], -r["avg_wins"], r["dress"]))

    leverage = []
    for j, g in enumerate(next_games):
        L = lev[j]
        def pct(side, key, o):
            n = L[side]["n"]; return round(100 * L[side][key][o] / n, 1) if n else None
        leverage.append({"week": next_week, "home": g["home"], "away": g["away"],
                         "home_team": sched["tname"].get(g["home"]), "away_team": sched["tname"].get(g["away"]),
                         "home": g["home"], "away": g["away"],
                         "sides": {
                             g["home"]: {"win": {"dress": pct("home_win", "dress", g["home"]), "playoff": pct("home_win", "playoff", g["home"])},
                                         "lose": {"dress": pct("away_win", "dress", g["home"]), "playoff": pct("away_win", "playoff", g["home"])}},
                             g["away"]: {"win": {"dress": pct("away_win", "dress", g["away"]), "playoff": pct("away_win", "playoff", g["away"])},
                                         "lose": {"dress": pct("home_win", "dress", g["away"]), "playoff": pct("home_win", "playoff", g["away"])}}}})
    played_weeks = sorted({g["week"] for g in sched["games"] if g["played"]})
    return {"season": sched["season"], "week": played_weeks[-1] if played_weeks else 0,
            "next_week": next_week, "games_left": len(todo), "sims": sims,
            "rows": rows, "leverage": leverage}


def _rec(sched, o):
    w = l = 0
    for g in sched["games"]:
        if not g["played"]: continue
        if o == g["home"]: w += g["hp"] > g["ap"]; l += g["hp"] < g["ap"]
        elif o == g["away"]: w += g["ap"] > g["hp"]; l += g["ap"] < g["hp"]
    return f"{w}-{l}"


# ---------------------------------------------------------------- entry points

def history(season):
    """Every saved weekly odds file, oldest first — feeds the Dress Watch trend."""
    out = []
    for f in sorted(DATA.glob(f"{season}-odds-week-*.json")):
        try: out.append(json.loads(f.read_text()))
        except Exception: pass
    return out


def run(season, board=None, sims=SIMS):
    load_env()
    sched = pull_schedule(season)
    st = strengths(sched, board)
    res = simulate(sched, st, sims=sims)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f'{season}-odds-week-{res["week"]:02d}.json').write_text(json.dumps(res, indent=1))
    return res
