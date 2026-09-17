"""Render generated copy + matchup data into matchups/ pages, styled like the site."""
import html, pathlib, datetime, math
from lib import ROOT
import chrome as SITE

OUT = ROOT / "matchups"


def _page(title, active, body, depth=1, page=None):
    """Shared chrome comes from chrome.py so generated pages match the static ones
    exactly; the card components (.mx-*, .gr-*, .pw-*) live in css/style.css."""
    return f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- HEAD:start -->
{SITE.head(page or "", depth, title=f"{title} — Players League")}
<!-- HEAD:end -->
</head>
<body>
<!-- NAV:start -->
{SITE.nav(active, depth)}
<!-- NAV:end -->
{body}
<!-- FOOTER:start -->
{SITE.footer()}
<!-- FOOTER:end -->
{SITE.scripts(depth)}
</body></html>'''


def _matchup_card(m, copy, phase):
    h, a = m["home"], m["away"]
    if phase == "preview":
        # no per-team score projections on previews — just the matchup
        a_pts = h_pts = ""
        a_win = h_win = False
        a_sub, h_sub = a["record"], h["record"]
    else:
        a_pts, h_pts = f'{a["actual"]:.1f}', f'{h["actual"]:.1f}'
        a_win = a["actual"] > h["actual"]
        h_win = h["actual"] > a["actual"]
        a_sub, h_sub = a["record"], h["record"]
    paras = "".join("<p>%s</p>" % html.escape(p.strip())
                    for p in copy["body"].split("\n") if p.strip())
    pick = copy.get("pick")
    if pick and phase == "preview":
        paras += ('<div class="mx-pick"><span>The Pick</span> %s by %d</div>'
                  % (html.escape(pick["owner"]), pick["margin"]))
    elif m.get("predicted"):
        p = m["predicted"]
        hit = p["owner"] == m["winner"]
        paras += ('<div class="mx-pick %s"><span>We Picked</span> %s by %d — %s</div>'
                  % ("hit" if hit else "miss", html.escape(p["owner"]), p["margin"],
                     "nailed it" if hit else "wrong"))
    a_cls = " win" if a_win else ""
    h_cls = " win" if h_win else ""
    if phase == "preview":
        mid_inner = '<div class="mx-vs">vs</div>'
    else:
        mid_inner = ('<div class="mx-pts{a_cls}">{a_pts}</div>'
                     '<div class="mx-vs">&mdash;</div>'
                     '<div class="mx-pts{h_cls}">{h_pts}</div>').format(
            a_cls=a_cls, h_cls=h_cls, a_pts=a_pts, h_pts=h_pts)
    return '''<article class="mx-card">
  <div class="mx-score">
    <div class="mx-team away">
      <span class="mx-owner">{a_owner}</span>
      <span class="mx-sub">{a_team} · {a_sub}</span>
    </div>
    <div class="mx-mid">{mid_inner}</div>
    <div class="mx-team">
      <span class="mx-owner">{h_owner}</span>
      <span class="mx-sub">{h_team} · {h_sub}</span>
    </div>
  </div>
  <div class="mx-body">
    <div class="mx-head">{head}</div>
    {paras}
  </div>
</article>'''.format(
        a_owner=html.escape(a["owner"]), a_team=html.escape(a["team"]), a_sub=a_sub,
        h_owner=html.escape(h["owner"]), h_team=html.escape(h["team"]), h_sub=h_sub,
        mid_inner=mid_inner,
        head=html.escape(copy["headline"]), paras=paras)


def week_page(league, copies, intro, stamp=None):
    wk, phase, season = league["week"], league["phase"], league["season"]
    kind = "preview" if phase == "preview" else "recap"
    badge = "Preview" if kind == "preview" else "Recap"
    cards = "\n".join(_matchup_card(m, copies[i], phase)
                      for i, m in enumerate(league["matchups"]))
    stamp = stamp or datetime.date.today().isoformat()   # a re-render keeps its original date
    body = f'''<section class="page-header" data-phase="{kind}">
  <span class="eyebrow">Matchups · {badge}</span>
  <h1>Week {wk} <span class="gold">{badge}</span></h1>
  <p>{season} season · generated {stamp}</p>
</section>
<div class="mx-wrap">
  <p class="mx-intro">{html.escape(intro)}</p>
  {cards}
</div>'''
    OUT.mkdir(exist_ok=True)
    # Previews keep their own page so Tuesday's recap doesn't overwrite Thursday's read.
    path = OUT / (f"{season}-week-{wk:02d}-preview.html" if kind == "preview"
                  else f"{season}-week-{wk:02d}.html")
    path.write_text(_page(f"Week {wk} {badge}", "Matchups", body, page=f"matchups/{path.name}"))
    return path


def _madness_card(m):
    a, h, x = m["away"], m["home"], m["madness"]
    if x["final"]:
        a_cls = " win" if m["winner"] == a["owner"] else ""
        h_cls = " win" if m["winner"] == h["owner"] else ""
        tag = '<span class="mx-badge">Final</span>'
        detail = ""
    else:
        a_cls = h_cls = ""
        tag = '<span class="mx-badge live">Alive</span>'
        rows = []
        for side, pend, win in ((a, x["away_pending"], x["away_win"]),
                                (h, x["home_pending"], x["home_win"])):
            who = (", ".join(f'{html.escape(p["name"])} ({p["pos"]} {p["pro"]}, proj {p["proj"]:g})'
                             for p in pend) or "done")
            rows.append(f'<div class="mnm-row"><span class="mnm-win">{win}%</span>'
                        f'<span class="mnm-who"><b>{html.escape(side["owner"])}</b> {who}</span></div>')
        detail = ('<div class="mnm-detail">%s<div class="mnm-need">%s trails by %g</div></div>'
                  % ("".join(rows), html.escape(x["trailer"]), x["deficit"]))
    return f'''<article class="mx-card">
  <div class="mx-score">
    <div class="mx-team away"><span class="mx-owner">{html.escape(a["owner"])}</span><span class="mx-sub">{html.escape(a["team"])}</span></div>
    <div class="mx-mid"><div class="mx-pts{a_cls}">{a["actual"]:.1f}</div>{tag}<div class="mx-pts{h_cls}">{h["actual"]:.1f}</div></div>
    <div class="mx-team home"><span class="mx-owner">{html.escape(h["owner"])}</span><span class="mx-sub">{html.escape(h["team"])}</span></div>
  </div>
  {detail}
</article>'''


def madness_page(league, post, stamp=None):
    """The Monday Night Madness page: the post (copy-ready) + a live board."""
    wk, season = league["week"], league["season"]
    stamp = stamp or datetime.date.today().isoformat()
    alive = [m for m in league["matchups"] if not m["madness"]["final"]]
    final = [m for m in league["matchups"] if m["madness"]["final"]]
    cards = "\n".join(_madness_card(m) for m in alive + final)
    modeled = any(m["madness"].get("source") == "model" for m in alive)
    note = ("Win chances are ESPN's own, the same numbers the app shows." if not modeled else
            "ESPN didn't send win chances this run, so these are the site's own: every starter "
            "still to play counts his projection with a normal spread.")
    body = f'''<section class="page-header">
  <span class="eyebrow">Matchups</span>
  <h1>Week {wk} <span class="gold">Monday Night Madness</span></h1>
  <p>{season} season · {len(alive)} alive going into Monday night · generated {stamp}</p>
</section>
<div class="mx-wrap">
  <div class="mnm-post-wrap">
    <button class="mnm-copy" type="button" data-copy="mnm-post">Copy for the group chat</button>
    <pre class="mnm-post" id="mnm-post">{html.escape(post)}</pre>
  </div>
  <h2 class="mnm-h2">The board</h2>
  <p class="mx-foot" style="margin-top:0">{note}</p>
  {cards}
</div>'''
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{season}-week-{wk:02d}-madness.html"
    path.write_text(_page(f"Week {wk} Monday Night Madness", "Matchups", body,
                          page=f"matchups/{path.name}"))
    return path


def _grade_card(t, copy):
    lo = " lo" if t["grade"][0] in "DF" else ""
    chips = "".join(
        '<span class="mx-tag">%s <b>%s</b></span>' % (pos, v["grade"])
        for pos, v in t["pos_grades"].items() if v["grade"] != "—")
    cite = ""
    if t.get("best"):
        b = t["best"]
        cite += ('<div class="mx-note">Best value: <span class="up">%s</span> '
                 '— round %s, pick %d (%+.0f vs market)</div>'
                 % (html.escape(b["name"]), b["round"], b["overall"], b["value"]))
    if t.get("reach"):
        r = t["reach"]
        cite += ('<div class="mx-note">Biggest reach: <span class="down">%s</span> '
                 '— round %s, pick %d (%+.0f)</div>'
                 % (html.escape(r["name"]), r["round"], r["overall"], r["value"]))
    paras = "".join("<p>%s</p>" % html.escape(p.strip())
                    for p in copy["body"].split("\n") if p.strip())
    return ('<article class="mx-card">'
            '<div class="mx-hd"><div class="gr-grade%s">%s'
            '<span class="gr-of">%s/100</span></div>'
            '<div><div class="mx-owner">%s</div>'
            '<div class="mx-sub">%s</div>'
            '<div class="gr-rank">#%d of 12</div></div></div>'
            '<div class="mx-tags">%s</div>'
            '%s'
            '<div class="mx-body"><div class="mx-head">%s</div>%s</div>'
            '</article>' % (
                lo, html.escape(t["grade"]), t["score"], html.escape(t["owner"]),
                html.escape(t["team"]), t["rank"], chips, cite,
                html.escape(copy["headline"]), paras))


def rankings_page(g, copies, intro, stamp=None):
    """Draft grades — its own page now that Rankings is the weekly power board."""
    season = g["season"]
    stamp = stamp or datetime.date.today().isoformat()   # a re-render keeps its original date
    cards = "\n".join(_grade_card(t, copies[i]) for i, t in enumerate(g["teams"]))
    body = ('<section class="page-header"><span class="eyebrow">Draft</span>'
            '<h1>%d Draft <span class="gold">Grades</span></h1>'
            '<p>Absolute 0–100 score (not curved) — roster quality vs fixed positional '
            'benchmarks on a 5-source consensus (ESPN, ESPN ADP, FantasyPros ECR, '
            'FantasyCalc, Sleeper), plus a draft-value adjustment · %s</p></section>'
            '<div class="mx-wrap"><p class="mx-intro">%s</p>%s'
            '<div class="mx-foot">This board is frozen at the draft. For where everyone '
            'actually stands now, see the <a href="rankings.html">weekly power rankings</a>.'
            '</div></div>'
            % (season, stamp, html.escape(intro), cards))
    (ROOT / "draft-grades.html").write_text(_page("Draft Grades", "Rankings", body, depth=0,
                                                  page="draft-grades.html"))
    return ROOT / "draft-grades.html"


def _power_card(r, copy):
    cls = " top" if r["rank"] <= 3 else ""
    mv = r.get("move") or 0
    if not r.get("prev_rank"):
        move = '<span class="pw-move">NEW</span>'
    elif mv > 0:
        move = '<span class="pw-move up">&#9650; %d</span>' % mv
    elif mv < 0:
        move = '<span class="pw-move down">&#9660; %d</span>' % abs(mv)
    else:
        move = '<span class="pw-move">&mdash;</span>'

    stats = []
    if r["gp"]:
        stats.append('<span class="mx-tag">Rec <b>%s</b></span>' % r["record"])
        stats.append('<span class="mx-tag">PPG <b>%.1f</b></span>' % r["pf_pg"])
        stats.append('<span class="mx-tag">All-play <b>%d-%d</b></span>'
                     % (r["allplay"][0], r["allplay"][1]))
        lk = "good" if r["luck"] >= 0.5 else "bad" if r["luck"] <= -0.5 else ""
        stats.append('<span class="mx-tag %s">Luck <b>%+.1f</b></span>' % (lk, r["luck"]))
        if r["streak"]:
            sc = "good" if r["streak"].startswith("W") else "bad"
            stats.append('<span class="mx-tag %s">Streak <b>%s</b></span>' % (sc, r["streak"]))
    else:
        if r.get("draft_roster") is not None:
            stats.append('<span class="mx-tag">Draft <b>%.0f</b></span>' % r["draft_roster"])
    if r.get("proj_avg"):
        stats.append('<span class="mx-tag">Roster proj <b>%.0f</b></span>' % r["proj_avg"])

    note = ""
    if r.get("nudge"):
        d = r["nudge"]
        note = ('<div class="mx-note">Moved %s %d %s from the model\'s order on review.</div>'
                % ("up" if d > 0 else "down", abs(d),
                   "spot" if abs(d) == 1 else "spots"))
    paras = "".join("<p>%s</p>" % html.escape(p.strip())
                    for p in copy["body"].split("\n") if p.strip())
    return ('<article class="mx-card">'
            '<div class="mx-hd"><div class="pw-rank%s">%d</div>'
            '<div><div class="mx-owner">%s</div>'
            '<div class="mx-sub">%s</div>%s</div>'
            '<div class="pw-score"><b>%.1f</b><span>Model</span></div></div>'
            '<div class="mx-tags">%s</div>%s'
            '<div class="mx-body"><div class="mx-head">%s</div>%s</div>'
            '</article>' % (
                cls, r["rank"], html.escape(r["owner"]), html.escape(r["team"]), move,
                r["score"], "".join(stats), note,
                html.escape(copy["headline"]), paras))


def power_page(board, copies, intro, stamp=None):
    """board from power.compute(); copies aligned to board['rows']."""
    season, wk = board["season"], board["week"]
    stamp = stamp or datetime.date.today().isoformat()   # a re-render keeps its original date
    title = ("Preseason <span class=\"gold\">Power Rankings</span>" if not wk
             else "Week %d <span class=\"gold\">Power Rankings</span>" % wk)
    if board["gp"]:
        blurb = ('Through Week %d · %d%% results, %d%% roster strength — all-play record, '
                 'points per game, recent form and current roster, with the order reviewed '
                 'before publishing · %s'
                 % (wk, round(board["w_results"] * 100),
                    round((1 - board["w_results"]) * 100), stamp))
    else:
        blurb = ('No games played yet — this board is pure roster strength: draft grade plus '
                 'what each roster projects to score · %s' % stamp)
    cards = "\n".join(_power_card(r, copies[i]) for i, r in enumerate(board["rows"]))
    body = ('<section class="page-header"><span class="eyebrow">Rankings</span>'
            '<h1>%s</h1><p>%s</p></section>'
            '<div class="mx-wrap"><p class="mx-intro">%s</p>%s'
            '<div class="mx-foot">The power score blends what you\'ve done (all-play record, '
            'points per game, form) with what you\'re holding (roster projection, draft '
            'grade). Results outweigh roster more each week. Full math on the '
            '<a href="analytics.html">analytics page</a> · '
            '<a href="draft-grades.html">%d draft grades</a>.</div></div>'
            % (title, blurb, html.escape(intro), cards, season))
    (ROOT / "rankings.html").write_text(_page("Power Rankings", "Rankings", body, depth=0,
                                              page="rankings.html"))
    return ROOT / "rankings.html"


def index_page(season):
    OUT.mkdir(exist_ok=True)
    weeks = (list(OUT.glob("%d-week-[0-9][0-9].html" % season))
             + list(OUT.glob("%d-week-[0-9][0-9]-preview.html" % season)))
    entries = []
    for w in weeks:
        if w.stem.endswith("-preview"):
            n, kind = int(w.stem.split("-")[-2]), "preview"
        else:
            n = int(w.stem.split("-")[-1])
            text = w.read_text()
            # Pages carry data-phase; older ones only had the "Final" header.
            if 'data-phase="preview"' in text:
                kind = "preview"
            elif 'data-phase="recap"' in text or "FINAL</SPAN>" in text.upper():
                kind = "recap"
            else:
                kind = "preview"
        entries.append((n, kind == "recap", w, kind))
    rows = []
    # Newest first; within a week the recap sits above its preview.
    for n, _, w, kind in sorted(entries, key=lambda e: (e[0], e[1]), reverse=True):
        if kind == "recap":
            label, blurb, cls = "Recap", "Final scores, results, and what it all meant", ""
        else:
            label, blurb, cls = "Preview", "The matchups, the lines, and our picks", " preview"
        rows.append('<a href="%s" class="mx-row-%s"><span class="mx-row-main">'
                    '<span class="wk">Week %d %s</span>'
                    '<span class="mx-sub">%s</span></span>'
                    '<span class="mx-badge%s">%s</span></a>'
                    % (w.name, kind, n, label, blurb, cls, label))
    listing = "\n".join(rows) or '<p class="mx-intro">No weeks generated yet.</p>'
    madness = sorted(OUT.glob("%d-week-[0-9][0-9]-madness.html" % season), reverse=True)
    mrows = "\n".join('<a href="%s" class="mx-row-madness"><span class="mx-row-main">'
                      '<span class="wk">Week %d Monday Night</span>'
                      '<span class="mx-sub">Where every game stands before MNF</span></span>'
                      '<span class="mx-badge live">Monday</span></a>'
                      % (w.name, int(w.stem.split("-")[2])) for w in madness)
    mblock = ('<h2 class="mnm-h2">Monday Night Madness</h2>'
              '<p class="mx-foot" style="margin-top:0">Where every game stands going into '
              'Monday night, plus the post for the group chat.</p>'
              '<div class="mx-week-list">%s</div>' % mrows) if mrows else ""
    body = ('<section class="page-header"><span class="eyebrow">Matchups</span>'
            '<h1>Matchup <span class="gold">Central</span></h1>'
            '<p>Weekly previews and recaps · %d</p></section>'
            '<div class="mx-wrap"><p class="mx-key"><span class="mx-badge preview">Preview</span> '
            'goes up Thursday before the games. <span class="mx-badge">Recap</span> lands Tuesday '
            'once every score is final.</p>'
            '<div class="mx-week-list">%s</div>%s</div>'
            % (season, listing, mblock))
    (OUT / "index.html").write_text(_page("Matchups", "Matchups", body, page="matchups/index.html"))


# ---------------------------------------------------------------- playoff & dress odds

def _pct(v, hi_good=True):
    if v is None:
        return '<span class="muted">–</span>'
    cls = ""
    if v >= 99.95: cls = "pos" if hi_good else "neg"
    elif v <= 0.05: cls = "neg" if hi_good else "pos"
    txt = "&lt;0.1%" if 0 < v < 0.1 else ("&gt;99.9%" if 99.9 < v < 100 else f"{v:g}%")
    return f'<span class="{cls}">{txt}</span>' if cls else txt


def _trend_svg(hist, owners, key="dress"):
    """Inline SVG: one line per owner, x = week, y = pct. Only the top movers get labels."""
    if len(hist) < 2:
        return ""
    weeks = [h["week"] for h in hist]
    series = {o: [] for o in owners}
    for h in hist:
        by = {r["owner"]: r[key] for r in h["rows"]}
        for o in owners:
            series[o].append(by.get(o))
    W, H, L, T, R, B = 720, 260, 44, 14, 12, 28
    def x(i): return L + (W - L - R) * (i / max(1, len(weeks) - 1))
    ymax = max(10.0, max(v for s in series.values() for v in s if v is not None))
    ymax = min(100.0, math.ceil(ymax / 10) * 10)
    def y(v): return T + (H - T - B) * (1 - v / ymax)
    palette = ["#e3b341", "#ff6b70", "#45e08a", "#7cc4ff", "#c98bff", "#ff9f43", "#5ee3d8", "#f472b6", "#a3e635", "#fb7185", "#93c5fd", "#fbbf24"]
    out = [f'<svg class="odds-trend" viewBox="0 0 {W} {H}" role="img" aria-label="{key} % by week">']
    for g in range(0, int(ymax) + 1, 10 if ymax > 30 else 5):
        out.append(f'<line x1="{L}" x2="{W-R}" y1="{y(g):.1f}" y2="{y(g):.1f}" stroke="rgba(255,255,255,.08)"/>'
                   f'<text x="{L-6}" y="{y(g)+4:.1f}" text-anchor="end" font-size="10" fill="#8a94a3">{g}%</text>')
    for i, wk in enumerate(weeks):
        out.append(f'<text x="{x(i):.1f}" y="{H-8}" text-anchor="middle" font-size="10" fill="#8a94a3">Wk {wk}</text>')
    last = {o: s[-1] for o, s in series.items() if s[-1] is not None}
    top = sorted(last, key=lambda o: -last[o])[:4]
    for k, (o, s) in enumerate(series.items()):
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(s) if v is not None)
        col = palette[k % len(palette)]
        hot = o in top
        out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="{2.4 if hot else 1.2}" opacity="{1 if hot else .45}"/>')
        if hot:
            out.append(f'<text x="{x(len(s)-1)+5:.1f}" y="{y(s[-1])+4:.1f}" font-size="11" font-weight="700" fill="{col}">{html.escape(o)}</text>')
    out.append("</svg>")
    return "".join(out)


def odds_page(res, hist, stamp=None):
    season, wk = res["season"], res["week"]
    stamp = stamp or datetime.date.today().isoformat()
    rows = res["rows"]
    by_dress = sorted(rows, key=lambda r: -r["dress"])[:3]
    watch = "".join(
        f'<div class="dress-card{" lead" if i == 0 else ""}"><div class="dress-pct">{r["dress"]:g}%</div>'
        f'<div class="dress-who">{html.escape(r["owner"])}</div><div class="dress-team">{html.escape(r["team"])} · {r["record"]}</div></div>'
        for i, r in enumerate(by_dress))
    table = "".join(
        f'<tr><td><span class="rank-num">{i+1}</span></td><td class="strong">{html.escape(r["owner"])}<br><small class="muted">{html.escape(r["team"])}</small></td>'
        f'<td>{r["record"]}</td><td>{r["avg_wins"]}</td><td>{_pct(r["playoff"])}</td><td>{_pct(r["bye"])}</td><td>{_pct(r["one"])}</td>'
        f'<td class="dress-col">{_pct(r["dress"], hi_good=False)}</td></tr>'
        for i, r in enumerate(rows))
    lev = ""
    if res.get("leverage"):
        cards = []
        for g in res["leverage"]:
            def side(o):
                s = g["sides"][o]
                return (f'<div class="lev-side"><div class="lev-name">{html.escape(o)}</div>'
                        f'<div class="lev-line"><span class="muted">Dress</span> win <b>{s["win"]["dress"]:g}%</b> · lose <b class="neg">{s["lose"]["dress"]:g}%</b></div>'
                        f'<div class="lev-line"><span class="muted">Playoffs</span> win <b class="pos">{s["win"]["playoff"]:g}%</b> · lose <b>{s["lose"]["playoff"]:g}%</b></div></div>')
            cards.append(f'<div class="lev-card">{side(g["away"])}<div class="lev-vs">at</div>{side(g["home"])}</div>')
        lev = (f'<section class="section"><span class="eyebrow">Week {res["next_week"]}</span><h2 class="section-title">What\'s on the line</h2>'
               f'<p class="section-sub">Each team\'s odds if they win this week versus if they lose. Big gaps = big games.</p>'
               f'<div class="lev-grid">{"".join(cards)}</div></section>')
    trend = _trend_svg(hist, [r["owner"] for r in rows], "dress")
    trend_sec = (f'<section class="section"><span class="eyebrow">Trend</span><h2 class="section-title">Dress Watch, week by week</h2>'
                 f'<p class="section-sub">How each team\'s chance of finishing last has moved. The four most at risk are labeled.</p>{trend}</section>') if trend else ""
    body = f'''<section class="page-header"><span class="eyebrow">Odds</span>
<h1>Playoff &amp; <span class="gold">Dress</span> Odds</h1>
<p>Through Week {wk} · {res["games_left"]} games left · {res["sims"]:,} simulated seasons · updated {stamp}</p></section>
<section class="section"><span class="eyebrow">Dress Watch</span><h2 class="section-title">Most likely to wear it</h2>
<p class="section-sub">Chance of finishing last in the regular season. Record, then points for, breaks ties. Somebody has to.</p>
<div class="dress-watch">{watch}</div></section>
<section class="section"><span class="eyebrow">The board</span><h2 class="section-title">Every team</h2>
<p class="section-sub">Seven teams make the playoffs; the #1 seed gets the bye. Strength = this season\'s scoring blended with the power model\'s roster projection.</p>
<div class="table-scroll"><table class="data-table sticky-first"><thead><tr><th>#</th><th>Owner</th><th>Record</th><th>Proj W</th><th>Playoffs</th><th>Bye</th><th>#1 seed</th><th>Dress</th></tr></thead><tbody>{table}</tbody></table></div></section>
{lev}
{trend_sec}
<section class="section"><p class="mx-foot">Method: every remaining game is simulated {res["sims"]:,} times. Each team\'s weekly score is drawn from a bell curve centered on its blended strength (real scoring this season plus the power model\'s roster projection, with the projection fading out as games pile up) with a spread taken from its own volatility. Seeds and last place follow the league rules: record, then points for.</p></section>'''
    (ROOT / "odds.html").write_text(_page("Playoff & Dress Odds", "Odds", body, depth=0, page="odds.html"))
    return ROOT / "odds.html"
