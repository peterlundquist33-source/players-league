"""Weekly-scoring records + franchise achievement banners.

Two outputs, one data pass:
  1. js/records.js  ->  LEAGUE_RECORDS  (read by the Teams page: banner rafters +
     weekly high/low stat cards)
  2. the <!-- WEEKLY:start --> ... <!-- WEEKLY:end --> block in analytics.html
     (the "Weekly Scoring" tab — crowns & cellars leaderboard)

"Leading the league in a week" = highest score of all 12 teams that regular-season
week. Playoffs excluded (only a handful of teams play). Achievements come from ESPN's
final standings / playoff seeds / divisions, 2022 -> present.

Run:  python3 tools/main.py records --season 2026
      python3 tools/records.py 2026
"""
import datetime
import json
import re

from lib import ROOT, espn, load_env
from lore import OWNERS, owner as canon
from analytics import FIRST_SEASON, _pull

RECORDS_JS = ROOT / "js" / "records.js"
ANALYTICS = ROOT / "analytics.html"
START = "<!-- WEEKLY:start -->"
END = "<!-- WEEKLY:end -->"

FIRST_TO_FULL = {v: k for k, v in OWNERS.items()}
DIVISIONS = {0: "East", 1: "West"}
DRESS_YEARS = {2025}          # seasons the last-place owner actually wore the dress


# ---------------------------------------------------------------- weekly high / low

def _weekly(through_season):
    """Per owner: regular-season weeks as the league's top / bottom scorer,
    all-time and for the current season, plus their single highest / lowest week."""
    stat = {}

    def _s(o):
        return stat.setdefault(o, {
            "high_weeks": 0, "low_weeks": 0,
            "high_weeks_season": 0, "low_weeks_season": 0,
            "highest": {"score": 0.0}, "lowest": {"score": 1e9},
        })

    for yr in range(FIRST_SEASON, through_season + 1):
        try:
            p = _pull(yr)
        except SystemExit:
            continue
        for w in p["weeks"]:
            sc = p["scores"][w]
            if len(sc) < 2:
                continue
            hi_o = max(sc, key=sc.get)
            lo_o = min(sc, key=sc.get)
            _s(hi_o)["high_weeks"] += 1
            _s(lo_o)["low_weeks"] += 1
            if yr == through_season:
                _s(hi_o)["high_weeks_season"] += 1
                _s(lo_o)["low_weeks_season"] += 1
            for o, s in sc.items():
                e = _s(o)
                if s > e["highest"]["score"]:
                    e["highest"] = {"score": round(s, 2), "week": w, "year": yr}
                if s < e["lowest"]["score"]:
                    e["lowest"] = {"score": round(s, 2), "week": w, "year": yr}

    for e in stat.values():
        if e["lowest"]["score"] >= 1e9:
            e["lowest"] = None
        if e["highest"]["score"] <= 0:
            e["highest"] = None
    return stat


# ---------------------------------------------------------------- achievements

def _season_meta(season):
    d = espn(["mTeam", "mSettings"], season)
    sched = d.get("settings", {}).get("scheduleSettings", {})
    n_playoff = sched.get("playoffTeamCount", 6)
    mem = {m["id"]: canon(f'{m.get("firstName","")} {m.get("lastName","")}')
           for m in d.get("members", [])}
    teams = []
    for t in d.get("teams", []):
        o = mem.get(t.get("primaryOwner")) or mem.get((t.get("owners") or [None])[0])
        if not o:
            continue
        rec = t.get("record", {}).get("overall", {})
        teams.append({
            "owner": o,
            "final_rank": t.get("rankCalculatedFinal") or 99,
            "seed": t.get("playoffSeed") or 99,
            "division": t.get("divisionId", 0),
            "wins": rec.get("wins", 0),
            "losses": rec.get("losses", 0),
            "pf": round(rec.get("pointsFor", 0.0), 1),
        })
    return {"season": season, "n_playoff": n_playoff, "teams": teams}


def _achievements(through_season):
    ach = {o: [] for o in OWNERS.values()}

    def add(owner, icon, label, year, tier, note=""):
        ach[owner].append({"icon": icon, "label": label, "year": year,
                           "tier": tier, "note": note})

    for yr in range(FIRST_SEASON, through_season + 1):
        try:
            meta = _season_meta(yr)
        except SystemExit:
            continue
        teams = meta["teams"]
        if not teams or not any(t["wins"] or t["losses"] for t in teams):
            continue                                  # season hasn't been played

        n = meta["n_playoff"]
        scoring_champ = max(teams, key=lambda t: t["pf"])["owner"]
        dress = min(teams, key=lambda t: (t["wins"], t["pf"]))["owner"]
        div_winners = {}
        for div in {t["division"] for t in teams}:
            pool = [t for t in teams if t["division"] == div]
            div_winners[div] = max(pool, key=lambda t: (t["wins"], t["pf"]))["owner"]

        for t in teams:
            o = t["owner"]
            if t["final_rank"] == 1:
                add(o, "🏆", "Champion", yr, "champ")
                if t["seed"] >= 4:
                    add(o, "🎯", "Cinderella", yr, "major")
            elif t["final_rank"] == 2:
                add(o, "🥈", "Runner-Up", yr, "silver")
                if t["seed"] >= 4:
                    add(o, "🎯", "Cinderella", yr, "major")
            if t["seed"] == 1:
                add(o, "🥇", "#1 Seed", yr, "major")
            if div_winners.get(t["division"]) == o:
                add(o, "🎖️", f'{DIVISIONS.get(t["division"], "Division")} Title', yr, "major")
            if scoring_champ == o:
                add(o, "📊", "Scoring Title", yr, "major")
            if t["seed"] <= n and t["final_rank"] not in (1, 2):
                add(o, "🎟️", "Playoff Berth", yr, "minor")
            if dress == o:
                if yr in DRESS_YEARS:
                    add(o, "👗", "The Dress", yr, "dishonor")
                else:
                    add(o, "🚽", "Last Place", yr, "dishonor")

    order = {"champ": 0, "silver": 1, "major": 2, "minor": 3, "dishonor": 4}
    for lst in ach.values():
        lst.sort(key=lambda a: (order[a["tier"]], a["year"], a["label"]))
    return ach


# ---------------------------------------------------------------- build + write

def build(through_season):
    weekly = _weekly(through_season)
    ach = _achievements(through_season)

    per_owner = {}
    board = []
    for first, full in FIRST_TO_FULL.items():
        w = weekly.get(first, {"high_weeks": 0, "low_weeks": 0,
                               "high_weeks_season": 0, "low_weeks_season": 0,
                               "highest": None, "lowest": None})
        per_owner[full] = w
        board.append({"owner": first, "full": full,
                      "high_weeks": w["high_weeks"], "low_weeks": w["low_weeks"],
                      "high_weeks_season": w["high_weeks_season"],
                      "low_weeks_season": w["low_weeks_season"],
                      "highest": w["highest"], "lowest": w["lowest"]})
    board.sort(key=lambda r: (-r["high_weeks"], r["low_weeks"], r["owner"]))

    return {
        "generated": datetime.date.today().isoformat(),
        "season": through_season,
        "weekly": per_owner,
        "weekly_leaderboard": board,
        "achievements": {FIRST_TO_FULL[o]: v for o, v in ach.items()},
    }


def _write_js(data):
    RECORDS_JS.write_text(
        "// Generated by tools/records.py — do not hand-edit.\n"
        "// Weekly-scoring records + franchise banners, refreshed by the weekly workflow.\n"
        f"// last built: {data['generated']}\n"
        "const LEAGUE_RECORDS = " + json.dumps({
            "generated": data["generated"],
            "season": data["season"],
            "weekly": data["weekly"],
            "achievements": data["achievements"],
        }, indent=2) + ";\n"
    )
    print(f"wrote {RECORDS_JS.relative_to(ROOT)}")


# ---------------------------------------------------------------- analytics tab

def _rows(board, key_hi, key_lo, season_label):
    body = ""
    for i, r in enumerate(board, 1):
        hi = f'{r["highest"]["score"]:.1f} <span style="color:var(--text-muted);font-size:.82em;">' \
             f'W{r["highest"]["week"]} {r["highest"]["year"]}</span>' if r["highest"] else "—"
        lo = f'{r["lowest"]["score"]:.1f} <span style="color:var(--text-muted);font-size:.82em;">' \
             f'W{r["lowest"]["week"]} {r["lowest"]["year"]}</span>' if r["lowest"] else "—"
        body += (
            f'<tr><td><span class="rank-num">{i}</span></td>'
            f'<td style="font-weight:600;color:var(--text);">{r["owner"]}</td>'
            f'<td style="font-weight:700;color:var(--accent);">{r[key_hi]}</td>'
            f'<td style="font-weight:700;color:var(--red);">{r[key_lo]}</td>'
            f'<td>{hi}</td><td>{lo}</td></tr>'
        )
    return (
        '<div class="table-scroll" style="overflow-x:auto;">'
        '<table class="data-table sticky-first"><thead><tr>'
        '<th>#</th><th>Owner</th><th>👑 Wks&nbsp;Led</th><th>💀 Wks&nbsp;Last</th>'
        '<th>Highest Wk</th><th>Lowest Wk</th></tr></thead>'
        f'<tbody>{body}</tbody></table></div>'
    )


def _weekly_block(data):
    board = data["weekly_leaderboard"]
    played_2026 = any(r["high_weeks_season"] or r["low_weeks_season"] for r in board)

    cur = ""
    if played_2026:
        cur_board = sorted(board, key=lambda r: (-r["high_weeks_season"], r["low_weeks_season"], r["owner"]))
        cur = (
            '<h3 style="color:var(--accent);font-size:1.05rem;margin:2rem 0 .4rem;">'
            f'{data["season"]} — so far</h3>'
            + _rows(cur_board, "high_weeks_season", "low_weeks_season", str(data["season"]))
        )

    return (
        f'{START}\n  <!-- generated by tools/records.py — do not hand-edit -->\n'
        '  <section id="tab-weekly" class="section analytics-section">\n'
        '  <h2 class="section-title">👑 Weekly Scoring — Crowns &amp; Cellars</h2>'
        '<div class="gold-line"></div>'
        '<p class="section-sub">Every regular-season week, one team tops all 12 in points and '
        'one finishes dead last. This is who does it most. 2022–' f'{data["season"] - 1 if not played_2026 else data["season"]}'
        ', regular season only.</p>'
        + _rows(board, "high_weeks", "low_weeks", "all-time")
        + cur +
        '\n  </section>\n  ' + END
    )


def update(season):
    load_env()
    data = build(season)
    _write_js(data)

    src = ANALYTICS.read_text()
    block = _weekly_block(data)
    if START in src and END in src:
        new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, src, flags=re.S)
        if new != src:
            ANALYTICS.write_text(new)
            print("analytics.html weekly-scoring tab updated")
        else:
            print("analytics.html unchanged")
    else:
        print("WEEKLY markers not found in analytics.html — add them once, then re-run")


if __name__ == "__main__":
    import sys
    yr = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    update(yr)
