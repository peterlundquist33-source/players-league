"""Auto-compute the Expected Wins / luck / schedule / PF-PA / schedule-swap tables
(current season AND all-time) from ESPN results, and drop them into analytics.html
between the XWINS markers.

Expected wins = all-play: each week your score is compared to every other team,
not just your opponent. Schedule swap = your weekly scores run through every other
owner's slate. Everything is keyed by owner first name (stable across seasons).
"""
import re
from lib import espn, load_env, ROOT
from lore import owner

START = "<!-- XWINS:start -->"
END = "<!-- XWINS:end -->"
FIRST_SEASON = 2022


# ---------------------------------------------------------------- pull

def _pull(season):
    """One season -> per-week scores / opponents / results, keyed by owner first name."""
    d = espn(["mMatchupScore", "mTeam", "mSettings"], season)
    mpc = d.get("settings", {}).get("scheduleSettings", {}).get("matchupPeriodCount", 14)
    mem = {m["id"]: owner(f'{m.get("firstName","")} {m.get("lastName","")}')
           for m in d.get("members", [])}
    tmap, tname = {}, {}
    for t in d.get("teams", []):
        o = mem.get(t.get("primaryOwner")) or mem.get((t.get("owners") or [None])[0])
        if o:
            tmap[t["id"]] = o
            tname[o] = (t.get("name") or "").strip()

    scores, opp, result = {}, {}, {}
    for s in d.get("schedule", []):
        if s.get("matchupPeriodId", 99) > mpc or s.get("playoffTierType") not in (None, "NONE"):
            continue
        h, a = s.get("home"), s.get("away")
        if not h or not a:
            continue
        hp = round(h.get("totalPoints", 0.0), 2)
        ap = round(a.get("totalPoints", 0.0), 2)
        if hp == 0 and ap == 0:
            continue
        ho, ao = tmap.get(h["teamId"]), tmap.get(a["teamId"])
        if not ho or not ao:
            continue
        w = s["matchupPeriodId"]
        scores.setdefault(w, {}).update({ho: hp, ao: ap})
        opp.setdefault(w, {}).update({ho: ao, ao: ho})
        result.setdefault(w, {})
        result[w][ho] = "W" if hp > ap else "L" if hp < ap else "T"
        result[w][ao] = "W" if ap > hp else "L" if ap < hp else "T"

    weeks = sorted(w for w, sc in scores.items()
                   if len(sc) == len([o for o in tmap.values()]))
    return {"season": season, "weeks": weeks, "scores": scores, "opp": opp,
            "result": result, "owners": sorted(tname), "tname": tname}


# ---------------------------------------------------------------- aggregate

def _aggregate(pulls):
    """pulls = list of _pull() dicts. Returns per-owner all-play + swap stats
    pooled across every (season, week) in the list."""
    owners = sorted({o for p in pulls for o in p["owners"]})
    n = len(owners)
    keys = [(pi, w) for pi, p in enumerate(pulls) for w in p["weeks"]]

    st = {o: {"xw": 0.0, "aw": 0.0, "pf": 0.0, "pa": 0.0, "opp_allplay": 0.0, "gp": 0}
          for o in owners}
    for pi, w in keys:
        p = pulls[pi]
        sc = p["scores"][w]
        m = len(sc)
        for o, s in sc.items():
            beat = sum(1 for x, xs in sc.items() if x != o and s > xs)
            tie = sum(1 for x, xs in sc.items() if x != o and s == xs)
            st[o]["xw"] += (beat + 0.5 * tie) / (m - 1)
            r = p["result"][w][o]
            st[o]["aw"] += 1.0 if r == "W" else 0.5 if r == "T" else 0.0
            st[o]["pf"] += s
            st[o]["gp"] += 1
            op = p["opp"][w][o]
            st[o]["pa"] += sc[op]
            ob = sum(1 for x, xs in sc.items() if x != op and sc[op] > xs)
            ot = sum(1 for x, xs in sc.items() if x != op and sc[op] == xs)
            st[o]["opp_allplay"] += ob + 0.5 * ot

    swap = {a: {} for a in owners}
    for a in owners:
        for b in owners:
            wr = lr = tr = 0
            for pi, w in keys:
                p = pulls[pi]
                if a not in p["scores"][w] or b not in p["scores"][w]:
                    continue
                op = p["opp"][w][b]
                if op == a:
                    op = b
                sa, so = p["scores"][w][a], p["scores"][w][op]
                if sa > so:
                    wr += 1
                elif sa < so:
                    lr += 1
                else:
                    tr += 1
            swap[a][b] = (wr, lr, tr)

    rows = []
    for o in owners:
        s = st[o]
        gp = s["gp"]
        recs = swap[o]
        by_w = sorted(owners, key=lambda b: (recs[b][0], -recs[b][1]))
        rows.append({
            "owner": o, "gp": gp,
            "xw": round(s["xw"], 1), "aw": round(s["aw"], 1),
            "luck": round(s["aw"] - s["xw"], 1),
            "pf": round(s["pf"], 1), "pa": round(s["pa"], 1),
            "sched": round(s["opp_allplay"] / gp, 2) if gp else None,
            "actual_rec": recs[o],
            "swap": recs,
            "swap_avg_w": round(sum(recs[b][0] for b in owners) / n, 1) if n else 0,
            "swap_best": (by_w[-1], recs[by_w[-1]]),
            "swap_worst": (by_w[0], recs[by_w[0]]),
        })
    return {"owners": owners, "n": n, "rows": rows}


def compute(season):
    p = _pull(season)
    agg = _aggregate([p])
    for r in agg["rows"]:
        r["pf_by_week"] = {w: p["scores"][w][r["owner"]] for w in p["weeks"]}
        r["pa_by_week"] = {w: p["scores"][w][p["opp"][w][r["owner"]]] for w in p["weeks"]}
        r["team"] = p["tname"].get(r["owner"], "")
    agg["rows"].sort(key=lambda r: -r["luck"])
    return {"season": season, "weeks": p["weeks"], **agg}


def compute_alltime(through_season):
    pulls = []
    for yr in range(FIRST_SEASON, through_season + 1):
        try:
            pp = _pull(yr)
        except SystemExit:
            continue
        if pp["weeks"]:
            pulls.append(pp)
    if not pulls:
        return None
    agg = _aggregate(pulls)
    agg["rows"].sort(key=lambda r: -r["luck"])
    agg["seasons"] = [p["season"] for p in pulls]
    return agg


# ---------------------------------------------------------------- render

def _rec(t):
    w, l, tie = t
    return f'{w}-{l}' + (f'-{tie}' if tie else '')


def _pill(luck):
    if luck >= 0.5:
        return f'<span class="pill-luck pos">+{luck:.1f} 🍀</span>'
    if luck <= -0.5:
        return f'<span class="pill-luck neg">{luck:.1f} 💀</span>'
    return f'<span class="pill-luck neu">{luck:+.1f}</span>'


def _xw_table(rows, extra_cols=True):
    cols = ('<th>#</th><th>Owner</th><th>Exp W</th><th>Actual W</th>'
            + ('<th>PF</th><th>PA</th>' if extra_cols else '') + '<th>Luck</th>')
    b = ""
    for i, r in enumerate(rows, 1):
        mid = (f'<td>{r["pf"]:.0f}</td><td>{r["pa"]:.0f}</td>' if extra_cols else '')
        b += (f'<tr><td><span class="rank-num">{i}</span></td>'
              f'<td style="font-weight:600;color:var(--text);">{r["owner"]}</td>'
              f'<td>{r["xw"]:.1f}</td><td>{r["aw"]:.1f}</td>{mid}<td>{_pill(r["luck"])}</td></tr>')
    return ('<div class="table-scroll" style="overflow-x:auto;"><table class="data-table sticky-first">'
            f'<thead><tr>{cols}</tr></thead><tbody>{b}</tbody></table></div>')


def _grid(rows, key, weeks):
    hdr = "".join(f"<th>{w}</th>" for w in weeks)
    hi = {w: max(r[key].get(w, -1) for r in rows) for w in weeks}
    lo = {w: min((r[key][w] for r in rows if w in r[key]), default=1e9) for w in weeks}
    body = ""
    for r in sorted(rows, key=lambda r: -sum(r[key].values())):
        cells = ""
        for w in weeks:
            v = r[key].get(w)
            if v is None:
                cells += "<td>—</td>"
            else:
                cls = ' class="pf-high"' if v == hi[w] else ' class="pf-low"' if v == lo[w] else ""
                cells += f'<td{cls}>{v:.1f}</td>'
        body += (f'<tr><td style="font-weight:600;color:var(--text);">{r["owner"]}</td>'
                 f'{cells}<td style="font-weight:700;">{sum(r[key].values()):.1f}</td></tr>')
    return (f'<table class="data-table sticky-first" style="font-size:0.8rem;min-width:640px;">'
            f'<thead><tr><th>Owner</th>{hdr}<th>Tot</th></tr></thead><tbody>{body}</tbody></table>')


def _swap_section(agg, title, blurb):
    rows, owners = agg["rows"], agg["owners"]
    by_o = {r["owner"]: r for r in rows}

    summ = (f'<h3 style="color:var(--accent);font-size:1.05rem;margin:2rem 0 .4rem;">{title}</h3>'
            f'<p class="section-sub">{blurb} Your real record is the diagonal.</p>'
            '<div class="table-scroll" style="overflow-x:auto;"><table class="data-table sticky-first">'
            '<thead><tr><th>Owner</th><th>Actual</th><th>Avg W</th>'
            '<th>Best case</th><th>Worst case</th></tr></thead><tbody>')
    for r in sorted(rows, key=lambda r: (-r["actual_rec"][0], r["actual_rec"][1])):
        bo, br = r["swap_best"]
        wo, wr = r["swap_worst"]
        summ += (f'<tr><td style="font-weight:600;color:var(--text);">{r["owner"]}</td>'
                 f'<td style="font-weight:700;">{_rec(r["actual_rec"])}</td>'
                 f'<td>{r["swap_avg_w"]:.1f}</td>'
                 f'<td><span style="color:var(--green);">{_rec(br)}</span> '
                 f'<span style="color:var(--text-muted);font-size:.85em;">({bo})</span></td>'
                 f'<td><span style="color:var(--red);">{_rec(wr)}</span> '
                 f'<span style="color:var(--text-muted);font-size:.85em;">({wo})</span></td></tr>')
    summ += '</tbody></table></div>'

    hdr = "".join(f'<th>{b.split()[0]}</th>' for b in owners)
    body = ""
    for a in owners:
        r = by_o[a]
        aw = r["actual_rec"][0]
        cells = ""
        for b in owners:
            w, l, _ = r["swap"][b]
            if a == b:
                cells += f'<td style="background:var(--surface-3);font-weight:800;color:var(--text);">{w}-{l}</td>'
            else:
                c = "var(--green)" if w > aw else "var(--red)" if w < aw else "var(--text-muted)"
                cells += f'<td style="color:{c};">{w}-{l}</td>'
        body += f'<tr><td style="font-weight:600;color:var(--text);">{a}</td>{cells}</tr>'
    matrix = ('<p class="section-sub" style="margin-top:1rem;">Full grid — row = whose scores, '
              'column = whose schedule. Green = better than their real record, red = worse.</p>'
              '<div class="table-scroll" style="overflow-x:auto;">'
              '<table class="data-table sticky-first" style="font-size:0.78rem;min-width:720px;">'
              f'<thead><tr><th>Scores \\ Sched</th>{hdr}</tr></thead><tbody>{body}</tbody></table></div>')
    return summ + matrix


def render_html(cur, alltime):
    weeks, rows = cur["weeks"], cur["rows"]
    played = len(weeks)
    n = cur["n"]

    head = (f'<h2 class="section-title">📊 Expected Wins Analysis</h2><div class="gold-line"></div>'
            f'<p class="section-sub">Every week your score is measured against <strong>all '
            f'{n - 1} other teams</strong>, not just your opponent — that\'s Expected Wins. '
            f'Actual minus expected = luck. '
            + (f'Through Week {weeks[-1]}, {cur["season"]}.'
               if played else
               f'No {cur["season"]} games yet — this half fills in after Week 1.') + '</p>')

    if played:
        cur_html = (head
                    + _xw_table(rows)
                    + _sched_diff(rows)
                    + _swap_section(cur,
                                    f'Schedule Swap — {cur["season"]}',
                                    "Everyone's weekly scores this season, run through every "
                                    "other owner's schedule.")
                    + '<h3 style="color:var(--accent);font-size:1.05rem;margin:2rem 0 .4rem;">'
                    'Points For — by week</h3><div class="table-scroll" style="overflow-x:auto;">'
                    + _grid(rows, "pf_by_week", weeks) + '</div>'
                    + '<h3 style="color:var(--accent);font-size:1.05rem;margin:2rem 0 .4rem;">'
                    'Points Against — by week</h3><div class="table-scroll" style="overflow-x:auto;">'
                    + _grid(rows, "pa_by_week", weeks) + '</div>')
    else:
        ph = "".join(f'<tr><td><span class="rank-num">{i}</span></td>'
                     f'<td style="font-weight:600;color:var(--text);">{r["owner"]}</td>'
                     f'<td style="color:var(--text-muted);">{r.get("team","")}</td>'
                     f'<td>0.0</td><td>0.0</td><td><span class="pill-luck neu">0.0</span></td></tr>'
                     for i, r in enumerate(sorted(rows, key=lambda r: r["owner"]), 1))
        cur_html = (head + '<div class="table-scroll" style="overflow-x:auto;"><table class="data-table">'
                    '<thead><tr><th>#</th><th>Owner</th><th>Team</th><th>Exp W</th>'
                    '<th>Actual W</th><th>Luck</th></tr></thead><tbody>' + ph + '</tbody></table></div>')

    at_html = ""
    if alltime:
        yr0, yr1 = alltime["seasons"][0], alltime["seasons"][-1]
        at_html = (
            '<div style="border-top:2px solid var(--border);margin-top:3rem;padding-top:1.5rem;">'
            f'<h2 class="section-title">🏆 All-Time ({yr0}–{yr1})</h2><div class="gold-line"></div>'
            '<p class="section-sub">The same math pooled across every regular-season week in '
            'league history.</p>'
            '<h3 style="color:var(--accent);font-size:1.05rem;margin:1.5rem 0 .4rem;">'
            'All-Time Expected Wins &amp; Luck</h3>'
            + _xw_table(alltime["rows"])
            + _swap_section(alltime, "All-Time Schedule Swap",
                            "Every owner's weekly scores across all seasons, run through "
                            "every other owner's full schedule history.")
            + '</div>')

    return (f'{START}\n  <!-- generated by tools/analytics.py — do not hand-edit -->\n'
            f'  <section id="tab-xwins" class="section analytics-section active">\n'
            f'  {cur_html}\n  {at_html}\n  </section>\n  {END}')


def _sched_diff(rows):
    sd = sorted((r for r in rows if r["sched"] is not None), key=lambda r: -r["sched"])
    out = ('<h3 style="color:var(--accent);font-size:1.05rem;margin:2rem 0 .4rem;">Schedule Difficulty</h3>'
           '<p class="section-sub">Average all-play wins your opponents would have earned. '
           'Higher = easier slate.</p>'
           '<div class="table-scroll" style="overflow-x:auto;"><table class="data-table sticky-first">'
           '<thead><tr><th>Owner</th><th>Avg Wins Faced</th><th></th></tr></thead><tbody>')
    for j, r in enumerate(sd):
        tag = "Easiest" if j == 0 else "Hardest" if j == len(sd) - 1 else ""
        col = "var(--green)" if j == 0 else "var(--red)" if j == len(sd) - 1 else "var(--text-muted)"
        out += (f'<tr><td style="font-weight:600;color:var(--text);">{r["owner"]}</td>'
                f'<td>{r["sched"]:.2f}</td><td style="color:{col};">{tag}</td></tr>')
    return out + '</tbody></table></div>'


def update(season):
    load_env()
    f = ROOT / "analytics.html"
    src = f.read_text()
    block = render_html(compute(season), compute_alltime(season))
    if START in src and END in src:
        new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, src, flags=re.S)
    else:
        new = re.sub(r'  <section id="tab-xwins"[^\0]*?\n  </section>\n', block + "\n",
                     src, count=1, flags=re.S)
    if new != src:
        f.write_text(new)
        print("analytics.html expected-wins updated")
    else:
        print("analytics.html unchanged")


if __name__ == "__main__":
    import sys
    load_env()
    yr = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    at = compute_alltime(yr)
    print(f"all-time seasons: {at['seasons']}")
    for r in at["rows"]:
        bo, br = r["swap_best"]
        wo, wr = r["swap_worst"]
        print(f'  {r["owner"]:<10} actual {_rec(r["actual_rec"]):<7} xw {r["xw"]:5.1f} '
              f'luck {r["luck"]:+5.1f}  swap {r["swap_avg_w"]:.1f}avg  '
              f'best {_rec(br)}({bo})  worst {_rec(wr)}({wo})')
