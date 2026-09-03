"""Shared page chrome — head, nav, footer — and the stamp that applies it.

Every page on the site, hand-written or generated, gets its <head> links, nav
and footer from here. render.py imports the functions; the static pages get
them stamped in between markers, the same way homepage.py stamps standings.
Run `python3 tools/main.py site` after editing anything in this file.
(It's chrome.py, not site.py, because `site` is a Python stdlib module.)

Why markers: there is no build step and no framework, so the only way six
hand-written pages stay identical is for one function to own the markup and
overwrite it in place. Before this, all six navs had drifted apart.
"""
import re
from lib import ROOT

STYLE_VERSION = "3"

# (href, label) — the order the nav shows them in
NAV = [
    ("home.html", "Home"),
    ("rankings.html", "Rankings"),
    ("matchups/index.html", "Matchups"),
    ("analytics.html", "Analytics"),
    ("teams.html", "Teams"),
    ("history.html", "History"),
    ("awards.html", "Awards"),
    ("weekend.html", "Weekend"),
]

# per-page title + meta description. Pages not listed keep their own <title>.
PAGES = {
    "home.html": ("Players League",
                  "Standings, champions, and the running story of a 12-team fantasy football league, est. 2022."),
    "rankings.html": ("Power Rankings — Players League",
                      "Weekly power rankings from results, scoring and roster strength, refreshed every Tuesday."),
    "draft-grades.html": ("Draft Grades — Players League",
                          "Every roster graded against fixed positional benchmarks on a five-source consensus."),
    "matchups/index.html": ("Matchups — Players League",
                            "Weekly previews and recaps for every game."),
    "analytics.html": ("Analytics — Players League",
                       "Expected wins, luck, schedule strength, schedule swaps and weekly scoring records."),
    "teams.html": ("Teams — Players League",
                   "Every owner's profile, career record, head-to-heads and banners in the rafters."),
    "history.html": ("History — Players League",
                     "Season by season since 2022: champions, standings and the moments that mattered."),
    "awards.html": ("Awards — Players League",
                    "Champions, records, and who wore the dress."),
    "weekend.html": ("Players Weekend — Players League",
                     "The lake weekend: countdown, itinerary and the live draft."),
}
DEFAULT_DESC = "Players League — a 12-team fantasy football league, est. 2022."
OG_IMAGE = "img/weekend/hero.jpg"

# the exact nav-toggle handler every page used to carry inline
_OLD_TOGGLE = re.compile(
    r"\s*document\.querySelector\('\.nav-toggle'\)\??\.addEventListener\('click',\s*(?:\(\)\s*=>|function\s*\(\)\s*)\s*\{\s*"
    r"document\.querySelector\('\.nav-links'\)\.classList\.toggle\('open'\);\s*\}\);?",
    re.S)


def _rel(depth):
    return "../" * depth


def head(page, depth=0, title=None, desc=None):
    """The shared part of <head>: fonts, stylesheet, icon, meta, OG."""
    up = _rel(depth)
    t, d = PAGES.get(page, (title or "Players League", desc or DEFAULT_DESC))
    if title:
        t = title
    if desc:
        d = desc
    return (
        f'<title>{t}</title>\n'
        f'<meta name="description" content="{d}">\n'
        f'<meta property="og:title" content="{t}">\n'
        f'<meta property="og:description" content="{d}">\n'
        f'<meta property="og:type" content="website">\n'
        f'<meta property="og:image" content="{up}{OG_IMAGE}">\n'
        f'<meta name="theme-color" content="#0e1117">\n'
        f'<link rel="icon" type="image/svg+xml" href="{up}favicon.svg">\n'
        f'<link rel="preload" href="{up}css/fonts/archivo-latin.woff2" as="font" type="font/woff2" crossorigin>\n'
        f'<link rel="preload" href="{up}css/fonts/plex-sans-latin.woff2" as="font" type="font/woff2" crossorigin>\n'
        f'<link rel="stylesheet" href="{up}css/style.css?v={STYLE_VERSION}">'
    )


# The whole icon set: one size, one colour (currentColor), used via
# <svg class="icon"><use href="#i-trophy"/></svg>. Stroked, 24-unit grid.
ICONS = {
    "trophy": "M7 4h10v5a5 5 0 0 1-10 0V4z M7 6H4v2a3 3 0 0 0 3 3 M17 6h3v2a3 3 0 0 1-3 3 M12 14v4 M8 20h8",
    "dress":  "M9 3l3 3 3-3 M8 9l1-6 M16 9l-1-6 M8 9L5 20h14L16 9 M8 9h8",
    "flag":   "M5 21V4 M5 4h12l-2 4 2 4H5",
    "crown":  "M4 18h16 M4 18L3 8l5 4 4-6 4 6 5-4-1 10",
    "star":   "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9L12 3z",
    "chart":  "M4 19h16 M7 16V9 M12 16V5 M17 16v-6",
}


def icons():
    syms = "".join(
        f'<symbol id="i-{k}" viewBox="0 0 24 24"><path d="{d}"/></symbol>' for k, d in ICONS.items())
    return f'<svg width="0" height="0" style="position:absolute" aria-hidden="true">{syms}</svg>'


def nav(active, depth=0):
    """`active` is a nav label ("Home") or a page href."""
    up = _rel(depth)
    links = []
    for href, label in NAV:
        attrs = ' class="active" aria-current="page"' if active in (label, href) else ""
        links.append(f'<a href="{up}{href}"{attrs}>{label}</a>')
    return (
        icons() +
        '<nav class="nav" aria-label="Primary"><div class="nav-inner">'
        f'<a href="{up}home.html" class="nav-logo">Players League</a>'
        '<button class="nav-toggle" type="button" aria-label="Menu" aria-expanded="false">'
        '<span></span><span></span><span></span></button>'
        f'<div class="nav-links">{"".join(links)}</div>'
        '</div></nav>'
    )


def footer():
    return ('<footer class="footer"><p><span class="gold">Players League</span> &middot; '
            'Est. 2022</p></footer>')


def scripts(depth=0):
    return f'<script src="{_rel(depth)}js/site.js"></script>'


# ---------------------------------------------------------------- stamping

_NAV_RE = re.compile(r"(<!-- NAV:start -->.*?<!-- NAV:end -->|<nav class=\"nav\".*?</nav>)", re.S)
_FOOT_RE = re.compile(r"(<!-- FOOTER:start -->.*?<!-- FOOTER:end -->|<footer class=\"footer\".*?</footer>)", re.S)
_HEAD_RE = re.compile(r"(<!-- HEAD:start -->.*?<!-- HEAD:end -->)", re.S)


def _active_for(page):
    for href, label in NAV:
        if page == href:
            return label
    if page == "draft-grades.html":
        return "Rankings"
    if page.startswith("matchups/"):
        return "Matchups"
    return ""


def stamp_text(html, page, depth):
    """Apply the shared chrome to one page's HTML. Idempotent."""
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    own_title = m.group(1).strip() if m else None
    title = None if page in PAGES else own_title

    # --- head: strip the pieces we own, then insert one block after viewport ---
    if _HEAD_RE.search(html):
        html = _HEAD_RE.sub(lambda _: "<!-- HEAD:start -->\n" + head(page, depth, title) + "\n<!-- HEAD:end -->", html)
    else:
        html = re.sub(r"\s*<title>.*?</title>", "", html, count=1, flags=re.S)
        html = re.sub(r'\s*<link[^>]+(?:style\.css|fonts\.googleapis|favicon|rel="preload")[^>]*>', "", html)
        html = re.sub(r'\s*<meta (?:name="description"|property="og:[a-z]+"|name="theme-color")[^>]*>', "", html)
        html = re.sub(r'(<meta name="viewport"[^>]*>)',
                      lambda mm: mm.group(1) + "\n<!-- HEAD:start -->\n" + head(page, depth, title) + "\n<!-- HEAD:end -->",
                      html, count=1)

    # --- nav / footer ---
    html = _NAV_RE.sub(lambda _: "<!-- NAV:start -->\n" + nav(_active_for(page), depth) + "\n<!-- NAV:end -->", html, count=1)
    html = _FOOT_RE.sub(lambda _: "<!-- FOOTER:start -->\n" + footer() + "\n<!-- FOOTER:end -->", html, count=1)

    # --- scripts: drop the splash gate and scroll-reveal, own the nav toggle ---
    html = re.sub(r'\s*<script src="[^"]*js/(?:gate|polish)\.js[^"]*"></script>', "", html)
    html = _OLD_TOGGLE.sub("", html)
    html = re.sub(r"<script>\s*</script>\s*", "", html)
    if "js/site.js" not in html:
        html = re.sub(r"</body>", scripts(depth) + "\n</body>", html, count=1)

    html = html.replace('<body class="polish">', "<body>")
    return html


def stamp(path):
    """Stamp one file under ROOT. Returns True if it changed."""
    p = ROOT / path
    src = p.read_text(encoding="utf-8")
    depth = path.count("/")
    out = stamp_text(src, path, depth)
    if out != src:
        p.write_text(out, encoding="utf-8")
        return True
    return False


STATIC = ["home.html", "teams.html", "awards.html", "history.html",
          "analytics.html", "weekend.html", "rankings.html", "draft-grades.html",
          "matchups/index.html"]


def stamp_all(extra=()):
    pages = list(STATIC) + [str(p.relative_to(ROOT)) for p in sorted((ROOT / "matchups").glob("*-week-*.html"))]
    pages += list(extra)
    changed = []
    for pg in pages:
        if (ROOT / pg).exists() and stamp(pg):
            changed.append(pg)
    return changed


if __name__ == "__main__":
    for pg in stamp_all():
        print("stamped", pg)
