"""Beat the Board — CHANNEL 11. Weekly confidence pick'em, scored and rendered.

The only page on the site owners write to. Picks live in Firestore (same
`rizzlers-pickems` project the pick'em and the wedding to-dos use, no accounts);
everything else — the slate, the lock times, the results and the leaderboard —
is baked into board.html from this repo's own data by this script.

    python3 tools/board.py                 # rebuild board.html for 2026
    python3 tools/board.py 2026
    python3 tools/board.py --rules         # print the Firestore rules block
    python3 tools/board.py --scores        # print the leaderboard, don't write

Reads only committed data: tools/data/{season}-week-NN.json for finals,
-preview.json for the open slate. No ESPN credentials needed. The one network
call is ESPN's public scoreboard, to learn each week's real first kickoff; the
answer is cached in tools/data/{season}-board-locks.json, and a missed fetch
falls back to Thursday 7:00pm CT.

Scoring (one place, this file):
  * a correct pick scores its own confidence rank, 1 through 6 — max 21
  * closest to the week's highest single-team score: +3
  * closest to the week's smallest margin of victory: +3
  * a tie on either bonus pays every entrant who tied
A tied fantasy matchup scores nobody.
"""
import argparse
import datetime
import html
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from lib import ROOT
from lore import OWNERS
import chrome as SITE

DATA = ROOT / "tools" / "data"
OUT = ROOT / "board.html"
CT = ZoneInfo("America/Chicago")

# The twelve, full names, alphabetical — this list IS the dropdown and it is
# repeated verbatim in the Firestore rules. Free text would let one typo split
# a man's season across two leaderboard rows.
ENTRANTS = sorted(OWNERS)                      # "Adam Stockwell", ...
FIRST = {full: first for full, first in OWNERS.items()}
FIRSTS = sorted(set(OWNERS.values()))

WEEKS = 18                  # NFL weeks the lock table covers
MAX_CONF = 6                # six fantasy matchups, confidence 1-6
BONUS = 3                   # each tiebreaker bonus
LOCK_HOUR = 19              # 7:00pm CT, nominal Thursday lock

FB_PROJECT = "rizzlers-pickems"
FB_KEY = "AIzaSyCtUp7DYEjdE5i_Vt9oTqzpmNAgHP32xy8"   # public web API key, not a secret
FB_DOCS = f"https://firestore.googleapis.com/v1/projects/{FB_PROJECT}/databases/(default)/documents"
COLLECTION = "boardpicks"


# ------------------------------------------------------------------ lock times

def _nominal_lock(season, week):
    """Thursday 7:00pm CT of that NFL week. Week 1 Thursday is the season anchor."""
    # 2026 week 1's Thursday. Every later week is exactly 7 days on, localised
    # separately so the Nov 1 DST change can't shift the hour.
    anchor = datetime.date(2026, 9, 10) if season == 2026 else None
    if anchor is None:                      # other seasons: first Thu after Labor Day
        sept = datetime.date(season, 9, 1)
        labor = sept + datetime.timedelta(days=(7 - sept.weekday()) % 7)   # 1st Monday
        anchor = labor + datetime.timedelta(days=3)
    d = anchor + datetime.timedelta(days=7 * (week - 1))
    return datetime.datetime(d.year, d.month, d.day, LOCK_HOUR, 0, tzinfo=CT)


def _espn_first_kickoff(season, week):
    """UTC datetime of the week's earliest real NFL kickoff, or None.

    Uses the same cdn.espn.com scoreboard nfl.py does — site.api.espn.com answers
    403 to this client.
    """
    try:
        import nfl as NF
        d = NF._get(NF.URL.format(week=week, season=season))
        events = d["content"]["sbData"]["events"]
    except Exception:
        return None
    dates = sorted(x for x in (e.get("date") or "" for e in events) if x)
    if not dates:
        return None
    try:
        return datetime.datetime.strptime(dates[0], "%Y-%m-%dT%H:%MZ").replace(
            tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def locks(season, weeks=WEEKS, refresh=False):
    """{week: epoch_millis}. The earlier of Thursday 7pm CT and the real first
    kickoff — weeks 1 and 12 open on a Wednesday, so the nominal Thursday alone
    would leave picks writable after games had started."""
    path = DATA / f"{season}-board-locks.json"
    cache = {}
    if path.exists() and not refresh:
        try:
            cache = {int(k): v for k, v in json.loads(path.read_text()).items()}
        except Exception:
            cache = {}
    out, dirty = {}, False
    for w in range(1, weeks + 1):
        if w in cache:
            out[w] = cache[w]
            continue
        nominal = _nominal_lock(season, w)
        kick = _espn_first_kickoff(season, w)
        when = min(nominal, kick) if kick else nominal
        out[w] = int(when.timestamp() * 1000)
        dirty = True
    if dirty:
        path.write_text(json.dumps({str(k): v for k, v in sorted(out.items())}, indent=1) + "\n")
    return out


def lock_label(millis):
    t = datetime.datetime.fromtimestamp(millis / 1000, CT)
    return t.strftime("%a %b %-d, %-I:%M %p CT" if sys.platform != "win32"
                      else "%a %b %d, %I:%M %p CT")


# ----------------------------------------------------------------- the slates

def matchup_id(a, b):
    """Order-independent id for a fantasy matchup: 'adam-kaleb'. ESPN flips home
    and away between the preview and the recap, so the pair has to sort."""
    return "-".join(sorted([a.lower(), b.lower()]))


def _week_file(season, week):
    """The best file for a week: a recap beats a preview."""
    for name in (f"{season}-week-{week:02d}.json", f"{season}-week-{week:02d}-preview.json"):
        p = DATA / name
        if p.exists():
            return p
    return None


def slates(season, weeks=WEEKS):
    """{week: {'phase','games':[{id,away,home,away_team,home_team,away_pts,home_pts,played}]}}"""
    out = {}
    for w in range(1, weeks + 1):
        p = _week_file(season, w)
        if not p:
            continue
        try:
            blob = json.loads(p.read_text())
        except Exception:
            continue
        d = blob.get("data") or {}
        games = []
        for m in d.get("matchups") or []:
            a, h = m.get("away") or {}, m.get("home") or {}
            if not a.get("owner") or not h.get("owner"):
                continue
            games.append({
                "id": matchup_id(a["owner"], h["owner"]),
                "away": a["owner"], "home": h["owner"],
                "away_team": a.get("team", ""), "home_team": h.get("team", ""),
                "away_pts": round(float(a.get("actual") or 0.0), 2),
                "home_pts": round(float(h.get("actual") or 0.0), 2),
                "played": bool(m.get("played")),
            })
        if games:
            out[w] = {"phase": blob.get("phase", "preview"), "games": games}
    return out


def results(slate):
    """Graded truth for one finished week, or None while it is still in progress.

    -> {winners: {mid: first_name|None}, high: float, margin: float}
    """
    games = slate["games"]
    if not games or not all(g["played"] for g in games):
        return None
    winners, scores, margins = {}, [], []
    for g in games:
        a, h = g["away_pts"], g["home_pts"]
        winners[g["id"]] = None if a == h else (g["away"] if a > h else g["home"])
        scores += [a, h]
        margins.append(round(abs(a - h), 2))
    return {"winners": winners, "high": max(scores), "margin": min(margins)}


def open_week(slates_, results_):
    """The next unplayed week: lowest week with a slate and no final result."""
    for w in sorted(slates_):
        if not results_.get(w):
            return w
    return (max(slates_) + 1) if slates_ else 1


# ------------------------------------------------------------------- the picks

def fetch_picks(timeout=30):
    """Every submitted entry, straight off the public Firestore REST API.

    -> {week(int): {owner_full: {picks, conf, high, margin, updated}}}
    """
    out, token = {}, None
    while True:
        q = {"pageSize": "300", "key": FB_KEY}
        if token:
            q["pageToken"] = token
        url = f"{FB_DOCS}/{COLLECTION}?" + urllib.parse.urlencode(q)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                blob = json.load(r)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Firestore HTTP {e.code}: {e.read().decode()[:300]}")
        for doc in blob.get("documents", []):
            e = _from_firestore(doc.get("fields") or {})
            if not e:
                continue
            out.setdefault(e["week"], {})[e["owner"]] = e
        token = blob.get("nextPageToken")
        if not token:
            break
    return out


def _from_firestore(f):
    """One document's fields -> a plain entry, or None if it isn't one of ours."""
    def s(k):
        return (f.get(k) or {}).get("stringValue")

    def n(k):
        v = f.get(k) or {}
        for key in ("doubleValue", "integerValue"):
            if key in v:
                return float(v[key])
        return None

    def smap(k):
        fields = ((f.get(k) or {}).get("mapValue") or {}).get("fields") or {}
        return {kk: (vv or {}).get("stringValue") for kk, vv in fields.items()}

    week, owner = s("week"), s("owner")
    if not week or not week.isdigit() or owner not in OWNERS:
        return None
    conf = {k: int(v) for k, v in smap("conf").items() if v and v.isdigit()}
    return {"week": int(week), "owner": owner, "picks": smap("picks"), "conf": conf,
            "high": n("high"), "margin": n("margin"),
            "updated": ((f.get("updated") or {}).get("timestampValue") or "")}


# --------------------------------------------------------------------- scoring

def score_week(entries, result):
    """Score one week. `entries` is {owner_full: entry}, `result` from results().

    -> {owner_full: {hits, pick_pts, high_bonus, margin_bonus, total}}
    """
    out = {}
    for owner, e in entries.items():
        hits, pts = 0, 0
        for mid, winner in result["winners"].items():
            if winner and e["picks"].get(mid) == winner:
                hits += 1
                pts += int(e["conf"].get(mid) or 0)
        out[owner] = {"hits": hits, "pick_pts": pts, "high_bonus": 0,
                      "margin_bonus": 0, "total": pts}
    for field, actual in (("high", result["high"]), ("margin", result["margin"])):
        guesses = {o: e[field] for o, e in entries.items() if e.get(field) is not None}
        if not guesses:
            continue
        best = min(abs(v - actual) for v in guesses.values())
        for o, v in guesses.items():
            if abs(v - actual) == best:          # a tie pays everyone who tied
                out[o][f"{field}_bonus"] = BONUS
                out[o]["total"] += BONUS
    return out


def leaderboard(slates_, results_, picks):
    """Season standings plus the per-week grid.

    -> {'weeks': [w...], 'by_week': {w: {owner: scorecard}}, 'rows': [...]}
    """
    by_week, scored = {}, []
    for w in sorted(slates_):
        r = results_.get(w)
        if not r:
            continue
        by_week[w] = score_week(picks.get(w, {}), r)
        scored.append(w)
    rows = []
    for owner in ENTRANTS:
        weeks = {w: by_week[w][owner] for w in scored if owner in by_week[w]}
        total = sum(c["total"] for c in weeks.values())
        played = len(weeks)
        rows.append({
            "owner": owner, "first": FIRST[owner], "total": total, "played": played,
            "hits": sum(c["hits"] for c in weeks.values()),
            "pick_pts": sum(c["pick_pts"] for c in weeks.values()),
            "bonus": sum(c["high_bonus"] + c["margin_bonus"] for c in weeks.values()),
            "best": max((c["total"] for c in weeks.values()), default=0),
            "avg": round(total / played, 1) if played else 0.0,
        })
    # most points wins; a man who entered more weeks ranks ahead of a man who
    # scored the same from fewer, then alphabetical so the order never jitters
    rows.sort(key=lambda r: (-r["total"], -r["played"], r["owner"]))
    return {"weeks": scored, "by_week": by_week, "rows": rows}


# --------------------------------------------------------------- rules snippet

def rules_block(season=2026):
    """The Firestore rules for this collection, lock table baked in.

    Paste into the canonical combined ruleset (wolves-ticket-draft/firestore.rules)
    and publish via the Rules API — never publish this block on its own.
    """
    lk = locks(season)
    table = ",\n".join(f"        '{w}': {ms}" for w, ms in sorted(lk.items()))
    owners = ", ".join(f"'{o}'" for o in ENTRANTS)
    firsts = ", ".join(f"'{f}'" for f in FIRSTS)
    weeks = ", ".join(f"'{w}'" for w in range(1, WEEKS + 1))
    return f"""\
    // ---- Players League "Beat the Board" pick'em -------------------------------
    // One doc per owner per week, id "<week>-<Owner Full Name>", so a resubmission
    // overwrites and nobody can file picks under someone else's name. Writes are
    // unauthenticated like the rest of this project, so the rules carry the whole
    // integrity story: known owner, 1-6 confidence permutation, and a hard lock at
    // kickoff. Lock table is epoch millis, generated by players-league
    // tools/board.py ({season} season) — the earlier of Thursday 7pm CT and that
    // week's real first kickoff.
    function boardOwners() {{
      return [{owners}];
    }}
    function boardFirsts() {{
      return [{firsts}];
    }}
    function boardWeeks() {{
      return [{weeks}];
    }}
    function boardLock(w) {{
      return {{
{table}
      }}[w];
    }}
    function boardShapeOk(d) {{
      return d.keys().hasOnly(['week', 'owner', 'picks', 'conf', 'high', 'margin', 'updated'])
             && d.keys().hasAll(['week', 'owner', 'picks', 'conf', 'high', 'margin'])
             && d.week in boardWeeks()
             && d.owner in boardOwners()
             && d.picks is map && d.picks.size() == {MAX_CONF}
             && d.picks.values().hasOnly(boardFirsts())
             && d.conf is map && d.conf.size() == {MAX_CONF}
             && d.conf.keys().hasOnly(d.picks.keys())
             && d.conf.values().hasAll(['1', '2', '3', '4', '5', '6'])
             && d.high is number && d.high > 0 && d.high < 400
             && d.margin is number && d.margin >= 0 && d.margin < 400;
    }}
    match /{COLLECTION}/{{id}} {{
      allow read: if true;
      allow write: if boardShapeOk(request.resource.data)
                   && id == request.resource.data.week + '-' + request.resource.data.owner
                   && request.time.toMillis() < boardLock(request.resource.data.week);
      allow delete: if false;
    }}
"""


# ---------------------------------------------------------------------- render

def _esc(s):
    return html.escape(str(s), quote=True)


def _leaderboard_html(lb, slates_):
    if not lb["weeks"]:
        return ('<p class="bd-empty">Nothing scored yet. The first leaderboard posts once '
                'this week\'s games are final.</p>')
    head = "".join(f"<th>W{w}</th>" for w in lb["weeks"])
    body = []
    for i, r in enumerate(lb["rows"], 1):
        cells = []
        for w in lb["weeks"]:
            c = lb["by_week"][w].get(r["owner"])
            cells.append(f'<td>{c["total"]}</td>' if c else '<td class="bd-dnp">&mdash;</td>')
        cls = ' class="row-hi"' if i == 1 and r["total"] else ""
        body.append(
            f'<tr{cls}><td><span class="rank-num">{i}</span></td>'
            f'<td class="strong">{_esc(r["first"])}</td>'
            f'<td class="bd-tot">{r["total"]}</td>'
            f'<td class="muted">{r["played"]}</td>'
            f'<td class="muted">{r["hits"]}</td>'
            f'<td class="muted">{r["bonus"]}</td>'
            f'<td class="muted">{r["avg"]}</td>'
            f'<td class="muted">{r["best"]}</td>'
            f'{"".join(cells)}</tr>')
    return (
        '<div class="table-scroll"><table class="data-table sticky-first">'
        '<thead><tr><th>#</th><th>Owner</th><th>Pts</th><th>Wks</th><th>Hits</th>'
        f'<th>Bonus</th><th>Avg</th><th>Best</th>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>')


def _results_html(lb, slates_):
    """Week-by-week receipts: what actually happened, and who called it."""
    if not lb["weeks"]:
        return ""
    out = []
    for w in sorted(lb["weeks"], reverse=True):
        r = results(slates_[w])
        cards = []
        for g in slates_[w]["games"]:
            win = r["winners"][g["id"]]
            callers = [FIRST[o] for o, e in sorted(lb["by_week"][w].items())
                       if win and e and _picked(lb, w, o, g["id"]) == win]
            cards.append(
                f'<tr><td class="strong">{_esc(g["away"])} {g["away_pts"]:.1f}'
                f' &mdash; {g["home_pts"]:.1f} {_esc(g["home"])}</td>'
                f'<td class="bd-win">{_esc(win or "tie")}</td>'
                f'<td class="muted">{_esc(", ".join(callers)) or "&mdash;"}</td></tr>')
        out.append(
            f'<h3 class="sub-title">Week {w}</h3>'
            f'<p class="section-sub">High score {r["high"]:.1f} &middot; '
            f'smallest margin {r["margin"]:.1f}</p>'
            '<div class="table-scroll"><table class="data-table">'
            '<thead><tr><th>Final</th><th>Winner</th><th>Who had it</th></tr></thead>'
            f'<tbody>{"".join(cards)}</tbody></table></div>')
    return "".join(out)


_PICKS_CACHE = {}


def _picked(lb, week, owner, mid):
    return _PICKS_CACHE.get((week, owner), {}).get(mid)


def build(season=2026, refresh_locks=False):
    lk = locks(season, refresh=refresh_locks)
    sl = slates(season)
    res = {w: results(s) for w, s in sl.items()}
    res = {w: r for w, r in res.items() if r}
    try:
        picks = fetch_picks()
    except SystemExit as e:
        print(f"  picks unavailable ({e}) — leaderboard will show as empty")
        picks = {}
    for w, by_owner in picks.items():
        for owner, e in by_owner.items():
            _PICKS_CACHE[(w, owner)] = e["picks"]
    lb = leaderboard(sl, res, picks)
    wk = open_week(sl, res)
    open_slate = sl.get(wk, {"games": []})
    lock_ms = lk.get(wk, 0)

    cfg = {
        "season": season, "week": wk, "lockMs": lock_ms,
        "lockLabel": lock_label(lock_ms) if lock_ms else "",
        "entrants": ENTRANTS, "firsts": FIRSTS,
        "maxConf": MAX_CONF,
        "games": [{"id": g["id"], "away": g["away"], "home": g["home"],
                   "awayTeam": g["away_team"], "homeTeam": g["home_team"]}
                  for g in open_slate["games"]],
        "project": FB_PROJECT, "collection": COLLECTION,
        "weeks": {str(w): {"lockMs": lk.get(w, 0),
                           "games": [{"id": g["id"], "away": g["away"], "home": g["home"]}
                                     for g in s["games"]]}
                  for w, s in sl.items()},
    }
    body = _TEMPLATE_BODY.format(
        week=wk,
        lock=_esc(cfg["lockLabel"]),
        n_games=len(cfg["games"]),
        max_conf_label=MAX_CONF,
        max_pts=sum(range(1, MAX_CONF + 1)),
        bonus=BONUS,
        max_total=sum(range(1, MAX_CONF + 1)) + 2 * BONUS,
        leaderboard=_leaderboard_html(lb, sl),
        receipts=_results_html(lb, sl),
        scored=("Weeks " + ", ".join(str(w) for w in lb["weeks"])) if lb["weeks"] else "nothing yet",
        config=json.dumps(cfg, separators=(",", ":")),
        firebase=json.dumps(_FB_CONFIG, separators=(",", ":")),
    )
    doc = f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- HEAD:start -->
{SITE.head("board.html", 0, title="Beat the Board — Players League", desc="The weekly Players League prediction game: pick all six matchups, rank your confidence 1-6, and climb the season leaderboard.")}
<!-- HEAD:end -->
</head>
<body>
<!-- NAV:start -->
{SITE.nav("", 0)}
<!-- NAV:end -->
{body}
<!-- FOOTER:start -->
{SITE.footer()}
<!-- FOOTER:end -->
{SITE.scripts(0)}
</body></html>
'''
    OUT.write_text(doc, encoding="utf-8")
    (DATA / f"{season}-board-scores.json").write_text(
        json.dumps({"season": season, "open_week": wk,
                    "scored_weeks": lb["weeks"], "rows": lb["rows"]}, indent=1) + "\n")
    return OUT, wk, lb


_FB_CONFIG = {
    "apiKey": FB_KEY,
    "authDomain": f"{FB_PROJECT}.firebaseapp.com",
    "projectId": FB_PROJECT,
    "storageBucket": f"{FB_PROJECT}.firebasestorage.app",
    "messagingSenderId": "401907218298",
    "appId": "1:401907218298:web:795ef076067ee1926b88c3",
}


# The page: header, entry form, submission tracker, leaderboard, receipts.
# Components use .bd-* classes defined in the page's own <style> block so this
# channel can't change how any other page renders.
_TEMPLATE_BODY = r'''<style>
  .bd-wrap {{ max-width: var(--measure); margin: 0 auto; padding: 0 var(--s-6) var(--s-8); }}
  .bd-state {{
    display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap;
    background: var(--surface); border: var(--hair); border-left: 2px solid var(--accent);
    border-radius: var(--r); padding: var(--s-4) var(--s-5); margin-bottom: var(--s-6);
  }}
  .bd-state.is-locked {{ border-left-color: var(--neg); }}
  .bd-chip {{
    font-size: 10px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
    color: var(--accent); background: var(--accent-tint); border: 1px solid var(--accent-line);
    border-radius: 999px; padding: 2px 10px;
  }}
  .bd-state.is-locked .bd-chip {{ color: var(--neg); background: var(--neg-tint); border-color: var(--neg); }}
  .bd-clock {{ font-family: var(--font-display); font-weight: 700; font-size: var(--fs-18); }}
  .bd-state p {{ margin: 0; color: var(--text-2); font-size: var(--fs-13); }}

  .bd-form {{ background: var(--surface); border: var(--hair); border-radius: var(--r); box-shadow: var(--shadow), var(--lift); }}
  .bd-form > header {{ padding: var(--s-5) var(--s-5) var(--s-4); border-bottom: var(--hair); }}
  .bd-form h2 {{ font-size: var(--fs-18); }}
  .bd-form > header p {{ color: var(--text-2); font-size: var(--fs-13); margin-top: var(--s-2); }}
  .bd-field {{ padding: var(--s-4) var(--s-5); border-bottom: var(--hair); display: flex; gap: var(--s-4); align-items: center; flex-wrap: wrap; }}
  .bd-label {{ font-size: var(--fs-12); font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-3); min-width: 150px; }}
  .bd-input, .bd-select {{
    background: var(--surface-2); color: var(--text); border: 1px solid var(--line-2);
    border-radius: var(--r-sm); padding: 8px var(--s-3); font: inherit; min-height: 38px;
  }}
  .bd-select {{ min-width: 240px; }}
  .bd-input {{ width: 120px; font-variant-numeric: tabular-nums; }}
  .bd-input:focus-visible, .bd-select:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
  .bd-hint {{ font-size: var(--fs-12); color: var(--text-3); }}

  .bd-game {{ display: grid; grid-template-columns: 1fr 236px; gap: var(--s-4); align-items: center; padding: var(--s-4) var(--s-5); border-bottom: var(--hair); }}
  .bd-sides {{ display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-2); }}
  .bd-side {{
    display: block; text-align: left; background: var(--surface-2); border: 1px solid var(--line-2);
    border-radius: var(--r-sm); padding: var(--s-3); transition: var(--transition);
  }}
  .bd-side:hover {{ border-color: var(--text-3); }}
  .bd-side.is-on {{ border-color: var(--accent); background: var(--accent-tint); box-shadow: inset 0 0 0 1px var(--accent-line); }}
  .bd-side-own {{ font-family: var(--font-display); font-weight: 700; font-size: var(--fs-16); }}
  .bd-side-team {{ display: block; font-size: var(--fs-12); color: var(--text-2); margin-top: 2px; }}
  .bd-conf {{ display: flex; flex-direction: column; gap: 6px; }}
  .bd-conf .bd-label {{ min-width: 0; }}
  .bd-conf-opts {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: var(--s-2); }}
  .bd-rank {{
    display: flex; align-items: center; justify-content: center; min-height: 38px; padding: 0;
    font-family: var(--font-display); font-weight: 700; font-size: var(--fs-16);
    font-variant-numeric: tabular-nums; color: var(--text-3);
    background: var(--surface-2); border: 1px solid var(--line-2);
    border-radius: var(--r-sm); transition: var(--transition);
  }}
  .bd-rank:hover {{ border-color: var(--text-3); color: var(--text); }}
  .bd-rank.is-on {{
    color: var(--text); border-color: var(--accent); background: var(--accent-tint);
    box-shadow: inset 0 0 0 1px var(--accent-line);
  }}
  .bd-rank.is-taken {{ color: var(--text-3); opacity: .45; }}
  .bd-rank:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
  .bd-conf.is-dupe .bd-rank.is-on {{ border-color: var(--neg); background: var(--neg-tint); box-shadow: none; }}
  .bd-actions {{ display: flex; align-items: center; gap: var(--s-4); flex-wrap: wrap; padding: var(--s-5); }}
  .bd-msg {{ font-size: var(--fs-13); color: var(--text-2); }}
  .bd-msg.is-bad {{ color: var(--neg); }}
  .bd-msg.is-good {{ color: var(--accent); }}
  button.bd-side, button.btn {{ font: inherit; }}
  .btn[disabled] {{ opacity: .5; cursor: not-allowed; }}

  .bd-who {{ display: flex; flex-wrap: wrap; gap: var(--s-2); margin-top: var(--s-4); }}
  .bd-who span {{
    font-size: var(--fs-12); font-weight: 600; border-radius: 999px; padding: 3px 10px;
    border: 1px solid var(--line-2); color: var(--text-3); background: var(--surface);
  }}
  .bd-who span.is-in {{ color: var(--accent); border-color: var(--accent-line); background: var(--accent-tint); }}
  .bd-who span.is-out {{ color: var(--neg); border-color: var(--neg); background: var(--neg-tint); }}

  .bd-grid td.bd-conf-cell {{ font-variant-numeric: tabular-nums; color: var(--text-3); }}
  .bd-grid .bd-pick {{ font-weight: 600; }}
  .bd-tot {{ font-family: var(--font-display); font-weight: 700; }}
  .bd-dnp {{ color: var(--text-3); }}
  .bd-win {{ color: var(--accent); font-weight: 600; }}
  .bd-empty {{ color: var(--text-2); border: 1px dashed var(--line-2); border-radius: var(--r); padding: var(--s-5); }}
  .bd-rules li {{ color: var(--text-2); font-size: var(--fs-13); margin-bottom: 6px; }}
  .bd-rules b {{ color: var(--text); }}
  @media (max-width: 560px) {{
    .bd-game {{ grid-template-columns: 1fr; }}
    .bd-sides {{ grid-template-columns: 1fr; }}
    .bd-select, .bd-input {{ width: 100%; min-width: 0; }}
  }}
</style>

<section class="page-header">
  <span class="eyebrow">Channel 11</span>
  <h1>Beat the <span class="gold">Board</span></h1>
  <p>Pick all {n_games} matchups, rank them 1 to {max_conf_label} by how sure you are, and add two tiebreakers.
     A right pick pays its rank — {max_pts} points if you sweep, {max_total} with both bonuses.
     Everything locks at kickoff and then everyone's card goes public.</p>
</section>

<div class="bd-wrap">
  <div class="bd-state" id="bd-state">
    <span class="bd-chip" id="bd-chip">Week {week}</span>
    <span class="bd-clock" id="bd-clock">&hellip;</span>
    <p id="bd-lock">Locks {lock}</p>
  </div>

  <div id="bd-live"></div>

  <section class="section" style="padding-left:0;padding-right:0">
    <span class="eyebrow">Standings</span>
    <h2 class="section-title">Season leaderboard</h2>
    <p class="section-sub">Scored by this site's pipeline, not by the browser &mdash; {scored}.
       Pts = confidence points plus bonuses. Hits = correct picks. Wks = weeks entered.</p>
    {leaderboard}
  </section>

  <section class="section" style="padding-left:0;padding-right:0">
    <span class="eyebrow">Receipts</span>
    <h2 class="section-title">How each week actually went</h2>
    {receipts}
  </section>

  <section class="section" style="padding-left:0;padding-right:0">
    <span class="eyebrow">The rules</span>
    <h2 class="section-title">Scoring</h2>
    <ul class="bd-rules">
      <li><b>Confidence points.</b> Every matchup you call right pays the rank you put on it, 1 through {max_conf_label}. Each rank gets used exactly once, so a perfect week is <b>{max_pts}</b>.</li>
      <li><b>Highest score bonus.</b> Closest guess to the week's single best team score: <b>+{bonus}</b>.</li>
      <li><b>Smallest margin bonus.</b> Closest guess to the week's narrowest margin of victory: <b>+{bonus}</b>.</li>
      <li><b>Ties pay everyone.</b> If two of you are equally close on a bonus, you both get it.</li>
      <li><b>A tied fantasy matchup pays nobody</b> &mdash; there's no winner to have called.</li>
      <li><b>One card per owner per week.</b> Resubmit as many times as you like before the lock; the last one counts. After the lock nothing can be written.</li>
    </ul>
  </section>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/firebase/10.14.1/firebase-app-compat.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/firebase/10.14.1/firebase-firestore-compat.min.js"></script>
<script>window.BOARD = {config}; window.FIREBASE_CONFIG = {firebase};</script>
<script src="js/board.js"></script>
'''


# ------------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description="Beat the Board — build board.html")
    ap.add_argument("season", nargs="?", type=int, default=2026)
    ap.add_argument("--rules", action="store_true", help="print the Firestore rules block")
    ap.add_argument("--scores", action="store_true", help="print the leaderboard, write nothing")
    ap.add_argument("--refresh-locks", action="store_true", help="re-fetch kickoff times")
    a = ap.parse_args(argv)

    if a.rules:
        print(rules_block(a.season))
        return
    if a.scores:
        sl = slates(a.season)
        res = {w: r for w, r in ((w, results(s)) for w, s in sl.items()) if r}
        lb = leaderboard(sl, res, fetch_picks())
        print(f"open week {open_week(sl, res)} · scored {lb['weeks']}")
        for i, r in enumerate(lb["rows"], 1):
            print(f"{i:>2}. {r['first']:<10} {r['total']:>4} pts  "
                  f"({r['played']} wks, {r['hits']} hits, {r['bonus']} bonus)")
        return

    out, wk, lb = build(a.season, refresh_locks=a.refresh_locks)
    print(f"wrote {out.relative_to(ROOT)} — open week {wk}, scored {lb['weeks'] or 'none'}")


if __name__ == "__main__":
    main()
