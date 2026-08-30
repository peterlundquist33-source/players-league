"""Render generated copy + matchup data into matchups/ pages, styled like the site."""
import html, pathlib, datetime
from lib import ROOT

OUT = ROOT / "matchups"
CSS = "../css/style.css?v=green-1"

NAV_ITEMS = [("weekend.html", "Weekend"), ("home.html", "Home"), ("teams.html", "Teams"),
             ("awards.html", "Awards"), ("history.html", "History"),
             ("analytics.html", "Analytics"), ("matchups/index.html", "Matchups"),
             ("rankings.html", "Rankings")]


def _nav(active, depth=1):
    up = "../" * depth
    parts = []
    for href, label in NAV_ITEMS:
        cls = ' class="active"' if label == active else ""
        parts.append('<a href="%s%s"%s>%s</a>' % (up, href, cls, label))
    links = "".join(parts)
    return ('<nav class="nav"><div class="nav-inner">'
            '<a href="%shome.html" class="nav-logo">PLAYERS LEAGUE'
            '<span class="sub">Fantasy Football · Est. 2022</span></a>'
            '<div class="nav-toggle"><span></span><span></span><span></span></div>'
            '<div class="nav-links">%s</div></div></nav>' % (up, links))


def _page(title, active, body, depth=1):
    return f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)} — Players League</title>
<link rel="icon" type="image/svg+xml" href="{"../" * depth}favicon.svg">
<link rel="stylesheet" href="{"../" * depth}css/style.css?v=green-1">
<style>
 .mx-wrap{{max-width:820px;margin:0 auto;padding:2rem 1.25rem 3rem}}
 .mx-card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
   box-shadow:var(--shadow-md);margin-bottom:1.1rem;overflow:hidden}}
 .mx-score{{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;
   gap:.5rem;padding:1.1rem 1.3rem;border-bottom:1px solid var(--border)}}
 .mx-team{{display:flex;flex-direction:column;gap:.15rem}}
 .mx-team.away{{text-align:right}}
 .mx-owner{{font-family:var(--font-display);font-weight:800;font-size:1.05rem;color:var(--text)}}
 .mx-sub{{font-size:.72rem;color:var(--text-muted)}}
 .mx-pts{{font-family:var(--font-display);font-weight:900;font-size:1.5rem;
   font-variant-numeric:tabular-nums;color:var(--text)}}
 .mx-pts.win{{color:var(--accent)}}
 .mx-vs{{font-family:var(--font-display);font-weight:800;font-size:.7rem;color:var(--text-light);
   letter-spacing:.1em;padding:0 .4rem}}
 .mx-body{{padding:1.1rem 1.3rem}}
 .mx-head{{font-family:var(--font-display);font-weight:800;font-size:1.05rem;color:var(--text);
   margin-bottom:.5rem;line-height:1.3}}
 .mx-body p{{color:var(--text-body);font-size:.9rem;line-height:1.65;margin-bottom:.6rem}}
 .mx-body p:last-child{{margin-bottom:0}}
 .mx-badge{{display:inline-block;font-family:var(--font-display);font-size:.6rem;font-weight:800;
   letter-spacing:.1em;text-transform:uppercase;padding:.2rem .5rem;border-radius:4px;
   background:var(--accent-tint);color:var(--accent);margin-left:.5rem;vertical-align:middle}}
 .mx-intro{{color:var(--text-muted);font-size:.95rem;line-height:1.7;margin-bottom:1.6rem;
   border-left:2px solid var(--accent);padding-left:1rem}}
 .mx-week-list a{{display:flex;justify-content:space-between;align-items:center;
   background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
   padding:1rem 1.2rem;margin-bottom:.7rem;transition:var(--transition)}}
 .mx-week-list a:hover{{border-color:var(--accent);transform:translateY(-2px)}}
 .mx-week-list .wk{{font-family:var(--font-display);font-weight:800;color:var(--text)}}
 .gr-hd{{display:flex;align-items:center;gap:1rem;padding:1rem 1.3rem;border-bottom:1px solid var(--border)}}
 .gr-grade{{font-family:var(--font-display);font-weight:900;font-size:2rem;line-height:1;
   color:var(--accent);min-width:2.4ch;text-align:center}}
 .gr-grade.lo{{color:var(--red)}}
 .gr-rank{{font-size:.72rem;color:var(--text-muted);font-weight:700}}
 .gr-pos{{display:flex;flex-wrap:wrap;gap:.35rem;padding:.7rem 1.3rem;border-bottom:1px solid var(--border)}}
 .gr-chip{{font-family:var(--font-display);font-size:.66rem;font-weight:800;letter-spacing:.04em;
   padding:.2rem .5rem;border-radius:4px;background:var(--surface-2);color:var(--text-muted)}}
 .gr-chip b{{color:var(--text)}}
 .gr-cite{{font-size:.78rem;color:var(--text-muted);padding:.6rem 1.3rem 0}}
 .gr-cite .up{{color:var(--accent);font-weight:700}} .gr-cite .down{{color:var(--red);font-weight:700}}
</style></head>
<body class="polish">
{_nav(active, depth)}
{body}
<footer class="footer"><p><span class="gold">PLAYERS LEAGUE</span> &mdash; Est. 2022</p></footer>
<script>document.querySelector('.nav-toggle').addEventListener('click',function(){{
 document.querySelector('.nav-links').classList.toggle('open');}});</script>
<script src="{"../" * depth}js/polish.js"></script>
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
    a_cls = " win" if a_win else ""
    h_cls = " win" if h_win else ""
    mid = "vs" if phase == "preview" else "—"
    return '''<article class="mx-card reveal">
  <div class="mx-score">
    <div class="mx-team away">
      <span class="mx-owner">{a_owner}</span>
      <span class="mx-sub">{a_team} · {a_sub}</span>
    </div>
    <div style="text-align:center">
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


def week_page(league, copies, intro):
    wk, phase, season = league["week"], league["phase"], league["season"]
    badge = "Preview" if phase == "preview" else "Final"
    cards = "\n".join(_matchup_card(m, copies[i], phase)
                      for i, m in enumerate(league["matchups"]))
    stamp = datetime.date.today().isoformat()
    body = f'''<section class="page-header">
  <h1>WEEK {wk} <span class="gold">{badge.upper()}</span></h1>
  <p>{season} season · generated {stamp}</p>
</section>
<div class="mx-wrap">
  <p class="mx-intro">{html.escape(intro)}</p>
  {cards}
</div>'''
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{season}-week-{wk:02d}.html"
    path.write_text(_page(f"Week {wk} {badge}", "Matchups", body))
    return path


def _grade_card(t, copy):
    lo = " lo" if t["grade"][0] in "DF" else ""
    chips = "".join(
        '<span class="gr-chip">%s <b>%s</b></span>' % (pos, v["grade"])
        for pos, v in t["pos_grades"].items() if v["grade"] != "—")
    cite = ""
    if t.get("best"):
        b = t["best"]
        cite += ('<div class="gr-cite">Best value: <span class="up">%s</span> '
                 '— round %s, pick %d (%+.0f vs market)</div>'
                 % (html.escape(b["name"]), b["round"], b["overall"], b["value"]))
    if t.get("reach"):
        r = t["reach"]
        cite += ('<div class="gr-cite">Biggest reach: <span class="down">%s</span> '
                 '— round %s, pick %d (%+.0f)</div>'
                 % (html.escape(r["name"]), r["round"], r["overall"], r["value"]))
    paras = "".join("<p>%s</p>" % html.escape(p.strip())
                    for p in copy["body"].split("\n") if p.strip())
    return ('<article class="mx-card reveal">'
            '<div class="gr-hd"><div class="gr-grade%s">%s'
            '<span style="display:block;font-size:.42em;font-weight:700;color:var(--text-muted);'
            'letter-spacing:0;">%s/100</span></div>'
            '<div><div class="mx-owner">%s</div>'
            '<div class="mx-sub">%s</div>'
            '<div class="gr-rank">#%d of 12</div></div></div>'
            '<div class="gr-pos">%s</div>'
            '%s'
            '<div class="mx-body"><div class="mx-head">%s</div>%s</div>'
            '</article>' % (
                lo, html.escape(t["grade"]), t["score"], html.escape(t["owner"]),
                html.escape(t["team"]), t["rank"], chips, cite,
                html.escape(copy["headline"]), paras))


def rankings_page(g, copies, intro):
    """g from draft.build(); copies aligned to g['teams']."""
    season = g["season"]
    stamp = datetime.date.today().isoformat()
    cards = "\n".join(_grade_card(t, copies[i]) for i, t in enumerate(g["teams"]))
    body = ('<section class="page-header"><h1>%d DRAFT <span class="gold">GRADES</span></h1>'
            '<p>Absolute 0–100 score (not curved) — roster quality vs fixed positional '
            'benchmarks on a 5-source consensus (ESPN, ESPN ADP, FantasyPros ECR, '
            'FantasyCalc, Sleeper), plus a draft-value adjustment · %s</p></section>'
            '<div class="mx-wrap"><p class="mx-intro">%s</p>%s</div>'
            % (season, stamp, html.escape(intro), cards))
    (ROOT / "rankings.html").write_text(_page("Draft Grades", "Rankings", body, depth=0))
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
    body = ('<section class="page-header"><h1>MATCHUP <span class="gold">CENTRAL</span></h1>'
            '<p>Weekly previews and recaps · %d</p></section>'
            '<div class="mx-wrap"><div class="mx-week-list">%s</div></div>' % (season, listing))
    (OUT / "index.html").write_text(_page("Matchups", "Matchups", body))
