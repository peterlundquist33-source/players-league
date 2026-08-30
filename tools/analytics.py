"""Auto-compute the Expected Wins / luck / schedule / PF-PA tables from ESPN
results and drop them into analytics.html between the XWINS markers.

Expected wins = all-play: each week your score is compared to every other team,
not just your opponent. Beat 8 of 11 -> +8/11 expected wins that week.
"""
import re
from lib import espn, load_env, ROOT

START = "<!-- XWINS:start -->"
END = "<!-- XWINS:end -->"


def _name(s):
    return " ".join(("CJ" if p.lower() == "cj" else p[:1].upper() + p[1:].lower())
                    for p in (s or "").split())


def compute(season):
    d = espn(["mMatchupScore", "mTeam"], season)
    members = {m["id"]: _name(f'{m.get("firstName","")} {m.get("lastName","")}')
               for m in d.get("members", [])}
    teams = {}
    for t in d.get("teams", []):
        owner = (members.get(t.get("primaryOwner"))
                 or members.get((t.get("owners") or [None])[0]) or (t.get("name") or ""))
        teams[t["id"]] = {"owner": owner, "team": (t.get("name") or "").strip()}
    n = len(teams)

    week_scores, week_opp, week_result = {}, {}, {}
    for s in d.get("schedule", []):
        wk = s.get("matchupPeriodId")
        h, a = s.get("home"), s.get("away")
        if not h or not a:
            continue
        hp = round(h.get("totalPoints", 0.0), 2)
        ap = round(a.get("totalPoints", 0.0), 2)
        if hp == 0 and ap == 0:
            continue                      # not played yet
        ws = week_scores.setdefault(wk, {})
        ws[h["teamId"]], ws[a["teamId"]] = hp, ap
        wo = week_opp.setdefault(wk, {})
        wo[h["teamId"]], wo[a["teamId"]] = a["teamId"], h["teamId"]
        wr = week_result.setdefault(wk, {})
        wr[h["teamId"]] = "W" if hp > ap else "L" if hp < ap else "T"
        wr[a["teamId"]] = "W" if ap > hp else "L" if ap < hp else "T"

    weeks = sorted(w for w, sc in week_scores.items() if len(sc) == n)

    st = {tid: {"xw": 0.0, "aw": 0.0, "pf": 0.0, "pa": 0.0,
                "opp_allplay": 0.0, "gp": 0} for tid in teams}
    pf_grid = {tid: {} for tid in teams}
    pa_grid = {tid: {} for tid in teams}

    for wk in weeks:
        sc = week_scores[wk]
        for tid, s in sc.items():
            beat = sum(1 for o, os in sc.items() if o != tid and s > os)
            tie = sum(1 for o, os in sc.items() if o != tid and s == os)
            st[tid]["xw"] += (beat + 0.5 * tie) / (n - 1)
            r = week_result[wk][tid]
            st[tid]["aw"] += 1.0 if r == "W" else 0.5 if r == "T" else 0.0
            st[tid]["pf"] += s
            st[tid]["gp"] += 1
            pf_grid[tid][wk] = s
            opp = week_opp[wk][tid]
            opp_s = sc[opp]
            st[tid]["pa"] += opp_s
            pa_grid[tid][wk] = opp_s
            opp_beat = sum(1 for o, os in sc.items() if o != opp and opp_s > os)
            opp_tie = sum(1 for o, os in sc.items() if o != opp and opp_s == os)
            st[tid]["opp_allplay"] += opp_beat + 0.5 * opp_tie   # 0..(n-1)

    # schedule swap — A's weekly scores run through every other team's slate
    swap = {}
    for a in teams:
        swap[a] = {}
        for b in teams:
            w = l = tie = 0
            for wk in weeks:
                opp = week_opp[wk][b]
                if opp == a:            # b played a that week -> a now plays b
                    opp = b
                sa, so = week_scores[wk][a], week_scores[wk][opp]
                if sa > so:
                    w += 1
                elif sa < so:
                    l += 1
                else:
                    tie += 1
            swap[a][b] = (w, l, tie)

    rows = []
    for tid, t in teams.items():
        s = st[tid]
        gp = s["gp"]
        recs = swap[tid]
        actual = recs[tid]
        by_wins = sorted(teams, key=lambda b: (recs[b][0], -recs[b][1]))
        best_b, worst_b = by_wins[-1], by_wins[0]
        avg_w = sum(recs[b][0] for b in teams) / n if n else 0
        rows.append({
            "owner": t["owner"], "team": t["team"], "tid": tid,
            "gp": gp,
            "xw": round(s["xw"], 1), "aw": round(s["aw"], 1),
            "luck": round(s["aw"] - s["xw"], 1),
            "pf": round(s["pf"], 1), "pa": round(s["pa"], 1),
            "sched": round(s["opp_allplay"] / gp, 2) if gp else None,
            "pf_by_week": pf_grid[tid], "pa_by_week": pa_grid[tid],
            "actual_rec": actual,
            "swap": {b: recs[b] for b in teams},
            "swap_avg_w": round(avg_w, 1),
            "swap_best": (teams[best_b]["owner"], recs[best_b]),
            "swap_worst": (teams[worst_b]["owner"], recs[worst_b]),
        })
    rows.sort(key=lambda r: -r["luck"])
    order = [r["tid"] for r in sorted(rows, key=lambda r: r["owner"])]
    return {"season": season, "weeks": weeks, "n": n, "rows": rows,
            "swap_order": order, "team_owner": {tid: t["owner"] for tid, t in teams.items()}}


# ---------------------------------------------------------------- render

def _pill(luck):
    if luck >= 0.5:
        return f'<span class="pill-luck pos">+{luck:.1f} 🍀</span>'
    if luck <= -0.5:
        return f'<span class="pill-luck neg">{luck:.1f} 💀</span>'
    return f'<span class="pill-luck neu">{luck:+.1f}</span>'


def _grid(rows, key, weeks):
    """PF or PA week-by-week table with weekly high (green) / low (red)."""
    hdr = "".join(f"<th>{w}</th>" for w in weeks)
    body = ""
    # weekly extremes
    hi = {w: max(r[key].get(w, -1) for r in rows) for w in weeks}
    lo = {w: min((r[key][w] for r in rows if w in r[key]), default=1e9) for w in weeks}
    srt = sorted(rows, key=lambda r: -sum(r[key].values()))
    for r in srt:
        cells = ""
        for w in weeks:
            v = r[key].get(w)
            if v is None:
                cells += "<td>—</td>"
            else:
                cls = ' class="pf-high"' if v == hi[w] else ' class="pf-low"' if v == lo[w] else ""
                cells += f'<td{cls}>{v:.1f}</td>'
        tot = sum(r[key].values())
        body += (f'<tr><td style="font-weight:600;color:var(--text);">{r["owner"]}</td>'
                 f'{cells}<td style="font-weight:700;">{tot:.1f}</td></tr>')
    return (f'<table class="data-table sticky-first" style="font-size:0.8rem;min-width:640px;">'
            f'<thead><tr><th>Owner</th>{hdr}<th>Tot</th></tr></thead><tbody>{body}</tbody></table>')


def _rec(t):
    w, l, tie = t
    return f'{w}-{l}' + (f'-{tie}' if tie else '')


def _swap_section(a):
    rows, order, owner = a["rows"], a["swap_order"], a["team_owner"]
    by_tid = {r["tid"]: r for r in rows}
    fn = {tid: owner[tid].split()[0] for tid in order}   # first names for headers

    # summary
    summ = ('<h3 style="color:var(--accent);font-size:1.05rem;margin:2rem 0 .4rem;">'
            'Schedule Swap</h3>'
            '<p class="section-sub">Everyone\'s weekly scores, run through every other '
            'team\'s schedule. Your real record is the diagonal.</p>'
            '<div class="table-scroll" style="overflow-x:auto;"><table class="data-table sticky-first">'
            '<thead><tr><th>Owner</th><th>Actual</th><th>Avg W (of 12 schedules)</th>'
            '<th>Best case</th><th>Worst case</th></tr></thead><tbody>')
    for r in sorted(rows, key=lambda r: (-r["actual_rec"][0], r["actual_rec"][1])):
        bo, brec = r["swap_best"]; wo, wrec = r["swap_worst"]
        summ += (f'<tr><td style="font-weight:600;color:var(--text);">{r["owner"]}</td>'
                 f'<td style="font-weight:700;">{_rec(r["actual_rec"])}</td>'
                 f'<td>{r["swap_avg_w"]:.1f}</td>'
                 f'<td><span style="color:var(--green);">{_rec(brec)}</span> '
                 f'<span style="color:var(--text-muted);font-size:.85em;">({bo}\'s)</span></td>'
                 f'<td><span style="color:var(--red);">{_rec(wrec)}</span> '
                 f'<span style="color:var(--text-muted);font-size:.85em;">({wo}\'s)</span></td></tr>')
    summ += '</tbody></table></div>'

    # full matrix — rows = whose scores, cols = whose schedule
    hdr = "".join(f'<th title="{owner[b]}">{fn[b]}</th>' for b in order)
    body = ""
    for a_tid in order:
        r = by_tid[a_tid]
        actual_w = r["actual_rec"][0]
        cells = ""
        for b_tid in order:
            w, l, tie = r["swap"][b_tid]
            if a_tid == b_tid:
                cells += f'<td style="background:var(--surface-3);font-weight:800;color:var(--text);">{w}-{l}</td>'
            else:
                col = "var(--green)" if w > actual_w else "var(--red)" if w < actual_w else "var(--text-muted)"
                cells += f'<td style="color:{col};">{w}-{l}</td>'
        body += (f'<tr><td style="font-weight:600;color:var(--text);">{r["owner"]}</td>{cells}</tr>')
    matrix = ('<p class="section-sub" style="margin-top:1rem;">Full grid — row = whose '
              'scores, column = whose schedule. Green = better than their real record, '
              'red = worse.</p>'
              f'<div class="table-scroll" style="overflow-x:auto;">'
              f'<table class="data-table sticky-first" style="font-size:0.78rem;min-width:720px;">'
              f'<thead><tr><th>Scores \\ Schedule</th>{hdr}</tr></thead><tbody>{body}</tbody></table></div>')
    return summ + matrix


def render_html(a):
    season, weeks, rows = a["season"], a["weeks"], a["rows"]
    played = len(weeks)
    head = (f'<h2 class="section-title">📊 Expected Wins Analysis</h2>'
            f'<div class="gold-line"></div>'
            f'<p class="section-sub">Every week your score is measured against <strong>all '
            f'{a["n"] - 1} other teams</strong>, not just your opponent — that\'s Expected '
            f'Wins. Actual wins minus expected = luck. '
            + (f'Through Week {weeks[-1]}, {season} season.'
               if played else
               f'No games played yet — this fills in automatically after Week 1, {season}.')
            + '</p>')

    if not played:
        tbl = ('<div class="table-scroll" style="overflow-x:auto;"><table class="data-table">'
               '<thead><tr><th>#</th><th>Owner</th><th>Team</th><th>Exp W</th><th>Actual W</th>'
               '<th>Luck</th></tr></thead><tbody>'
               + "".join(f'<tr><td><span class="rank-num">{i}</span></td>'
                         f'<td style="font-weight:600;color:var(--text);">{r["owner"]}</td>'
                         f'<td style="color:var(--text-muted);">{r["team"]}</td>'
                         f'<td>0.0</td><td>0.0</td><td><span class="pill-luck neu">0.0</span></td></tr>'
                         for i, r in enumerate(sorted(rows, key=lambda r: r["owner"]), 1))
               + '</tbody></table></div>')
        return f'{START}\n  <!-- generated by tools/analytics.py — do not hand-edit -->\n' \
               f'  <section id="tab-xwins" class="section analytics-section active">\n' \
               f'  {head}\n  {tbl}\n  </section>\n  {END}'

    main = ('<div class="table-scroll" style="overflow-x:auto;"><table class="data-table sticky-first">'
            '<thead><tr><th>#</th><th>Owner</th><th>Exp W</th><th>Actual W</th><th>PF</th>'
            '<th>PA</th><th>Luck</th></tr></thead><tbody>')
    for i, r in enumerate(rows, 1):
        main += (f'<tr><td><span class="rank-num">{i}</span></td>'
                 f'<td style="font-weight:600;color:var(--text);">{r["owner"]}</td>'
                 f'<td>{r["xw"]:.1f}</td><td>{r["aw"]:.1f}</td>'
                 f'<td>{r["pf"]:.1f}</td><td>{r["pa"]:.1f}</td><td>{_pill(r["luck"])}</td></tr>')
    main += "</tbody></table></div>"

    sd = sorted((r for r in rows if r["sched"] is not None), key=lambda r: -r["sched"])
    sched = ('<h3 style="color:var(--accent);font-size:1.05rem;margin:2rem 0 .4rem;">Schedule Difficulty</h3>'
             '<p class="section-sub">Average all-play wins your opponents would have earned. '
             'Higher = easier slate, lower = tougher.</p>'
             '<div class="table-scroll" style="overflow-x:auto;"><table class="data-table sticky-first">'
             '<thead><tr><th>Owner</th><th>Avg Wins Faced</th><th></th></tr></thead><tbody>')
    for j, r in enumerate(sd):
        tag = ("Easiest" if j == 0 else "Hardest" if j == len(sd) - 1 else "")
        col = "var(--green)" if j == 0 else "var(--red)" if j == len(sd) - 1 else "var(--text-muted)"
        sched += (f'<tr><td style="font-weight:600;color:var(--text);">{r["owner"]}</td>'
                  f'<td>{r["sched"]:.2f}</td><td style="color:{col};">{tag}</td></tr>')
    sched += "</tbody></table></div>"

    pf = ('<h3 style="color:var(--accent);font-size:1.05rem;margin:2rem 0 .4rem;">Points For — by week</h3>'
          '<div class="table-scroll" style="overflow-x:auto;">' + _grid(rows, "pf_by_week", weeks) + '</div>')
    pa = ('<h3 style="color:var(--accent);font-size:1.05rem;margin:2rem 0 .4rem;">Points Against — by week</h3>'
          '<div class="table-scroll" style="overflow-x:auto;">' + _grid(rows, "pa_by_week", weeks) + '</div>')

    swap = _swap_section(a)

    return (f'{START}\n  <!-- generated by tools/analytics.py — do not hand-edit -->\n'
            f'  <section id="tab-xwins" class="section analytics-section active">\n'
            f'  {head}\n  {main}\n  {sched}\n  {swap}\n  {pf}\n  {pa}\n  </section>\n  {END}')


def update(season):
    load_env()
    f = ROOT / "analytics.html"
    src = f.read_text()
    block = render_html(compute(season))
    if START in src and END in src:
        new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, src, flags=re.S)
    else:
        new = re.sub(r'  <section id="tab-xwins"[^\0]*?\n  </section>\n', block + "\n", src, count=1, flags=re.S)
    if new != src:
        f.write_text(new); print("analytics.html expected-wins updated")
    else:
        print("analytics.html unchanged")


if __name__ == "__main__":
    import sys, json
    load_env()
    a = compute(int(sys.argv[1]) if len(sys.argv) > 1 else 2026)
    print(json.dumps({k: v for k, v in a.items() if k != "rows"}, indent=2))
    for r in a["rows"]:
        print(f'  {r["owner"]:<12} xw {r["xw"]:.1f}  aw {r["aw"]:.1f}  luck {r["luck"]:+.1f}  gp {r["gp"] if "gp" in r else r["gp"]}')
