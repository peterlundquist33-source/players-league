"""Render generated copy + matchup data into matchups/ pages, styled like the site."""
import html, pathlib, datetime
from lib import ROOT
import chrome as SITE

OUT = ROOT / "matchups"


def _page(title, active, body, depth=1, page=None):
    """Shared chrome comes from site.py so generated pages match the static ones
    exactly; only the page-specific component styles live here."""
    return f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- HEAD:start -->
{SITE.head(page or "", depth, title=f"{title} — Players League")}
<!-- HEAD:end -->
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
 .mx-pick{{margin-top:.85rem;padding-top:.7rem;border-top:1px dashed var(--border);
   font-family:var(--font-display);font-weight:800;font-size:.82rem;color:var(--text)}}
 .mx-pick span{{display:inline-block;font-size:.6rem;letter-spacing:.12em;font-weight:800;
   text-transform:uppercase;color:var(--accent);background:var(--accent-tint);
   padding:.18rem .45rem;border-radius:4px;margin-right:.5rem;vertical-align:middle}}
 .mx-pick.hit span{{color:var(--accent)}}
 .mx-pick.miss span{{color:var(--red);background:rgba(255,107,112,.12)}}
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
 .pw-hd{{display:flex;align-items:center;gap:.9rem;padding:1rem 1.3rem;border-bottom:1px solid var(--border)}}
 .pw-rank{{font-family:var(--font-display);font-weight:900;font-size:2.1rem;line-height:1;
   color:var(--text-light);min-width:2ch;text-align:center;font-variant-numeric:tabular-nums}}
 .pw-rank.top{{color:var(--accent)}}
 .pw-move{{font-family:var(--font-display);font-size:.68rem;font-weight:800;letter-spacing:.03em;
   padding:.15rem .4rem;border-radius:4px;background:var(--surface-2);color:var(--text-muted)}}
 .pw-move.up{{color:var(--accent);background:var(--accent-tint)}}
 .pw-move.down{{color:var(--red);background:rgba(255,107,112,.12)}}
 .pw-score{{margin-left:auto;text-align:right}}
 .pw-score b{{font-family:var(--font-display);font-weight:900;font-size:1.25rem;color:var(--text);
   font-variant-numeric:tabular-nums}}
 .pw-score span{{display:block;font-size:.62rem;color:var(--text-muted);letter-spacing:.08em;
   text-transform:uppercase;font-weight:700}}
 .pw-stats{{display:flex;flex-wrap:wrap;gap:.35rem;padding:.7rem 1.3rem;border-bottom:1px solid var(--border)}}
 .pw-stat{{font-family:var(--font-display);font-size:.66rem;font-weight:800;letter-spacing:.04em;
   padding:.2rem .5rem;border-radius:4px;background:var(--surface-2);color:var(--text-muted)}}
 .pw-stat b{{color:var(--text);font-weight:800}}
 .pw-stat.good b{{color:var(--accent)}} .pw-stat.bad b{{color:var(--red)}}
 .pw-note{{font-size:.72rem;color:var(--text-muted);padding:.55rem 1.3rem 0;font-style:italic}}
 .pw-foot{{margin-top:2rem;padding-top:1.2rem;border-top:1px solid var(--border);
   font-size:.78rem;color:var(--text-muted);line-height:1.7}}
 .pw-foot a{{color:var(--accent);font-weight:700}}
</style></head>
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
    path.write_text(_page(f"Week {wk} {badge}", "Matchups", body, page=f"matchups/{path.name}"))
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
    """Draft grades — its own page now that Rankings is the weekly power board."""
    season = g["season"]
    stamp = datetime.date.today().isoformat()
    cards = "\n".join(_grade_card(t, copies[i]) for i, t in enumerate(g["teams"]))
    body = ('<section class="page-header"><h1>%d DRAFT <span class="gold">GRADES</span></h1>'
            '<p>Absolute 0–100 score (not curved) — roster quality vs fixed positional '
            'benchmarks on a 5-source consensus (ESPN, ESPN ADP, FantasyPros ECR, '
            'FantasyCalc, Sleeper), plus a draft-value adjustment · %s</p></section>'
            '<div class="mx-wrap"><p class="mx-intro">%s</p>%s'
            '<div class="pw-foot">This board is frozen at the draft. For where everyone '
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
        stats.append('<span class="pw-stat">REC <b>%s</b></span>' % r["record"])
        stats.append('<span class="pw-stat">PPG <b>%.1f</b></span>' % r["pf_pg"])
        stats.append('<span class="pw-stat">ALL-PLAY <b>%d-%d</b></span>'
                     % (r["allplay"][0], r["allplay"][1]))
        lk = "good" if r["luck"] >= 0.5 else "bad" if r["luck"] <= -0.5 else ""
        stats.append('<span class="pw-stat %s">LUCK <b>%+.1f</b></span>' % (lk, r["luck"]))
        if r["streak"]:
            sc = "good" if r["streak"].startswith("W") else "bad"
            stats.append('<span class="pw-stat %s">STREAK <b>%s</b></span>' % (sc, r["streak"]))
    else:
        if r.get("draft_roster") is not None:
            stats.append('<span class="pw-stat">DRAFT <b>%.0f</b></span>' % r["draft_roster"])
    if r.get("proj_avg"):
        stats.append('<span class="pw-stat">ROSTER PROJ <b>%.0f</b></span>' % r["proj_avg"])

    note = ""
    if r.get("nudge"):
        d = r["nudge"]
        note = ('<div class="pw-note">Moved %s %d %s from the model\'s order on review.</div>'
                % ("up" if d > 0 else "down", abs(d),
                   "spot" if abs(d) == 1 else "spots"))
    paras = "".join("<p>%s</p>" % html.escape(p.strip())
                    for p in copy["body"].split("\n") if p.strip())
    return ('<article class="mx-card reveal">'
            '<div class="pw-hd"><div class="pw-rank%s">%d</div>'
            '<div><div class="mx-owner">%s</div>'
            '<div class="mx-sub">%s</div>%s</div>'
            '<div class="pw-score"><b>%.1f</b><span>Model</span></div></div>'
            '<div class="pw-stats">%s</div>%s'
            '<div class="mx-body"><div class="mx-head">%s</div>%s</div>'
            '</article>' % (
                cls, r["rank"], html.escape(r["owner"]), html.escape(r["team"]), move,
                r["score"], "".join(stats), note,
                html.escape(copy["headline"]), paras))


def power_page(board, copies, intro):
    """board from power.compute(); copies aligned to board['rows']."""
    season, wk = board["season"], board["week"]
    stamp = datetime.date.today().isoformat()
    title = ("PRESEASON <span class=\"gold\">POWER RANKINGS</span>" if not wk
             else "WEEK %d <span class=\"gold\">POWER RANKINGS</span>" % wk)
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
    body = ('<section class="page-header"><h1>%s</h1><p>%s</p></section>'
            '<div class="mx-wrap"><p class="mx-intro">%s</p>%s'
            '<div class="pw-foot">The power score blends what you\'ve done (all-play record, '
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
    body = ('<section class="page-header"><h1>MATCHUP <span class="gold">CENTRAL</span></h1>'
            '<p>Weekly previews and recaps · %d</p></section>'
            '<div class="mx-wrap"><div class="mx-week-list">%s</div></div>' % (season, listing))
    (OUT / "index.html").write_text(_page("Matchups", "Matchups", body, page="matchups/index.html"))
