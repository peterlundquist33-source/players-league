"""Beat the Board's weekly featured player — chosen once, frozen, then scored.

The board's one tiebreaker is "how many full-PPR points does THIS guy put up this
week". That only works if the guy is settled before anybody answers, so this
module is built around one rule:

    a week's featured player is written to tools/data/{season}-board-featured.json
    the first time it is asked for, and after that the record is never touched.

Selection, every part of which has to be true or the pick is not made:
  * genuinely high-scoring — drawn from the top of season-to-date full-PPR
    production, computed here from raw stats, not from a site's own point column
  * his NFL team has a real scheduled game that week (ESPN's cdn scoreboard)
  * his team is therefore not on bye — bye is exactly "absent from that week's
    scoreboard", so the two checks come off the same authoritative list
  * he is not Out / Doubtful / IR / PUP / suspended (Sleeper designation, via
    injuries.py) and Sleeper does not have him Inactive

Which of the eligible candidates gets picked is random but *seeded on
(season, week)*, so the same pool always yields the same man and a lost record
file would most likely rebuild to the same answer. The file, not the seed, is
the actual guarantee.

Scoring is full PPR, spelled out in PPR_RULES below rather than inherited from
anyone's league settings. Sleeper's own pts_ppr column differs from this on
quarterbacks only — it charges 1 point for an interception where full PPR charges
2 — so pts_ppr is used as a cross-check, never as the answer.

    python3 tools/featured.py            # show the open-ish week's pick + evidence
    python3 tools/featured.py 2026 11
    python3 tools/featured.py 2026 11 --pool    # the whole candidate pool

Stdlib only, like the rest of tools/.
"""
import datetime
import hashlib
import json
import sys
import urllib.request
from zoneinfo import ZoneInfo

from lib import ROOT

DATA = ROOT / "tools" / "data"
CT = ZoneInfo("America/Chicago")

SLEEPER_PLAYERS = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_STATS = "https://api.sleeper.app/v1/stats/nfl/regular/{season}"
SLEEPER_WEEK = "https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"

ROSTER_CACHE = DATA / "sleeper-roster.json"
ROSTER_MAX_AGE_H = 12

SKILL_POS = ("QB", "RB", "WR", "TE")
POOL_SIZE = 30              # candidates considered before eligibility filtering
MIN_GAMES = 4               # enough of a season to call someone high-scoring

# Sleeper designations that mean "do not feature this man". Questionable is not
# here: questionable players play, and the record keeps the tag so the page can
# say so.
HARD_OUT = {"out", "doubtful", "ir", "injured reserve", "pup",
            "sus", "suspended", "nfi", "dnr"}

ALL_TEAMS = {"ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
             "DET", "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA",
             "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
             "TEN", "WSH"}

# Full PPR, stated once, in the order the page prints it.
PPR_RULES = (
    ("rec", 1.0), ("rec_yd", 0.1), ("rec_td", 6.0),
    ("rush_yd", 0.1), ("rush_td", 6.0),
    ("pass_yd", 0.04), ("pass_td", 4.0), ("pass_int", -2.0),
    ("pass_2pt", 2.0), ("rush_2pt", 2.0), ("rec_2pt", 2.0),
    ("fum_lost", -2.0), ("fum_rec_td", 6.0),
)
PPR_LABEL = ("1 per catch, 0.1 per rushing/receiving yard, 6 per TD, "
             "0.04 per passing yard, 4 per passing TD, −2 per interception, "
             "−2 per fumble lost, 2 per two-point conversion")


def ppr(stats):
    """Full-PPR points for one player's stat line, computed term by term."""
    if not stats:
        return 0.0
    total = 0.0
    for key, weight in PPR_RULES:
        total += weight * float(stats.get(key) or 0.0)
    return round(total, 2)


def _get(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": "players-league/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ------------------------------------------------------------------- the roster

def roster(force=False):
    """{player_id: {name, pos, team, status, inj}} for skill-position players.

    Sleeper's player payload is ~14 MB; this keeps the few fields the board needs
    and caches them, the same way injuries.py caches its slice of the same feed.
    """
    import time
    if not force and ROSTER_CACHE.exists():
        try:
            blob = json.loads(ROSTER_CACHE.read_text())
            if time.time() - blob.get("fetched", 0) <= ROSTER_MAX_AGE_H * 3600:
                return blob["players"]
        except (ValueError, OSError, KeyError):
            pass
    try:
        raw = _get(SLEEPER_PLAYERS, timeout=120)
    except Exception as e:
        print(f"featured: Sleeper player fetch failed ({e})")
        if ROSTER_CACHE.exists():
            try:
                return json.loads(ROSTER_CACHE.read_text()).get("players") or {}
            except (ValueError, OSError):
                return {}
        return {}
    out = {}
    for pid, p in raw.items():
        pos, team, name = p.get("position"), p.get("team"), p.get("full_name")
        if pos not in SKILL_POS or not team or not name:
            continue
        out[pid] = {
            "name": name, "pos": pos, "team": team,
            "status": (p.get("status") or "").strip(),
            "inj": (p.get("injury_status") or "").strip(),
        }
    ROSTER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ROSTER_CACHE.write_text(
        json.dumps({"fetched": time.time(), "players": out}, indent=1) + "\n")
    return out


# ----------------------------------------------------------------- the schedule

def schedule(season, week):
    """({team: {opp, home, kickoff}}, bye_teams) for one NFL week, off ESPN.

    A bye is the complement of the week's scoreboard, so "has a game" and "isn't
    on bye" are the same fact read two ways — which is what they are.
    """
    import nfl as NF
    games = NF.games(season, week)
    byes = sorted(ALL_TEAMS - set(games)) if games else []
    return games, byes


def kickoff_label(raw):
    """ESPN's '2026-11-24 01:15' (UTC) -> 'Mon Nov 23, 7:15 PM CT'."""
    if not raw:
        return ""
    try:
        dt = datetime.datetime.strptime(raw.strip()[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return ""
    local = dt.replace(tzinfo=datetime.timezone.utc).astimezone(CT)
    fmt = "%a %b %-d, %-I:%M %p CT" if sys.platform != "win32" else "%a %b %d, %I:%M %p CT"
    return local.strftime(fmt)


# --------------------------------------------------------------------- the pool

def pool(season, week, size=POOL_SIZE, min_games=MIN_GAMES):
    """Ranked candidates for one week, each carrying why it is or isn't eligible.

    -> [{player_id, name, pos, team, season_ppr, ppg, games, rank,
         scheduled, bye, inj, status, eligible, why}]  (season_ppr descending)
    """
    meta = roster()
    if not meta:
        return []
    try:
        season_stats = _get(SLEEPER_STATS.format(season=season))
    except Exception as e:
        print(f"featured: Sleeper season stats failed ({e})")
        return []
    import injuries as INJ
    inj_table = INJ.load()
    games, byes = schedule(season, week)
    bye_set = set(byes)

    ranked = []
    for pid, st in season_stats.items():
        m = meta.get(pid)
        if not m:
            continue
        gp = float(st.get("gp") or 0)
        if gp < min_games:
            continue
        ranked.append((ppr(st), pid, m, gp, float(st.get("pts_ppr") or 0.0)))
    ranked.sort(key=lambda r: (-r[0], r[2]["name"]))

    out = []
    for i, (pts, pid, m, gp, sl_pts) in enumerate(ranked[:size], 1):
        team = m["team"]
        g = games.get(team) or {}
        # Sleeper's player record and injuries.py's table are the same feed read
        # two ways; take the worse of the two so a stale slice can't let an Out
        # player through.
        tag = m["inj"] or INJ.describe({"name": m["name"], "pos": m["pos"]}, inj_table).split(",")[0]
        why = []
        if not g:
            why.append("no scheduled game")
        if team in bye_set:
            why.append("on bye")
        if tag and tag.lower() in HARD_OUT:
            why.append(tag)
        if m["status"] and m["status"].lower() != "active":
            why.append(f'Sleeper {m["status"]}')
        out.append({
            "player_id": pid, "name": m["name"], "pos": m["pos"], "team": team,
            "season_ppr": pts, "sleeper_pts_ppr": round(sl_pts, 2),
            "games": int(gp), "ppg": round(pts / gp, 2) if gp else 0.0, "rank": i,
            "scheduled": bool(g), "bye": team in bye_set,
            "opp": g.get("opp", ""), "home": g.get("home"),
            "kickoff": g.get("kickoff", ""), "kickoff_label": kickoff_label(g.get("kickoff")),
            "inj": tag, "status": m["status"],
            "eligible": not why, "why": "; ".join(why),
        })
    return out


# ------------------------------------------------------------- frozen selection

def _path(season):
    return DATA / f"{season}-board-featured.json"


def records(season):
    p = _path(season)
    if not p.exists():
        return {}
    try:
        return {str(k): v for k, v in json.loads(p.read_text()).items()}
    except (ValueError, OSError):
        return {}


def _write(season, recs):
    _path(season).parent.mkdir(parents=True, exist_ok=True)
    _path(season).write_text(
        json.dumps({k: recs[k] for k in sorted(recs, key=int)}, indent=1) + "\n")


def seed_index(season, week, n):
    """Deterministic index into an n-long list, seeded on (season, week) only."""
    if n <= 0:
        return 0
    digest = hashlib.sha256(f"{season}-{week}".encode()).hexdigest()
    return int(digest, 16) % n


def for_week(season, week, allow_pick=True):
    """The frozen record for one week, picking (and persisting) it if there isn't
    one yet. An existing record is returned untouched — that immutability is the
    whole point, because people answer against the name on the page."""
    recs = records(season)
    key = str(week)
    if key in recs:
        return recs[key]
    if not allow_pick:
        return None

    cands = [c for c in pool(season, week) if c["eligible"]]
    if not cands:
        print(f"featured: no eligible candidate for {season} week {week} — not picking")
        return None
    chosen = cands[seed_index(season, week, len(cands))]
    rec = {
        "season": season, "week": int(week),
        "player_id": chosen["player_id"], "name": chosen["name"],
        "pos": chosen["pos"], "team": chosen["team"],
        "opp": chosen["opp"], "home": chosen["home"],
        "kickoff": chosen["kickoff"], "kickoff_label": chosen["kickoff_label"],
        "chosen_at": datetime.datetime.now(datetime.timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seed": f"{season}-{week}", "pool_rank": chosen["rank"],
        "eligible_pool": len(cands),
        "season_ppr": chosen["season_ppr"], "ppg": chosen["ppg"],
        "games": chosen["games"],
        "evidence": {
            "scheduled_game": True, "on_bye": False,
            "injury_tag": chosen["inj"], "sleeper_status": chosen["status"],
        },
        "actual": None, "played": None, "final": False,
    }
    recs[key] = rec
    _write(season, recs)
    return rec


# ------------------------------------------------------------------ the outcome

def outcome(season, week, rec):
    """What the featured player actually did. -> {points, played, line, void}

    `played` is None while the week is still ahead of us; False means he was on
    the page and never took a snap, which voids the bonus for everyone.
    """
    if not rec:
        return {"points": None, "played": None, "line": {}, "void": False}
    try:
        stats = _get(SLEEPER_WEEK.format(season=season, week=week)) or {}
    except Exception as e:
        print(f"featured: Sleeper week {week} stats failed ({e})")
        return {"points": rec.get("actual"), "played": rec.get("played"),
                "line": {}, "void": rec.get("played") is False}
    line = stats.get(rec["player_id"]) or {}
    if not line:
        return {"points": None, "played": None, "line": {}, "void": False}
    snaps = line.get("off_snp")
    played = bool(float(line.get("gp") or 0) >= 1 and
                  (snaps is None or float(snaps) > 0))
    pts = ppr(line) if played else 0.0
    return {"points": pts, "played": played, "line": line, "void": not played}


def settle(season, week, rec, result, final):
    """Freeze the outcome into the record once the fantasy week is final, so a
    later rebuild without network still shows the same number."""
    if not rec or not final or rec.get("final"):
        return rec
    if result.get("played") is None:
        return rec
    recs = records(season)
    key = str(week)
    if key not in recs:
        return rec
    recs[key]["actual"] = result["points"]
    recs[key]["played"] = result["played"]
    recs[key]["final"] = True
    _write(season, recs)
    return recs[key]


# ------------------------------------------------------------------------ main

def main(argv=None):
    a = list(argv if argv is not None else sys.argv[1:])
    show_pool = "--pool" in a
    a = [x for x in a if not x.startswith("--")]
    season = int(a[0]) if a else 2026
    week = int(a[1]) if len(a) > 1 else 1

    games, byes = schedule(season, week)
    print(f"{season} week {week}: {len(games)} teams scheduled, bye {', '.join(byes) or 'none'}")
    if show_pool:
        for c in pool(season, week):
            flag = "OK " if c["eligible"] else "x  "
            print(f'{flag}{c["rank"]:>2}. {c["season_ppr"]:>7.2f} {c["name"]:<24}'
                  f'{c["pos"]:<3}{c["team"]:<4} {c["why"] or c["kickoff_label"]}')
        print()
    rec = for_week(season, week)
    if not rec:
        print("no featured player")
        return
    print(f'featured: {rec["name"]} ({rec["pos"]}, {rec["team"]}) '
          f'{"vs" if rec["home"] else "at"} {rec["opp"]} — {rec["kickoff_label"]}')
    print(f'  season {rec["season_ppr"]} PPR over {rec["games"]} games ({rec["ppg"]}/gm), '
          f'pool rank {rec["pool_rank"]} of {rec["eligible_pool"]} eligible, seed {rec["seed"]}')
    print(f'  evidence: {rec["evidence"]}')
    res = outcome(season, week, rec)
    print(f'  outcome: {res["points"]} PPR, played={res["played"]}')


if __name__ == "__main__":
    main()
