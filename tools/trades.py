"""Trade history + current-value grading, Chabels-Dynasty style.

Built from ESPN's communication/activity feed, NOT the mTransactions2 view —
that view only returns a recent rolling window and splits each trade into
separate ACCEPT/UPHOLD procedural records with no item detail. Confirmed
2026-10-23 against the real league: the activity feed below returns full
season trade history in one call, each trade intact with every player that
moved.

Each ACTIVITY_TRANSACTIONS topic tagged messageTypeId=244 ("TRADED") is one
trade: its `messages` list has one entry per player moved, each carrying
`from`/`to` ESPN team ids and `targetId` (the ESPN player id).

Grading compares each side's players by CURRENT FantasyPros ROS rank only —
no trade-time snapshot, no drift-over-time, matching
chabels-dynasty/js/trades-engine.js's model: rank is run through a steep
decay curve (a WR1 is worth vastly more than a WR40, which a flat rank sum
would understate), summed per side, and the side with the higher total
value wins. Because it only ever reads the live cache, the verdict updates
on its own every week as rankings move — no historical archive needed.
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

# (abs value diff, label) — same tiers and feel as chabels-dynasty's grader
GRADE_TIERS = [
    (5, "EVEN"),
    (15, "SLIGHT EDGE"),
    (35, "CLEAR WIN"),
    (60, "ROBBERY"),
]


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

def _load_live_ros(season):
    """{name_lower: consensus_rank} from the live FantasyPros ROS cache."""
    live = os.path.join(DATA_DIR, "fantasypros-cache.json")
    if not os.path.exists(live):
        return {}
    data = json.loads(open(live).read())
    return {p["name"].lower(): p["consensus_rank"] for p in data.get("players", [])}


def rank_to_value(rank):
    """ROS rank -> trade value on a steep decay curve — same shape as
    chabels-dynasty's dynastyRankToTradeValue, so a true WR1 dwarfs a
    flex-replacement-level player instead of differing by a flat ~1 point
    the way raw rank would."""
    if not rank or rank > 450:
        return 0.5
    if rank <= 5:
        return 120 - (rank - 1) * 8        # 120 -> 88
    if rank <= 15:
        return 85 - (rank - 5) * 4         # 85 -> 45
    if rank <= 30:
        return 45 - (rank - 15) * 1.5      # 45 -> 22.5
    if rank <= 60:
        return 22.5 - (rank - 30) * 0.4    # 22.5 -> 10.5
    if rank <= 100:
        return 10.5 - (rank - 60) * 0.15   # 10.5 -> 4.5
    if rank <= 150:
        return 4.5 - (rank - 100) * 0.05   # 4.5 -> 2
    if rank <= 250:
        return 2 - (rank - 150) * 0.01     # 2 -> 1
    return 0.5


def _grade(abs_diff):
    for cutoff, label in GRADE_TIERS:
        if abs_diff < cutoff:
            return label
    return "HEIST"


def grade_trades(season):
    load_env()
    trades = fetch_trades(season)
    espn_players = _espn_players(season)
    ros = _load_live_ros(season)

    out = []
    for tr in trades:
        sides = {}
        for owner, pids in tr["sides"].items():
            players = []
            total = 0.0
            for pid in pids:
                meta = espn_players.get(pid, {})
                name = meta.get("name", f"player {pid}")
                rank = ros.get(name.lower())
                value = rank_to_value(rank)
                players.append({"name": name, "pos": meta.get("pos"),
                                 "rank": rank, "value": round(value, 1)})
                total += value
            sides[owner] = {"players": players, "value": round(total, 1)}

        owners = list(sides.keys())
        diff = round(sides[owners[0]]["value"] - sides[owners[1]]["value"], 1) if len(owners) == 2 else 0.0
        abs_diff = abs(diff)
        winner = None
        if len(owners) == 2 and abs_diff >= GRADE_TIERS[0][0]:
            winner = owners[0] if diff > 0 else owners[1]

        out.append({
            "id": tr["id"],
            "date": tr["date"].isoformat(),
            "sides": sides,
            "winner": winner,
            "margin": round(abs_diff, 1),
            "grade": _grade(abs_diff),
        })
    return out


if __name__ == "__main__":
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    graded = grade_trades(season)
    print(f"{len(graded)} trades")
    for t in graded:
        print(f"\n{t['date'][:10]} [{t['grade']}] winner={t['winner'] or 'EVEN'} (+{t['margin']})")
        for owner, s in t["sides"].items():
            names = ", ".join(f"{p['name']} ({p['value']})" for p in s["players"])
            print(f"  {owner}: received {names} | total={s['value']}")
