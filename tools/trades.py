"""Trade history + value-drift grading.

Built from ESPN's communication/activity feed, NOT the mTransactions2 view —
that view only returns a recent rolling window and splits each trade into
separate ACCEPT/UPHOLD procedural records with no item detail. Confirmed
2026-10-23 against the real league: the activity feed below returns full
season trade history in one call, each trade intact with every player that
moved.

Each ACTIVITY_TRANSACTIONS topic tagged messageTypeId=244 ("TRADED") is one
trade: its `messages` list has one entry per player moved, each carrying
`from`/`to` ESPN team ids and `targetId` (the ESPN player id).

Grading is value drift on FantasyPros ROS consensus rank (lower is better):
for each side, sum the ROS rank of players RECEIVED minus players GIVEN UP,
both at trade time and now. A side trending more negative has gained value
(its side of the deal looks better in hindsight); more positive means it's
lost value. "At trade time" uses the nearest `{season}-fp-ros-week-NN.json`
archive at or before the trade's week; before 2026-10-22 no archive exists,
so those trades fall back to the earliest archive available and are flagged
`approximate` rather than silently presented as exact.
"""
import datetime
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from lib import _get, espn, load_env
from lore import owner as canon
from sources import _espn_players

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TRADE_MSG_TYPE = 244


# ---------------------------------------------------------------- fetch

def _fetch_trade_topics(season):
    filt = {
        "topics": {
            "filterType": {"value": ["ACTIVITY_TRANSACTIONS"]},
            "limit": 200,
            "limitPerMessageSet": {"value": 25},
            "offset": 0,
            "sortMessageDate": {"sortPriority": 1, "sortAsc": False},
            "sortFor": {"sortPriority": 2, "sortAsc": False},
            "filterIncludeMessageTypeIds": {"value": [TRADE_MSG_TYPE]},
        }
    }
    url = (f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
           f"/segments/0/leagues/{_get('LEAGUE_ID')}/communication/"
           f"?view=kona_league_communication")
    req = urllib.request.Request(url, headers={
        "Cookie": f'espn_s2={_get("ESPN_S2")}; SWID={_get("ESPN_SWID")}',
        "User-Agent": "players-league/1.0",
        "Accept": "application/json",
        "x-fantasy-filter": json.dumps(filt),
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("topics", [])


def _team_owners(season):
    d = espn(["mTeam"], season)
    from league import _owner_name
    out = {}
    for t in d.get("teams", []):
        owners = t.get("owners") or []
        name = ((t.get("primaryOwner") and _owner_name(d, t["primaryOwner"]))
                 or (owners and _owner_name(d, owners[0])) or str(t["id"]))
        out[t["id"]] = canon(name)
    return out


def fetch_trades(season):
    """[{id, date (datetime, UTC), week, sides: {owner: [espn_player_id,...]}}],
    oldest first."""
    topics = _fetch_trade_topics(season)
    teams = _team_owners(season)
    trades = []
    for t in topics:
        msgs = [m for m in t.get("messages", []) if m.get("messageTypeId") == TRADE_MSG_TYPE]
        if not msgs:
            continue
        sides = {}
        for m in msgs:
            to_owner = teams.get(m.get("to"))
            pid = m.get("targetId")
            if to_owner and pid:
                sides.setdefault(to_owner, []).append(pid)
        if len(sides) < 2:
            continue
        trades.append({
            "id": t["id"],
            "date": datetime.datetime.fromtimestamp(t["date"] / 1000, tz=datetime.timezone.utc),
            "sides": sides,
        })
    trades.sort(key=lambda x: x["date"])
    return trades


# ---------------------------------------------------------------- grading

def _week_for_date(season, dt):
    """Approximate NFL week from a trade's calendar date. ESPN's league
    settings don't expose a direct "week 1 start date" field, so this
    approximates from the known 2026 Week 1 Thursday kickoff and 7-day
    scoring periods — good enough for archive lookups, which only need
    "which week's snapshot is closest," not an exact boundary."""
    week1_start = datetime.datetime(2026, 9, 10, tzinfo=datetime.timezone.utc)
    days = (dt - week1_start).days
    return max(1, days // 7 + 1)


def _load_ros_archives(season):
    """{week: {name_lower: {"rank":..., "pos":..., "pos_rank":...}}}, plus the
    live cache keyed as week 0 = "now"."""
    out = {}
    for f in sorted(os.listdir(DATA_DIR)):
        if f.startswith(f"{season}-fp-ros-week-") and f.endswith(".json"):
            week = int(f.rsplit("-", 1)[1].split(".")[0])
            data = json.loads(open(os.path.join(DATA_DIR, f)).read())
            out[week] = {p["name"].lower(): p for p in data.get("players", [])}
    live = os.path.join(DATA_DIR, "fantasypros-cache.json")
    if os.path.exists(live):
        data = json.loads(open(live).read())
        out["now"] = {p["name"].lower(): p for p in data.get("players", [])}
    return out


def _value_at(archives, week, name_lower):
    """ROS consensus_rank for a player at the closest available week <= week,
    plus whether that lookup was an approximation (no real archive for that
    week existed, so an earlier one was substituted)."""
    weeks = sorted(w for w in archives if w != "now")
    if not weeks:
        return None, True
    exact = week in archives and name_lower in archives[week]
    use_week = week if exact else max((w for w in weeks if w <= week), default=weeks[0])
    p = archives.get(use_week, {}).get(name_lower)
    return (p["consensus_rank"] if p else None), (use_week != week)


def grade_trades(season):
    load_env()
    trades = fetch_trades(season)
    espn_players = _espn_players(season)
    archives = _load_ros_archives(season)

    out = []
    for tr in trades:
        week = _week_for_date(season, tr["date"])
        sides = {}
        any_approx = False
        for owner, pids in tr["sides"].items():
            players = []
            val_then_sum, val_now_sum, n = 0.0, 0.0, 0
            for pid in pids:
                meta = espn_players.get(pid, {})
                name = meta.get("name", f"player {pid}")
                val_then, approx = _value_at(archives, week, name.lower())
                val_now, _ = _value_at(archives, "now", name.lower())
                if approx:
                    any_approx = True
                players.append({
                    "name": name, "pos": meta.get("pos"),
                    "value_then": val_then, "value_now": val_now,
                })
                if val_then is not None:
                    val_then_sum += val_then
                    n += 1
                if val_now is not None:
                    val_now_sum += val_now
            sides[owner] = {
                "players": players,
                "value_then": round(val_then_sum, 1) if n else None,
                "value_now": round(val_now_sum, 1) if n else None,
            }
        # drift: how much each side's *rank total* improved (negative = better,
        # lower rank = more valuable) relative to what they gave up — measured
        # as the swing in value_now - value_then for what they received, since
        # what they gave up is the other side's "received" by construction.
        for owner, s in sides.items():
            if s["value_then"] is not None and s["value_now"] is not None:
                s["drift"] = round(s["value_then"] - s["value_now"], 1)
            else:
                s["drift"] = None
        out.append({
            "id": tr["id"],
            "date": tr["date"].isoformat(),
            "week": week,
            "approximate": any_approx,
            "sides": sides,
        })
    return out


if __name__ == "__main__":
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    graded = grade_trades(season)
    print(f"{len(graded)} trades")
    for t in graded:
        print(f"\n{t['date'][:10]} (week {t['week']}){' [approx]' if t['approximate'] else ''}")
        for owner, s in t["sides"].items():
            names = ", ".join(p["name"] for p in s["players"])
            print(f"  {owner}: received {names} | then={s['value_then']} now={s['value_now']} drift={s['drift']}")
