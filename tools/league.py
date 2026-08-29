"""Normalize the ESPN league payload into a clean shape the renderer + AI use."""
from lib import espn, POS, SLOT, PRO
from lore import owner

STARTER_SLOTS = set(SLOT) - {20, 21}  # everything except BE / IR


def _proj_and_actual(entry, scoring_period):
    """Return (projected, actual) points for one roster entry this scoring period."""
    proj = actual = 0.0
    p = entry.get("playerPoolEntry", {}).get("player", {})
    for s in p.get("stats", []):
        if s.get("scoringPeriodId") != scoring_period:
            continue
        if s.get("statSourceId") == 0:      # real
            actual = s.get("appliedTotal", 0.0) or 0.0
        elif s.get("statSourceId") == 1:    # projected
            proj = s.get("appliedTotal", 0.0) or 0.0
    return round(proj, 1), round(actual, 1)


def _side(raw_side, teams, scoring_period):
    tid = raw_side["teamId"]
    t = teams[tid]
    roster = (raw_side.get("rosterForCurrentScoringPeriod")
              or raw_side.get("rosterForMatchupPeriod") or {})
    starters = []
    proj_total = 0.0
    for e in roster.get("entries", []):
        slot = e.get("lineupSlotId")
        if slot not in STARTER_SLOTS:
            continue
        pl = e.get("playerPoolEntry", {}).get("player", {})
        proj, act = _proj_and_actual(e, scoring_period)
        proj_total += proj
        starters.append({
            "name": pl.get("fullName", "?"),
            "slot": SLOT.get(slot, str(slot)),
            "pos": POS.get(pl.get("defaultPositionId"), "?"),
            "pro": PRO.get(pl.get("proTeamId"), "?"),
            "proj": proj, "actual": act,
        })
    return {
        "teamId": tid,
        "team": t["name"],
        "owner": owner(t["owner"]),
        "owner_full": t["owner"],
        "record": t["record"],
        "actual": round(raw_side.get("totalPoints", 0.0), 1),
        "projected": round(raw_side.get("totalProjectedPointsLive")
                           or proj_total, 1),
        "starters": starters,
    }


def build(season, week=None, phase=None):
    d = espn(["mTeam", "mSettings", "mMatchupScore", "mRoster", "mScoreboard"], season)

    status = d.get("status", {})
    cur_week = status.get("currentMatchupPeriod", 1)
    latest_sp = status.get("latestScoringPeriod", 1)
    week = week or cur_week

    teams = {}
    for t in d.get("teams", []):
        name = (t.get("name") or f'{t.get("location","")} {t.get("nickname","")}').strip()
        rec = t.get("record", {}).get("overall", {})
        owners = t.get("owners") or []
        teams[t["id"]] = {
            "name": name,
            "owner": (t.get("primaryOwner") and _owner_name(d, t["primaryOwner"]))
                     or (owners and _owner_name(d, owners[0])) or name,
            "record": f'{rec.get("wins",0)}-{rec.get("losses",0)}'
                      + (f'-{rec["ties"]}' if rec.get("ties") else ""),
            "pf": round(rec.get("pointsFor", 0.0), 1),
            "pa": round(rec.get("pointsAgainst", 0.0), 1),
            "streak": _streak(rec),
        }

    games = [s for s in d.get("schedule", []) if s.get("matchupPeriodId") == week]
    scoring_period = week  # regular season: 1:1 with matchup period

    matchups = []
    for s in games:
        if "home" not in s or "away" not in s:
            continue
        h = _side(s["home"], teams, scoring_period)
        a = _side(s["away"], teams, scoring_period)
        played = (h["actual"] > 0 or a["actual"] > 0)
        matchups.append({
            "home": h, "away": a,
            "played": played,
            "margin": round(abs(h["actual"] - a["actual"]), 1) if played else None,
            "winner": (h["owner"] if h["actual"] > a["actual"] else a["owner"]) if played else None,
        })

    if phase is None:
        phase = "recap" if (matchups and all(m["played"] for m in matchups)) else "preview"

    return {
        "season": season,
        "week": week,
        "phase": phase,
        "current_week": cur_week,
        "latest_scoring_period": latest_sp,
        "standings": sorted(teams.values(), key=lambda t: (-_wins(t["record"]), -t["pf"])),
        "matchups": matchups,
    }


def _owner_name(d, guid):
    for m in d.get("members", []):
        if m.get("id") == guid:
            fn = (m.get("firstName") or "").strip()
            ln = (m.get("lastName") or "").strip()
            return f"{fn} {ln}".strip() or m.get("displayName", guid)
    return guid


def _wins(rec):
    try:
        return int(rec.split("-")[0])
    except Exception:
        return 0


def _streak(rec):
    t = rec.get("streakType")
    n = rec.get("streakLength", 0)
    if not t or not n:
        return ""
    return f'{"W" if t == "WIN" else "L"}{n}'


if __name__ == "__main__":
    import sys, json
    from lib import load_env
    load_env()
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    week = int(sys.argv[2]) if len(sys.argv) > 2 else None
    print(json.dumps(build(season, week), indent=2)[:6000])
