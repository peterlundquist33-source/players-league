"""Real NFL game context for a given week — matchups, spreads, totals, kickoff.

Source: ESPN's public scoreboard API. No auth, no key, same numbers the app shows.
Used to give previews something concrete to say about the games the fantasy points
actually come from ("Bijan's in a 49.5-point game, Jefferson's team is a 7-point dog").

Everything here degrades quietly: if the API is down or the odds aren't posted yet,
the fact block just doesn't get these lines.
"""
import json, urllib.request, urllib.error

# NOTE: site.api.espn.com returns 403 "Access Denied" to this client — use the
# cdn.espn.com scoreboard the website itself calls. It carries the same events
# plus the betting lines for upcoming games.
URL = ("https://cdn.espn.com/core/nfl/scoreboard"
       "?xhr=1&seasontype=2&week={week}&year={season}")

# ESPN's fantasy abbreviations vs the scoreboard's — mostly identical, these differ
ALIAS = {"WSH": "WSH", "JAX": "JAX", "LAR": "LAR", "LAC": "LAC", "LV": "LV"}


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def games(season, week):
    """-> {TEAM_ABBR: {opp, home, spread, total, kickoff}}  (empty on failure).

    `spread` is from that team's point of view: negative = favored.
    """
    try:
        d = _get(URL.format(week=week, season=season))
        events = d["content"]["sbData"]["events"]
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError,
            KeyError, TypeError):
        return {}

    out = {}
    for ev in events:
        for comp in ev.get("competitions", []):
            teams = comp.get("competitors", [])
            if len(teams) != 2:
                continue
            home = next((t for t in teams if t.get("homeAway") == "home"), None)
            away = next((t for t in teams if t.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            ha = (home.get("team") or {}).get("abbreviation")
            aa = (away.get("team") or {}).get("abbreviation")
            if not ha or not aa:
                continue

            total = spread_home = None
            odds = comp.get("odds") or []
            if odds:
                o = odds[0]
                total = o.get("overUnder")
                # `spread` is quoted for the home team: negative = home favored
                spread_home = o.get("spread")
                if spread_home is None:
                    d_ = (o.get("details") or "").split()
                    if len(d_) == 2:
                        try:
                            val = float(d_[1])
                            spread_home = val if d_[0] == ha else -val
                        except ValueError:
                            pass
            kick = (ev.get("date") or "")[:16].replace("T", " ")

            for abbr, opp, is_home in ((ha, aa, True), (aa, ha, False)):
                sp = None
                if spread_home is not None:
                    sp = spread_home if is_home else -spread_home
                out[ALIAS.get(abbr, abbr)] = {
                    "opp": ALIAS.get(opp, opp),
                    "home": is_home,
                    "spread": sp,               # negative = this team favored
                    "total": total,
                    "kickoff": kick,
                }
    return out


def describe(abbr, g):
    """One short clause about a team's real NFL game, or '' if we know nothing."""
    if not g:
        return ""
    where = "vs" if g["home"] else "at"
    s = f'{where} {g["opp"]}'
    if g.get("spread") is not None:
        sp = g["spread"]
        s += (f', favored by {abs(sp):g}' if sp < 0
              else f', {abs(sp):g}-point underdog' if sp > 0 else ', pick\'em')
    if g.get("total"):
        s += f', total {g["total"]:g}'
    return s


def team_context(pro_teams, season, week):
    """{abbr: description} for just the NFL teams that matter to this matchup."""
    gs = games(season, week)
    if not gs:
        return {}
    return {t: describe(t, gs[t]) for t in sorted(set(pro_teams)) if t in gs}


if __name__ == "__main__":
    import sys
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    week = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    g = games(season, week)
    print(f"{len(g)} teams for {season} week {week}")
    for t in sorted(g):
        print(f"  {t:<4} {describe(t, g[t])}")
