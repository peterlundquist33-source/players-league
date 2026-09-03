"""Render generated copy + matchup data into matchups/ pages, styled like the site."""
import html, pathlib, datetime
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
        a_pts, h_pts = f'{a["projected"]:.1f}', f'{h["projected"]:.1f}'
        a_win = h_win = False
        a_sub = f'{a["record"]} · proj'
        h_sub = f'{h["record"]} · proj'
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
    mid = "vs" if phase == "preview" else "—"
    return '''<article class="mx-card">
  <div class="mx-score">
    <div class="mx-team away">
      <span class="mx-owner">{a_owner}</span>
      <span class="mx-sub">{a_team} · {a_sub}</span>
    </div>
    <div class="mx-mid">
      <div class="mx-pts{a_cls}">{a_pts}</div>
      <div class="mx-vs">{mid}</div>
      <div class="mx-pts{h_cls}">{h_pts}</div>
    </div>
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
        a_cls=a_cls, h_cls=h_cls, a_pts=a_pts, h_pts=h_pts, mid=mid,
        head=html.escape(copy["headline"]), paras=paras)


def week_page(league, copies, intro, stamp=None):
    wk, phase, season = league["week"], league["phase"], league["season"]
    badge = "Preview" if phase == "preview" else "Final"
    cards = "\n".join(_matchup_card(m, copies[i], phase)
                      for i, m in enumerate(league["matchups"]))
    stamp = stamp or datetime.date.today().isoformat()   # a re-render keeps its original date
    body = f'''<section class="page-header">
  <span class="eyebrow">Matchups</span>
  <h1>Week {wk} <span class="gold">{badge}</span></h1>
  <p>{season} season · generated {stamp}</p>
</section>
<div class="mx-wrap">
  <p class="mx-intro">{html.escape(intro)}</p>
  {cards}
</div>'''
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{season}-week-{wk:02d}.html"
    path.write_text(_page(f"Week {wk} {badge}", "Matchups", body, page=f"matchups/{path.name}"))
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
    weeks = sorted(OUT.glob("%d-week-*.html" % season), reverse=True)
    rows = []
    for w in weeks:
        n = int(w.stem.split("-")[-1])
        badge = "Final" if "FINAL</SPAN>" in w.read_text().upper() else "Preview"
        rows.append('<a href="%s"><span class="wk">Week %d</span>'
                    '<span class="mx-badge">%s</span></a>' % (w.name, n, badge))
    listing = "\n".join(rows) or '<p class="mx-intro">No weeks generated yet.</p>'
    body = ('<section class="page-header"><span class="eyebrow">Matchups</span>'
            '<h1>Matchup <span class="gold">Central</span></h1>'
            '<p>Weekly previews and recaps · %d</p></section>'
            '<div class="mx-wrap"><div class="mx-week-list">%s</div></div>' % (season, listing))
    (OUT / "index.html").write_text(_page("Matchups", "Matchups", body, page="matchups/index.html"))
