"""Weekly podcast prep — builds a CSV shaped like the host's Google Sheet template.

Sections: Award Predictions · Power Rankings · Matchups (auto-assigned to NFL time
slots) with a pun team-name and a prediction blurb for each, written in the host's
voice. Reference notes appended below the grid.

    python3 tools/podcast.py [week] [--season 2026] [--dry]
"""
import csv, datetime, io, json, sys, urllib.request
from lib import ROOT, load_env, claude
import league as L
import draft as D

VOICE = """\
The host's voice: casual, crude, extremely online, lowercase-leaning, big hype energy,
lives for puns on team names and player names. Real lines of his:
- "This week is going to leave noah FIENDING for his first win. I'll take John."
- "It's going to be easy as a b c d e f g h i j k L for CJ this week."
- "I think Christian is going to get stuck in the laundry machine and say OMG as he
   gets pummelled by the Basement of KK."
- "Something tells me this matchup could be messy. Which means it could use a bath..
   You know what lives in a bath? Rubber ducky's."
- "we all know dougs a teacher, and Kaleb is going to be the student this week."
- "Mitch's roster makes me horny babayyyy. I got Ashton Powers getting hot early."
He calls Isaac "Doug". Keep it PG-13-ish but let it be crude. Punchy. 1-3 sentences.
"""

SLOTS = ["Thursday Night", "Friday Night Brazil", "Sunday Noon",
         "Sunday Afternoon", "Sunday Night", "Monday Night"]


# ---------------------------------------------------------------- NFL schedule

def _nfl_week(season, week):
    """{team_abbr: slot} plus [(slot, away, home), ...] for the NFL week."""
    url = (f"https://cdn.espn.com/core/nfl/schedule?xhr=1&year={season}"
           f"&week={week}&seasontype=2")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=25))
    out, games = {}, []
    for daykey, day in sorted(d["content"]["schedule"].items()):
        wd = datetime.datetime.strptime(daykey, "%Y%m%d").weekday()   # Mon=0
        for g in day.get("games", []):
            c = g["competitions"][0]
            tm = {x["homeAway"]: x["team"]["abbreviation"] for x in c["competitors"]}
            et = (datetime.datetime.fromisoformat(g["date"].replace("Z", "+00:00"))
                  - datetime.timedelta(hours=4))
            if wd == 0:
                slot = "Monday Night"
            elif wd in (2, 3):
                slot = "Thursday Night"
            elif wd in (4, 5):
                slot = "Friday Night Brazil"
            elif et.hour < 15:
                slot = "Sunday Noon"
            elif et.hour < 18 or (et.hour == 18 and et.minute < 30):
                slot = "Sunday Afternoon"
            else:
                slot = "Sunday Night"
            games.append((slot, tm.get("away"), tm.get("home")))
            out[tm.get("away")] = slot
            out[tm.get("home")] = slot
    return out, games


from lore import rivalry_between

# most prestigious -> least. The best fantasy matchup gets prime time.
_SLOT_PRIORITY = ["Sunday Night", "Monday Night", "Thursday Night",
                  "Friday Night Brazil", "Sunday Afternoon", "Sunday Noon"]


def _interest(m, roster_score):
    """How much this fantasy matchup matters to the league -> higher = primetime."""
    a, h = m["away"], m["home"]
    pa = a.get("optimal_proj", 0) or 0
    ph = h.get("optimal_proj", 0) or 0
    qa = roster_score.get(a["owner"], 60)
    qh = roster_score.get(h["owner"], 60)
    wins = lambda r: int(str(r).split("-")[0]) if r else 0
    score = 0.0
    score += 1.4 * (qa + qh)                 # both teams good = the main driver
    score -= 1.3 * abs(pa - ph)              # blowouts are a little boring
    score += 0.20 * (pa + ph)                # shootout potential
    score += 30 if rivalry_between(a["owner_full"], h["owner_full"]) else 0
    score += 7 * (wins(a["record"]) + wins(h["record"]))   # in-season: standings weight
    return score


def _assign_slots(matchups, roster_score, have_friday):
    """Rank matchups by interest, map best -> best slot."""
    slots = [s for s in _SLOT_PRIORITY if s != "Friday Night Brazil" or have_friday]
    ranked = sorted(range(len(matchups)),
                    key=lambda i: -_interest(matchups[i], roster_score))
    assigned = {}
    for k, i in enumerate(ranked):
        assigned[i] = slots[k] if k < len(slots) else "Sunday Noon"
    return assigned


# ---------------------------------------------------------------- Claude bits

_SERIOUS = ("OUT", "DOUBTFUL", "INJURY_RESERVE", "IR", "SUSPENSION", "PUP")


def _hurt(p):
    return p.get("injury", "").upper() in _SERIOUS


def _starters_by_proj(side):
    """Best realistic starting core (1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX), proj desc."""
    pool = sorted((p for p in side["players"] if p["pos"] in ("QB", "RB", "WR", "TE")),
                  key=lambda x: -x["proj"])
    need = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
    core, used = [], set()
    for p in pool:
        if need.get(p["pos"], 0):
            core.append(p); used.add(id(p)); need[p["pos"]] -= 1
    for p in pool:                     # FLEX
        if id(p) not in used and p["pos"] in ("RB", "WR", "TE"):
            core.append(p); break
    return sorted(core, key=lambda x: -x["proj"])


def _key_players(side, k=4):
    out = []
    for p in _starters_by_proj(side)[:k]:
        tag = f' [{p["injury"][:1].upper()}]' if _hurt(p) else ""
        out.append(f'{p["name"]} ({p["pos"]}-{p["pro"]}, {p["proj"]:.0f}){tag}')
    return out


def _matchup_writeup(matchups, assigned, week):
    """One Claude call -> per matchup: pun names, x-factor, 3 talking points, prediction."""
    blocks = []
    for i, m in enumerate(matchups):
        a, h = m["away"], m["home"]
        blocks.append(
            f'MATCHUP {i} — {assigned.get(i, "Sunday Noon")}\n'
            f'  {a["owner"]} ("{a["team"]}", {a["record"]}) proj {a.get("optimal_proj",0):.0f} — '
            f'key: {", ".join(_key_players(a))}\n'
            f'  {h["owner"]} ("{h["team"]}", {h["record"]}) proj {h.get("optimal_proj",0):.0f} — '
            f'key: {", ".join(_key_players(h))}')
    sys = VOICE + """

For EACH matchup, output EXACTLY these lines (keep the tags, one blank line between matchups):
NICK <i>: <away pun team-name> || <home pun team-name>
XFACTOR <i>: <one player name> — <half-sentence why this player swings it>
POINT <i>: <a talking point, 1 sentence, something to actually say on the mic>
POINT <i>: <another talking point>
POINT <i>: <a third talking point>
PRED <i>: <your pick to win + 2-3 sentences of reasoning and jokes, host voice>

Pun team-names riff on the manager's best player or real team name, short. The
talking points are the stuff you'd bring up previewing the game — a specific player
edge, a boom/bust guy, a bad matchup, whatever. Nothing before or after."""
    user = f"Week {week}. Preview these {len(matchups)} matchups.\n\n" + "\n\n".join(blocks)
    raw = claude(sys, user, max_tokens=2600)

    nick, xf, pred = {}, {}, {}
    pts = {i: [] for i in range(len(matchups))}
    for line in raw.splitlines():
        s = line.strip()
        u = s.upper()
        try:
            if u.startswith("NICK"):
                n, _, rest = s[4:].partition(":")
                l, r = rest.split("||")
                nick[int(n)] = (l.strip(), r.strip())
            elif u.startswith("XFACTOR"):
                n, _, rest = s[7:].partition(":")
                xf[int(n)] = rest.strip()
            elif u.startswith("POINT"):
                n, _, rest = s[5:].partition(":")
                pts[int(n)].append(rest.strip())
            elif u.startswith("PRED"):
                n, _, rest = s[4:].partition(":")
                pred[int(n)] = rest.strip()
        except (ValueError, KeyError):
            pass
    return nick, xf, pts, pred


def _awards(g, season):
    lines = []
    for t in g["teams"]:
        for p in sorted(t["picks"], key=lambda p: p["overall"]):
            if p["counts"]:
                lines.append(f'  {p["name"]} ({p["pos"]}, {p.get("pro","?")}) — '
                             f'{t["owner"]}, round {p["round"]}')
    sys = VOICE + """

Pick the league's preseason award predictions. Output EXACTLY these 5 lines:
MVP: <player> | <owner> | <one crude/funny sentence>
ROY: <rookie player> | <owner> | <one sentence>
COMEBACK: <player> | <owner> | <one sentence>
BUST: <player> | <owner> | <one sentence>
SLEEPER: <late-round player> | <owner> | <one sentence>
Nothing else. MVP = best overall player in the league. SLEEPER should be a genuine
mid/late-round pick. BUST should be an early pick you don't trust."""
    raw = claude(sys, "Every skill player drafted this year:\n" + "\n".join(lines),
                 max_tokens=700)
    out = {}
    for line in raw.splitlines():
        for key in ("MVP", "ROY", "COMEBACK", "BUST", "SLEEPER"):
            if line.strip().upper().startswith(key + ":"):
                parts = [x.strip() for x in line.split(":", 1)[1].split("|")]
                if len(parts) >= 3:
                    out[key] = parts[:3]
    return out


def _power(g, league, week):
    if week <= 1 or not any(t.get("record", "0-0") != "0-0" for t in league["standings"]):
        board = "\n".join(f'{t["owner"]}: draft score {t["score"]}/100 ({t["grade"]}), '
                          f'roster {t["roster_score"]:.0f}' for t in g["teams"])
        basis = "preseason — base it on roster strength / draft grade"
    else:
        board = "\n".join(f'{s["owner"]}: {s["record"]}, {s["pf"]:.0f} PF, {s["pa"]:.0f} PA, '
                          f'streak {s.get("streak","")}' for s in league["standings"])
        basis = f"through week {week - 1} — record, points, and form"
    sys = VOICE + f"""

Rank all 12 teams 1 (best) to 12 (worst), {basis}. Output EXACTLY 12 lines:
<rank>. <owner> | <one short punchy sentence>
Nothing else."""
    raw = claude(sys, board, max_tokens=900)
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if line[:2].strip().rstrip(".").isdigit() and "|" in line:
            num, rest = line.split(".", 1)
            name, note = rest.split("|", 1)
            rows.append((int(num), name.strip(), note.strip()))
    return sorted(rows)[:12]


# ---------------------------------------------------------------- CSV

def build_csv(season, week, dry=False):
    load_env()
    lg = L.build(season, week, "preview")
    week = lg["week"]
    ms = lg["matchups"]
    g = D.build(season)

    team_slot, games = _nfl_week(season, week)
    have_friday = any(s == "Friday Night Brazil" for s, _, _ in games)
    playing = set(team_slot)               # NFL teams with a game this week
    roster_score = {t["owner"]: t["roster_score"] for t in g["teams"]}
    assigned = _assign_slots(ms, roster_score, have_friday)

    # flavor only: the single NFL game each matchup has the most points riding on
    nfl_game = {}
    for i, m in enumerate(ms):
        best = None
        for s, aw, hm in games:
            pts = sum(p["proj"] for side in (m["away"], m["home"]) for p in side["players"]
                      if p["pro"] in (aw, hm))
            if best is None or pts > best[0]:
                best = (pts, f"{aw} @ {hm}")
        nfl_game[i] = best[1] if best else ""

    if dry:
        nick = {i: (f'{m["away"]["owner"]}co', f'{m["home"]["owner"]}co') for i, m in enumerate(ms)}
        xf = {i: "[dry]" for i in range(len(ms))}
        pts = {i: ["[dry] point"] for i in range(len(ms))}
        pred = {i: "[dry] pick TBD" for i in range(len(ms))}
        awards = {k: ["TBD", "TBD", "[dry]"] for k in ("MVP", "ROY", "COMEBACK", "BUST", "SLEEPER")}
        power = [(i + 1, t["owner"], "[dry]") for i, t in enumerate(g["teams"])]
    else:
        nick, xf, pts, pred = _matchup_writeup(ms, assigned, week)
        awards = _awards(g, season)
        power = _power(g, lg, week)

    def proj(side):
        return side.get("optimal_proj", 0) or 0

    # ---- players & notes to watch (computed) ----
    all_starters = [(p, side["owner"]) for m in ms for side in (m["away"], m["home"])
                    for p in _starters_by_proj(side)]
    top_proj = sorted(all_starters, key=lambda x: -x[0]["proj"])[:6]
    byes = [(p["name"], p["pos"], own) for p, own in all_starters
            if p["pro"] not in playing and p["pro"] != "?"]
    hurt = [(p["name"], p["pos"], p["injury"], own) for p, own in all_starters if _hurt(p)]

    gaps = sorted(ms, key=lambda m: abs(proj(m["away"]) - proj(m["home"])))
    closest, blowout = gaps[0], gaps[-1]
    loaded = max(ms, key=lambda m: max(proj(m["away"]), proj(m["home"])))
    ld_side = loaded["away"] if proj(loaded["away"]) >= proj(loaded["home"]) else loaded["home"]

    R = []                       # rows: list of cells
    def sec(title):
        R.extend([[], [title], []])

    R.append([f"PLAYERS LEAGUE PODCAST  —  WEEK {week} RUNDOWN"])
    R.append([f"generated {datetime.date.today().isoformat()}  ·  "
              f"{len(ms)} matchups  ·  season {season}"])

    sec("1  ·  WELCOME BACK")
    R.append(["", "Guest", ""])
    R.append(["", "Cold open / notes", ""])
    R.append(["", "This week's storylines", ""])
    R.append(["", "", f'Closest game: {closest["away"]["owner"]} vs {closest["home"]["owner"]} '
              f'(~{abs(proj(closest["away"]) - proj(closest["home"])):.0f} pts apart)'])
    R.append(["", "", f'Biggest mismatch: {blowout["away"]["owner"]} vs {blowout["home"]["owner"]} '
              f'(~{abs(proj(blowout["away"]) - proj(blowout["home"])):.0f} pts)'])
    R.append(["", "", f'Most loaded roster: {ld_side["owner"]} (~{proj(ld_side):.0f} projected)'])

    sec("2  ·  AWARD PREDICTIONS")
    R.append(["", "Award", "Pick", "Owner", "Why"])
    for key, lbl in [("MVP", "Fantasy MVP"), ("ROY", "Rookie of the Year"),
                     ("COMEBACK", "Comeback Player"), ("BUST", "Bust"),
                     ("SLEEPER", "Sleeper")]:
        a = awards.get(key, ["", "", ""])
        R.append(["", lbl, a[0], a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else ""])

    sec("3  ·  POWER RANKINGS")
    R.append(["", "#", "Team", "Owner", "Take"])
    owners_team = {t["owner"]: t["team"] for t in g["teams"]}
    for rank, owner_, note in power:
        R.append(["", rank, owners_team.get(owner_, ""), owner_, note])

    sec("4  ·  PLAYERS & NOTES TO WATCH")
    R.append(["", "Highest projected this week", ""])
    for p, own in top_proj:
        R.append(["", "", f'{p["name"]} — {p["pos"]}, {p["pro"]}, {p["proj"]:.0f} pts ({own})'])
    R.append(["", "On bye (starter down)", ", ".join(
        f'{n} ({pos}, {own})' for n, pos, own in byes) or "none"])
    R.append(["", "Banged up", ", ".join(
        f'{n} ({pos} — {st}, {own})' for n, pos, st, own in hurt) or "none flagged"])

    sec("5  ·  MATCHUPS   (best games get prime time, snoozers get Sunday noon)")
    tier = {"Sunday Night": "marquee game of the week", "Monday Night": "primetime",
            "Thursday Night": "primetime", "Friday Night Brazil": "quirky one",
            "Sunday Afternoon": "solid undercard", "Sunday Noon": "snoozer"}
    order = sorted(range(len(ms)),
                   key=lambda i: _SLOT_PRIORITY.index(assigned.get(i, "Sunday Noon")))
    for n, i in enumerate(order, 1):
        m = ms[i]
        a, h = m["away"], m["home"]
        na, nh = nick.get(i, (a["team"], h["team"]))
        fav = a["owner"] if proj(a) >= proj(h) else h["owner"]
        slot = assigned.get(i, "Sunday Noon")
        R.append([f"GAME {n}", slot, f"({tier.get(slot, '')})", f"proj favorite: {fav}",
                  f"biggest NFL game: {nfl_game.get(i, '')}"])
        R.append(["", f'{na}', a["owner"], f'{proj(a):.0f} proj · {a["record"]}',
                  "  |  ".join(_key_players(a, 4))])
        R.append(["", f'{nh}', h["owner"], f'{proj(h):.0f} proj · {h["record"]}',
                  "  |  ".join(_key_players(h, 4))])
        R.append(["", "X-factor", xf.get(i, "")])
        for pt in pts.get(i, []):
            R.append(["", "talk about", pt])
        R.append(["", "PREDICTION", pred.get(i, "")])
        R.append([])

    sec("6  ·  HOT SEAT")
    R.append(["", "(starts with the Week 4 podcast)"])

    sec("REFERENCE  ·  raw matchup data")
    R.append(["", "Matchup", "NFL slot", "Proj", "NFL game"])
    for i, m in enumerate(ms):
        a, h = m["away"], m["home"]
        R.append(["", f'{a["owner"]} vs {h["owner"]}', assigned.get(i, ""),
                  f'{proj(a):.0f}-{proj(h):.0f}', nfl_game.get(i, "")])

    out = io.StringIO()
    w = csv.writer(out)
    for row in R:
        w.writerow(row)
    text = out.getvalue()

    path = ROOT / "podcast" / f"{season}-week-{week:02d}.csv"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    print(f"wrote {path.relative_to(ROOT)}")
    return path


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    season = 2026
    if "--season" in sys.argv:
        season = int(sys.argv[sys.argv.index("--season") + 1])
    wk = int(args[0]) if args else None
    load_env()
    lg = L.build(season, wk, "preview")
    build_csv(season, lg["week"], dry="--dry" in sys.argv)
