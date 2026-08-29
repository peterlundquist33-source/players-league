"""Blend free ranking sources into one consensus per player.

Sources (all free, no auth):
  ESPN        — averageDraftPosition (ADP) + PPR expert rank, from the league API
  FantasyPros — expert consensus rank (ECR), ~100+ analysts
  FantasyCalc — redraft trade value  -> implied rank
  Sleeper     — search_rank (preseason consensus proxy)

Join key: normalized "first last" + position. FantasyCalc's espnId is a backstop.
"""
import json, re, urllib.request
from lib import espn

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)
_NONWORD = re.compile(r"[^a-z0-9 ]")


def norm(name):
    n = (name or "").lower().replace(".", "").replace("'", "")
    n = _SUFFIX.sub("", n)
    n = _NONWORD.sub("", n).strip()
    n = re.sub(r"\s+", " ", n)
    return n


def _get_json(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": "players-league/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------------------------------------------------------------- ESPN

def _espn_players(season, count=320):
    """Top `count` players by PPR draft rank, with ADP."""
    hdr_filter = json.dumps({"players": {
        "limit": count,
        "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": "PPR"},
    }})
    import urllib.request as u
    league = espn.__wrapped__ if hasattr(espn, "__wrapped__") else None  # noqa
    # espn() doesn't take a custom header; do the request inline
    from lib import _get
    url = (f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
           f"/segments/0/leagues/{_get('LEAGUE_ID')}?view=kona_player_info")
    req = u.Request(url, headers={
        "Cookie": f'espn_s2={_get("ESPN_S2")}; SWID={_get("ESPN_SWID")}',
        "User-Agent": "players-league/1.0",
        "X-Fantasy-Filter": hdr_filter,
        "Accept": "application/json",
    })
    with u.urlopen(req, timeout=45) as r:
        d = json.load(r)
    out = {}
    for row in d.get("players", []):
        p = row.get("player", row)
        adp = (p.get("ownership") or {}).get("averageDraftPosition") or 0
        rk = (p.get("draftRanksByRankType") or {}).get("PPR", {}).get("rank")
        out[p["id"]] = {
            "name": p.get("fullName", ""),
            "key": norm(p.get("fullName", "")),
            "pos": {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}.get(p.get("defaultPositionId")),
            "espn_adp": adp if adp and adp < 400 else None,
            "espn_rank": rk,
        }
    return out


# ---------------------------------------------------------------- FantasyCalc

def _fantasycalc():
    r = _get_json("https://api.fantasycalc.com/values/current"
                  "?isDynasty=false&numQbs=1&numTeams=12&ppr=1")
    out = {}
    for i, e in enumerate(r, 1):
        pl = e["player"]
        out[(norm(pl["name"]), pl.get("position"))] = {
            "rank": i, "value": e.get("redraftValue") or e.get("value"),
            "espnId": str(pl.get("espnId") or "")}
    return out


# ---------------------------------------------------------------- FantasyPros

def _fantasypros(season):
    url = ("https://partners.fantasypros.com/api/v1/consensus-rankings.php"
           f"?sport=NFL&year={season}&week=0&position=ALL&scoring=PPR&type=draft")
    d = _get_json(url, timeout=25)
    out = {}
    for p in d.get("players", []):
        out[(norm(p.get("player_name")), p.get("player_position_id"))] = p.get("rank_ecr")
    return out


# ---------------------------------------------------------------- Sleeper

def _sleeper():
    s = _get_json("https://api.sleeper.app/v1/players/nfl")
    rows = []
    for v in s.values():
        sr = v.get("search_rank")
        if not sr or sr > 900000 or not v.get("full_name"):
            continue
        rows.append((sr, v))
    rows.sort(key=lambda x: x[0])
    out = {}
    for i, (_, v) in enumerate(rows, 1):
        for pos in (v.get("fantasy_positions") or [None]):
            out.setdefault((norm(v["full_name"]), pos), i)   # keep best (first) rank
    return out


# ---------------------------------------------------------------- blend

def consensus(season):
    """{espn_player_id: {name, pos, adp, ranks{}, consensus_rank}}"""
    espn_p = _espn_players(season)
    fc = _fantasycalc()
    sl = _sleeper()
    fp = _fantasypros(season)
    fc_by_espnid = {v["espnId"]: v for v in fc.values() if v["espnId"]}

    out = {}
    for pid, e in espn_p.items():
        k, pos = e["key"], e["pos"]
        f = fc_by_espnid.get(str(pid)) or fc.get((k, pos)) or fc.get((k, None))
        s_rank = sl.get((k, pos)) or sl.get((k, None))
        fp_rank = fp.get((k, pos)) or fp.get((k, None))
        ranks = {}
        if e["espn_rank"]:
            ranks["espn"] = e["espn_rank"]
        if e["espn_adp"]:
            ranks["adp"] = e["espn_adp"]
        if fp_rank:
            ranks["fantasypros"] = fp_rank
        if f:
            ranks["fantasycalc"] = f["rank"]
        if s_rank:
            ranks["sleeper"] = s_rank
        cons = round(sum(ranks.values()) / len(ranks), 1) if ranks else None
        out[pid] = {"name": e["name"], "pos": e["pos"], "adp": e["espn_adp"],
                    "ranks": ranks, "consensus_rank": cons, "sources": len(ranks)}
    return out


if __name__ == "__main__":
    from lib import load_env
    load_env()
    c = consensus(2026)
    have = [v for v in c.values() if v["consensus_rank"]]
    have.sort(key=lambda v: v["consensus_rank"])
    print(f"{len(c)} espn players, {len(have)} with a consensus rank")
    for v in have[:15]:
        print(f'  {v["consensus_rank"]:6.1f}  {v["name"]:<22} {v["pos"]:<4} '
              f'{v["sources"]} src  {v["ranks"]}')
