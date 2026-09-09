"""Render the root index.html — the Players League "jumbotron" opening page.

A standalone, chrome-less bulb board: the nine lit rows ARE the site nav, so this
page is deliberately NOT stamped by chrome.py. It is rebuilt from cached run data
(the latest power board + the latest week's matchup copy), so it refreshes on
every preview / recap / rankings / power run — same pattern as the rest of the site.

  python3 tools/main.py opening --season 2026
  python3 tools/opening.py 2026
"""
import datetime
import html
import json
import re
import sys

from lib import ROOT
from lore import OWNERS

DATA = ROOT / "tools" / "data"
OUT = ROOT / "index.html"

FULL = {first: full for full, first in OWNERS.items()}

# (number, label, href, blurb) — blurb is the "NOW SHOWING" line on hover/focus.
# Matchups' blurb is filled at build time with the marquee headline.
SECTIONS = [
    ("01", "Standings",      "home.html",
     "Where all twelve sit right now — plus every champion since 2022"),
    ("02", "Power Rankings",  "rankings.html",
     "The weekly board. Honest, with bite — every take backed by a number"),
    ("03", "Matchups",        "matchups/index.html", None),
    ("04", "Draft Grades",    "draft-grades.html",
     "How the 2026 draft actually went, scored 0 to 100. No curve"),
    ("05", "Analytics",       "analytics.html",
     "Expected wins, luck, strength of schedule, and the weekly crowns"),
    ("06", "Teams",           "teams.html",
     "Twelve profiles and their rafters. Hover a tile for a fact to fact-check"),
    ("07", "History",         "history.html",
     "Four seasons of standings and brackets, last place flagged in each"),
    ("08", "Awards",          "awards.html",
     "The superlatives — the good and the cursed. The Dress lives here"),
    ("09", "Weekend",         "weekend.html",
     "The trip. The countdown is running — next up, August 2027"),
    ("10", "Podcast",         "podcast.html",
     "The whole league previewed on video — Week 1 is up now"),
]
DEFAULT_LIT = "03"


# ------------------------------------------------------------------ data sources

def _load(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _latest_power(season):
    best, best_n = None, -1
    for f in DATA.glob(f"{season}-power-week-*.json"):
        try:
            n = int(f.stem.split("-")[-1])
        except ValueError:
            continue
        if n > best_n:
            best, best_n = f, n
    return _load(best) if best else None


def _latest_week(season):
    best, best_n = None, -1
    for f in DATA.glob(f"{season}-week-*.json"):
        m = re.fullmatch(r".*-week-(\d{2})", f.stem)
        if not m:
            continue
        n = int(m.group(1))
        if n > best_n:
            best, best_n = f, n
    return _load(best) if best else None


def _records():
    try:
        t = (ROOT / "js" / "records.js").read_text()
        m = re.search(r"const LEAGUE_RECORDS = (\{.*\});", t, re.S)
        return json.loads(m.group(1)) if m else {}
    except Exception:
        return {}


def _last(name):
    return (name or "").split()[-1].upper() if name else ""


def _achiever(rec, labels):
    """Full name of whoever most recently earned one of `labels`."""
    best, best_year = None, -1
    for full, badges in (rec.get("achievements") or {}).items():
        for b in badges:
            if b.get("label") in labels and (b.get("year") or 0) > best_year:
                best, best_year = full, b.get("year") or 0
    return best, (best_year or None)


def _marquee(week_data, power):
    """The matchup with the two best power-ranked teams, and its headline."""
    if not week_data:
        return None
    d = week_data.get("data") or {}
    copies = week_data.get("copies") or []
    matchups = d.get("matchups") or []
    rank = {}
    if power:
        rank = {r["owner"]: r["rank"] for r in power.get("board", {}).get("rows", [])}

    def score(i):
        m = matchups[i]
        a = rank.get(m["away"]["owner"], 99)
        h = rank.get(m["home"]["owner"], 99)
        return (a + h, min(a, h), i)

    idx = min(range(len(matchups)), key=score) if matchups and rank else 0
    if idx < len(copies) and copies[idx].get("headline"):
        return copies[idx]["headline"]
    return copies[0]["headline"] if copies else None


# ------------------------------------------------------------------------ render

def _cell(label, value, sub=""):
    sub_html = f'<div class="pl-cell-sub">{html.escape(sub)}</div>' if sub else ""
    return (f'<div class="pl-cell"><div class="pl-cell-lab">{html.escape(label)}</div>'
            f'<div class="pl-cell-val">{html.escape(value)}</div>{sub_html}</div>')


def build(season=2026):
    power = _latest_power(season)
    week = _latest_week(season)
    rec = _records()

    phase = (week or {}).get("phase", "preview")
    wk_no = ((week or {}).get("data") or {}).get("week")
    if wk_no is None and power:
        wk_no = power.get("board", {}).get("next_week") or power.get("board", {}).get("week")
    wk_no = wk_no or 1
    phase_word = "FINAL" if phase == "recap" else "PREVIEW"

    marquee = _marquee(week, power) or f"Week {wk_no} preview is on the way"

    top_team = top_owner = ""
    if power:
        rows = power.get("board", {}).get("rows") or []
        if rows:
            top_team = rows[0].get("team", "")
            top_owner = rows[0].get("owner", "")

    champ, champ_yr = _achiever(rec, {"Champion"})
    dress, dress_yr = _achiever(rec, {"The Dress", "Last Place"})

    # lineup rows
    rows_html = []
    for num, label, href, blurb in SECTIONS:
        if blurb is None:
            blurb = marquee
        lit = " is-lit" if num == DEFAULT_LIT else ""
        dflt = ' data-default="1"' if num == DEFAULT_LIT else ""
        cta = f"CHANNEL {num} · {label.upper()}"
        rows_html.append(
            f'<a class="pl-row{lit}" href="{href}"{dflt} '
            f'data-blurb="{html.escape(blurb.upper(), quote=True)}" '
            f'data-cta="{html.escape(cta, quote=True)}">'
            f'<span class="pl-bulb"></span>'
            f'<span class="pl-num">{num}</span>'
            f'<span class="pl-name">{html.escape(label.upper())}</span></a>')

    cells = [
        f'<div class="pl-cell"><div class="pl-cell-lab">WEEK</div>'
        f'<div class="pl-cell-val big">WK&nbsp;{wk_no}</div>'
        f'<div class="pl-cell-sub">{season} &middot; {phase_word}</div></div>',
    ]
    if top_team:
        cells.append(_cell("TOP OF THE BOARD", top_team.upper(),
                           f"{top_owner} · roster #1" if phase == "preview" and not (power or {}).get("board", {}).get("gp")
                           else top_owner))
    if champ:
        cells.append(_cell("DEFENDING CHAMP", _last(champ),
                           str(champ_yr) if champ_yr else ""))
    if dress:
        cells.append(_cell("WEARS THE DRESS", _last(dress),
                           f"last in {dress_yr}" if dress_yr else ""))

    ticker = (f"WEEK {wk_no} {'RECAPS' if phase == 'recap' else 'PREVIEWS'} LIVE "
              "&nbsp;/&nbsp; RECAPS EVERY TUESDAY &nbsp;/&nbsp; "
              "POWER BOARD REFRESHES EACH SLATE &nbsp;/&nbsp; 4 CHAMPIONS 0 REPEATS")

    built = datetime.date.today().isoformat()
    now_default = html.escape(marquee.upper())
    dflt_label = next(lbl for n, lbl, _h, _b in SECTIONS if n == DEFAULT_LIT)
    now_cta = f"CHANNEL {DEFAULT_LIT} · {dflt_label.upper()}"

    doc = _TEMPLATE.format(
        season=season,
        rows="\n        ".join(rows_html),
        cells="\n          ".join(cells),
        ticker=ticker,
        now_default=now_default,
        now_cta=html.escape(now_cta),
        built=built,
    )
    OUT.write_text(doc, encoding="utf-8")
    return OUT


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Players League</title>
<meta name="description" content="The Players League board — weekly power rankings, matchup analysis, draft grades, and four seasons of history.">
<meta property="og:title" content="Players League">
<meta property="og:description" content="Weekly power rankings, matchup analysis, and four seasons of receipts.">
<meta property="og:type" content="website">
<meta name="theme-color" content="#05070a">
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Doto:wght@500;700;800;900&family=Jersey+10&family=IBM+Plex+Mono:wght@500;600&family=IBM+Plex+Sans:wght@400;500&display=swap">
<style>
  :root {{
    --scr-bg:#020a06;
    --p-bright:#d3ffe7; --p-lit:#56cf92; --p-dim:#1f6b47;
    --amber:#ffb454;
    --glow:0 0 4px #3dd68c,0 0 14px rgba(61,214,140,.75),0 0 34px rgba(61,214,140,.4);
    --glow-sm:0 0 6px rgba(61,214,140,.45);
  }}
  *,*::before,*::after {{ box-sizing:border-box; }}
  html,body {{ margin:0; }}
  body {{
    background:radial-gradient(140% 90% at 50% 0%, #0c1016, #05070a 60%);
    color:#eef1f5;
    font-family:'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    font-size:14px; line-height:1.55; -webkit-font-smoothing:antialiased;
    min-height:100vh; display:flex; flex-direction:column;
    align-items:center; justify-content:center; padding:22px 16px;
  }}
  a {{ color:#5bd598; text-decoration:none; }}

  .pl-stage {{ width:min(1020px, 96vw); }}

  .pl-truss {{
    display:flex; align-items:center; justify-content:space-between;
    height:24px; padding:0 20px; margin:0 auto;
    background:linear-gradient(#1b1e23,#0c0e11);
    border:1px solid #262a30; border-radius:3px;
  }}
  .pl-truss span {{
    width:6px; height:6px; border-radius:50%; background:#33383f;
    box-shadow:inset 0 1px 1px rgba(0,0,0,.7);
  }}
  .pl-hangers {{ display:flex; justify-content:center; gap:min(420px,38vw); }}
  .pl-hangers span {{
    width:14px; height:18px; background:linear-gradient(#1b1e23,#0c0e11);
    border:1px solid #262a30; border-top:0; border-radius:0 0 2px 2px;
  }}

  .pl-cabinet {{
    position:relative;
    background:linear-gradient(#0c0d0f,#060708);
    border:1px solid #1c1e22; border-radius:20px;
    padding:clamp(14px,2.2vw,22px);
    box-shadow:0 40px 80px -30px rgba(0,0,0,.9),
               inset 0 2px 0 rgba(255,255,255,.04),
               inset 0 -3px 6px rgba(0,0,0,.6);
    animation:pl-hum 4.5s ease-in-out infinite alternate;
  }}
  .pl-bolt {{
    position:absolute; width:10px; height:10px; border-radius:50%;
    background:radial-gradient(circle at 35% 30%, #3a3f45, #16181b);
    box-shadow:inset 0 1px 1px rgba(0,0,0,.8);
  }}
  .pl-bolt.tl {{ top:12px; left:12px; }}   .pl-bolt.tr {{ top:12px; right:12px; }}
  .pl-bolt.bl {{ bottom:12px; left:12px; }} .pl-bolt.br {{ bottom:12px; right:12px; }}

  .pl-chase {{
    border:6px dotted #2f7d55; border-radius:16px; padding:12px;
    box-shadow:0 0 18px rgba(61,214,140,.25), inset 0 0 14px rgba(61,214,140,.12);
    animation:pl-chase 1.6s linear infinite;
  }}

  .pl-screen {{
    position:relative; overflow:hidden; border-radius:26px / 44px;
    padding:clamp(18px,2.8vw,28px) clamp(20px,3.6vw,40px);
    background:radial-gradient(120% 130% at 50% 15%, #06180d, var(--scr-bg) 70%);
    box-shadow:inset 0 0 0 1px rgba(124,255,178,.06);
  }}
  .pl-ov {{ position:absolute; inset:0; pointer-events:none; }}
  .pl-ov-grid {{
    z-index:2;
    background-image:
      repeating-linear-gradient(90deg, rgba(2,8,5,.85) 0 1px, transparent 1px 4px),
      repeating-linear-gradient(0deg,  rgba(2,8,5,.85) 0 1px, transparent 1px 4px);
  }}
  .pl-ov-scan {{
    z-index:3;
    background:repeating-linear-gradient(0deg, rgba(0,0,0,.34) 0 1.5px, rgba(0,0,0,0) 1.5px 4px);
    animation:pl-drift 9s linear infinite;
  }}
  .pl-ov-vig {{
    z-index:4; border-radius:inherit;
    box-shadow:inset 0 0 130px 30px rgba(0,0,0,.85), inset 0 0 44px rgba(0,0,0,.6);
    background:radial-gradient(120% 130% at 50% 0%, rgba(124,255,178,.07), transparent 45%);
  }}
  .pl-content {{ position:relative; z-index:5; }}

  .pl-title {{
    font-family:'Doto','Jersey 10',monospace; font-weight:900;
    font-size:clamp(28px,6vw,56px); line-height:1; letter-spacing:.08em;
    text-align:center; color:var(--p-bright); text-shadow:var(--glow); margin:0;
  }}
  .pl-ticker {{
    font-family:'Jersey 10',monospace; font-size:clamp(11px,1.4vw,15px);
    letter-spacing:.22em; text-align:center; color:#3f9e6c; margin-top:10px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }}
  .pl-rule {{
    height:2px; margin:14px 0 16px;
    background:repeating-linear-gradient(90deg, #2f7d55 0 3px, transparent 3px 9px);
  }}

  .pl-body {{
    display:flex; align-items:stretch;
    gap:clamp(20px,3.4vw,34px); flex-wrap:wrap;
  }}
  .pl-left {{ flex:0 1 300px; min-width:0; }}
  .pl-right {{ flex:1 1 340px; min-width:0; display:flex; flex-direction:column; gap:12px; }}
  .pl-kicker {{
    font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.24em;
    color:var(--amber); text-shadow:0 0 8px rgba(255,180,84,.5); margin-bottom:12px;
  }}
  .pl-list {{ display:flex; flex-direction:column; gap:1px; }}
  .pl-row {{
    display:flex; align-items:center; gap:12px; padding:5px 10px;
    border:1px solid transparent; border-radius:4px;
    transition:background .12s, border-color .12s, box-shadow .12s;
  }}
  .pl-bulb {{
    width:8px; height:8px; border-radius:50%; background:var(--p-dim); flex:none;
  }}
  .pl-num {{
    font-family:'Jersey 10',monospace; font-size:15px; color:#3f8f66; min-width:2ch;
  }}
  .pl-name {{
    font-family:'Jersey 10',monospace; font-size:clamp(18px,2.4vw,21px);
    line-height:1.15; letter-spacing:.04em; color:var(--p-lit); text-shadow:var(--glow-sm);
  }}
  .pl-row:hover, .pl-row:focus-visible, .pl-row.is-lit {{
    background:rgba(124,255,178,.10); border-color:rgba(124,255,178,.5);
    box-shadow:0 0 16px rgba(61,214,140,.22), inset 0 0 12px rgba(61,214,140,.12);
    outline:none;
  }}
  .pl-row:hover .pl-bulb, .pl-row:focus-visible .pl-bulb, .pl-row.is-lit .pl-bulb {{
    background:#b6ffd6; box-shadow:0 0 8px #3dd68c, 0 0 16px rgba(61,214,140,.7);
  }}
  .pl-row:hover .pl-name, .pl-row:focus-visible .pl-name, .pl-row.is-lit .pl-name {{
    color:var(--p-bright); text-shadow:var(--glow);
  }}
  .pl-row:hover .pl-num, .pl-row:focus-visible .pl-num, .pl-row.is-lit .pl-num {{
    color:#8ff0bf;
  }}

  .pl-feed {{
    flex:1 1 auto; display:flex; flex-direction:column; justify-content:center;
    gap:9px; min-height:132px; padding:16px 20px;
    border:1px solid rgba(124,255,178,.28); border-radius:6px;
    background:radial-gradient(120% 140% at 20% 0%, rgba(61,214,140,.08), rgba(0,0,0,.34) 60%);
    box-shadow:inset 0 0 34px rgba(61,214,140,.07);
  }}
  .pl-feed-tag {{
    display:flex; align-items:center; gap:8px;
    font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.2em;
    color:var(--amber);
  }}
  .pl-feed-tag svg {{ flex:none; filter:drop-shadow(0 0 5px rgba(255,180,84,.6)); }}
  .pl-feed-txt {{
    font-family:'Jersey 10',monospace; font-size:clamp(19px,2.7vw,29px);
    line-height:1.14; letter-spacing:.02em; color:var(--p-bright);
    text-shadow:var(--glow-sm);
  }}
  .pl-feed-cta {{
    font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.14em;
    color:#4f8f6c;
  }}

  .pl-cells {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
  .pl-cell {{
    border:1px solid rgba(124,255,178,.20); background:rgba(0,0,0,.34);
    border-radius:4px; padding:9px 13px;
  }}
  .pl-cell-lab {{
    font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.2em;
    color:var(--amber); margin-bottom:4px;
  }}
  .pl-cell-val {{
    font-family:'Doto','Jersey 10',monospace; font-weight:700; font-size:22px;
    line-height:1.05; color:#cdffe4; text-shadow:0 0 8px rgba(61,214,140,.5);
  }}
  .pl-cell-val.big {{ font-size:34px; line-height:.9; letter-spacing:.02em; }}
  .pl-cell-sub {{
    font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.06em;
    color:#4f8f6c; margin-top:5px;
  }}

  .pl-plate {{
    text-align:center; margin-top:12px;
    font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.28em;
    color:#3c4148; text-shadow:0 1px 0 rgba(255,255,255,.04);
  }}
  .pl-foot {{
    text-align:center; color:#5b6572; font-size:12px; margin:16px auto 0; max-width:62ch;
  }}

  @keyframes pl-hum   {{ from {{ filter:brightness(.97); }} to {{ filter:brightness(1.03); }} }}
  @keyframes pl-chase {{ 0% {{ border-color:#2f7d55; }} 50% {{ border-color:#7dffbf; }} 100% {{ border-color:#2f7d55; }} }}
  @keyframes pl-drift {{ from {{ background-position:0 0; }} to {{ background-position:0 120px; }} }}

  @media (max-width:720px) {{
    body {{ padding:20px 10px; }}
    .pl-body {{ gap:18px; }}
    .pl-left, .pl-right {{ flex-basis:100%; }}
    .pl-ticker {{ letter-spacing:.06em; }}
    .pl-feed {{ min-height:120px; }}
  }}
  @media (max-width:420px) {{
    .pl-cells {{ grid-template-columns:1fr; }}
  }}
  @media (prefers-reduced-motion:reduce) {{
    .pl-cabinet, .pl-chase, .pl-ov-scan {{ animation:none; }}
  }}
</style>
</head>
<body>
<main class="pl-stage">

  <div class="pl-truss">
    <span></span><span></span><span></span><span></span><span></span><span></span>
  </div>
  <div class="pl-hangers"><span></span><span></span></div>

  <div class="pl-cabinet">
    <span class="pl-bolt tl"></span><span class="pl-bolt tr"></span>
    <span class="pl-bolt bl"></span><span class="pl-bolt br"></span>

    <div class="pl-chase">
      <div class="pl-screen">
        <div class="pl-ov pl-ov-grid"></div>
        <div class="pl-ov pl-ov-scan"></div>
        <div class="pl-ov pl-ov-vig"></div>

        <div class="pl-content">
          <h1 class="pl-title">PLAYERS LEAGUE</h1>
          <div class="pl-ticker">{ticker}</div>
          <div class="pl-rule"></div>

          <div class="pl-body">
            <div class="pl-left">
              <div class="pl-kicker">SELECT A CHANNEL</div>
              <nav class="pl-list" aria-label="Sections">
        {rows}
              </nav>
            </div>

            <div class="pl-right">
              <div class="pl-feed">
                <div class="pl-feed-tag">
                  <svg viewBox="0 0 12 12" width="10" height="10" fill="#ffb454" aria-hidden="true"><path d="M2 1l8 5-8 5z"/></svg>
                  <span>NOW SHOWING</span>
                </div>
                <div class="pl-feed-txt" id="pl-feed-txt">{now_default}</div>
                <div class="pl-feed-cta" id="pl-feed-cta">{now_cta}</div>
              </div>
              <div class="pl-cells">
          {cells}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="pl-plate">PLAYERS LEAGUE &middot; SOLID-STATE MATRIX DISPLAY &middot; MODEL PL-2600</div>
  </div>

  <p class="pl-foot">Every channel is a link into the site. The board rebuilds itself each week &mdash; last update {built}.</p>

</main>

<script>
(function () {{
  var txt = document.getElementById('pl-feed-txt');
  var cta = document.getElementById('pl-feed-cta');
  var rows = Array.prototype.slice.call(document.querySelectorAll('.pl-row'));
  var dflt = document.querySelector('.pl-row[data-default]');
  var defTxt = txt ? txt.textContent : '';
  var defCta = cta ? cta.textContent : '';
  function clearAll() {{ rows.forEach(function (x) {{ x.classList.remove('is-lit'); }}); }}
  function light(r) {{
    clearAll(); r.classList.add('is-lit');
    if (txt && r.getAttribute('data-blurb')) txt.textContent = r.getAttribute('data-blurb');
    if (cta && r.getAttribute('data-cta')) cta.textContent = r.getAttribute('data-cta');
  }}
  function reset() {{
    clearAll(); if (dflt) dflt.classList.add('is-lit');
    if (txt) txt.textContent = defTxt;
    if (cta) cta.textContent = defCta;
  }}
  rows.forEach(function (r) {{
    r.addEventListener('mouseenter', function () {{ light(r); }});
    r.addEventListener('focus', function () {{ light(r); }});
    r.addEventListener('blur', reset);
  }});
  var list = document.querySelector('.pl-list');
  if (list) list.addEventListener('mouseleave', reset);
}})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    print("wrote", build(season).relative_to(ROOT))
