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


def _assign_slots(matchups, team_slot, games):
    """One NFL slot per fantasy matchup. Standalone slots (TNF/Fri/SNF/MNF) go to
    the matchup with the most projected points invested there; the rest split
    across Sunday Noon / Afternoon."""
    have = {s for s, _, _ in games}
    by_mx = []
    for m in matchups:
        d = {}
        for side in (m["away"], m["home"]):
            for p in side["players"]:
                s = team_slot.get(p["pro"])
                if s:
                    d[s] = d.get(s, 0.0) + p["proj"]
        by_mx.append(d)

    assigned = {}
    for slot in ("Thursday Night", "Friday Night Brazil", "Sunday Night", "Monday Night"):
        if slot not in have:
            continue
        claims = sorted(((by_mx[i].get(slot, 0), i)
                         for i in range(len(matchups)) if i not in assigned), reverse=True)
        if claims and claims[0][0] > 0:
            assigned[claims[0][1]] = slot

    left = [i for i in range(len(matchups)) if i not in assigned]
    left.sort(key=lambda i: -(by_mx[i].get("Sunday Noon", 0) - by_mx[i].get("Sunday Afternoon", 0)))
    half = (len(left) + 1) // 2
    for k, i in enumerate(left):
        assigned[i] = "Sunday Noon" if k < half else "Sunday Afternoon"
    return assigned


# ---------------------------------------------------------------- Claude bits

def _nicknames_and_preds(matchups, assigned, week):
    blocks = []
    for i, m in enumerate(matchups):
        a, h = m["away"], m["home"]
        def top(side, k):
            return ", ".join(f'{p["name"]}' for p in sorted(
                side["players"], key=lambda x: -x["proj"])[:k])
        blocks.append(
            f'MATCHUP {i} — {assigned.get(i, "Sunday")}\n'
            f'  {a["owner"]} ("{a["team"]}", {a["record"]}) — proj {a.get("optimal_proj", 0):.0f}. '
            f'Best: {top(a, 4)}\n'
            f'  {h["owner"]} ("{h["team"]}", {h["record"]}) — proj {h.get("optimal_proj", 0):.0f}. '
            f'Best: {top(h, 4)}')
    sys = VOICE + """

For EACH matchup below, output exactly two lines:
NICK <i>: <away pun team-name> || <home pun team-name>
PRED <i>: <1-3 sentences: your pick to win + a pun/joke, host voice>

Pun team-names riff on that manager's best player or their real team name. Keep
them short. Nothing before or after. <i> is the matchup number."""
        # (note: the trailing content below is the user message)
    user = f"Week {week}. Write nicknames + predictions.\n\n" + "\n\n".join(blocks)
    raw = claude(sys, user, max_tokens=1400)
    nick, pred = {}, {}
    for line in raw.splitlines():
        line = line.strip()
        if line.upper().startswith("NICK"):
            n, _, rest = line[4:].partition(":")
            parts = rest.split("||")
            if len(parts) == 2:
                nick[int(n.strip())] = (parts[0].strip(), parts[1].strip())
        elif line.upper().startswith("PRED"):
            n, _, rest = line[4:].partition(":")
            try:
                pred[int(n.strip())] = rest.strip()
            except ValueError:
                pass
    return nick, pred


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
    assigned = _assign_slots(ms, team_slot, games)
    nfl_game = {}
    for i, m in enumerate(ms):
        slot = assigned.get(i)
        best = None
        for s, aw, hm in games:
            if s != slot:
                continue
            pts = sum(p["proj"] for side in (m["away"], m["home"]) for p in side["players"]
                      if p["pro"] in (aw, hm))
            if best is None or pts > best[0]:
                best = (pts, f"{aw} @ {hm}")
        nfl_game[i] = best[1] if best else ""

    if dry:
        nick = {i: (f'{m["away"]["owner"]}co', f'{m["home"]["owner"]}co') for i, m in enumerate(ms)}
        pred = {i: "[dry] pick TBD" for i in range(len(ms))}
        awards = {k: ["TBD", "TBD", "[dry]"] for k in ("MVP", "ROY", "COMEBACK", "BUST", "SLEEPER")}
        power = [(i + 1, t["owner"], "[dry]") for i, t in enumerate(g["teams"])]
    else:
        nick, pred = _nicknames_and_preds(ms, assigned, week)
        awards = _awards(g, season)
        power = _power(g, lg, week)

    grid = [["" for _ in range(13)] for _ in range(24)]

    def put(r, c, v):
        grid[r][c - 1] = v

    put(2, 4, "AGENDA")
    put(3, 2, "Guest:"); put(3, 3, "1"); put(3, 4, "Welcome back")
    put(4, 3, "2"); put(4, 4, "League Award Predictions")
    put(5, 3, "3"); put(5, 4, "Power Rankings")
    put(6, 3, "4"); put(6, 4, "Matchups")

    # matchups: 2 per band, 3 bands. left cols 6-8, right cols 11-13
    band_rows = [3, 10, 17]
    for band, r0 in enumerate(band_rows):
        for col0, idx in ((6, band * 2), (11, band * 2 + 1)):
            if idx >= len(ms):
                continue
            m = ms[idx]
            a, h = m["away"], m["home"]
            na, nh = nick.get(idx, (a["team"], h["team"]))
            put(r0, col0, f'{assigned.get(idx, "Sunday")} — {nfl_game.get(idx, "")}')
            put(r0 + 1, col0, f'{na} ({a["owner"]})')
            put(r0 + 1, col0 + 1, "vs.")
            put(r0 + 1, col0 + 2, f'{nh} ({h["owner"]})')
            put(r0 + 2, col0, f'proj {a.get("optimal_proj", 0):.0f}-{h.get("optimal_proj", 0):.0f}')
            put(r0 + 3, col0, "Prediction:")
            put(r0 + 4, col0, pred.get(idx, ""))

    # award table (cols 2-4), rows 17-22
    put(16, 2, "Award"); put(16, 3, "Pick"); put(16, 4, "Owner")
    for k, (lbl, r) in enumerate([("Fantasy MVP:", 17), ("Rookie of the Year:", 18),
                                  ("Comeback Player of the Year:", 19),
                                  ("Bust of the Year:", 20), ("Sleeper of the Year:", 21)]):
        key = ["MVP", "ROY", "COMEBACK", "BUST", "SLEEPER"][k]
        a = awards.get(key, ["", "", ""])
        put(r, 2, lbl); put(r, 3, a[0]); put(r, 4, a[1])

    # trailing reference sections
    extra = [[], ["POWER RANKINGS"]]
    for rank, owner_, note in power:
        extra.append([str(rank), owner_, note])
    extra += [[], ["AWARD NOTES"]]
    for key, lbl in [("MVP", "Fantasy MVP"), ("ROY", "Rookie of the Year"),
                     ("COMEBACK", "Comeback"), ("BUST", "Bust"), ("SLEEPER", "Sleeper")]:
        a = awards.get(key, ["", "", ""])
        extra.append([lbl, a[0], a[1], a[2] if len(a) > 2 else ""])
    extra += [[], ["MATCHUP DATA (reference)"]]
    for i, m in enumerate(ms):
        a, h = m["away"], m["home"]
        extra.append([f'{a["owner"]} vs {h["owner"]}', assigned.get(i, ""),
                      f'{a["optimal_proj"]:.0f}-{h["optimal_proj"]:.0f}', nfl_game.get(i, "")])

    out = io.StringIO()
    w = csv.writer(out)
    for row in grid:
        w.writerow(row)
    for row in extra:
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
