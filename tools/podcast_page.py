"""Render podcast.html from podcast/episodes.json: newest episode featured, the rest
as a library grid. Episodes without a YouTube id are skipped (not published yet).

    python3 tools/podcast_page.py
"""
import html, json, re
from lib import ROOT

EPISODES = ROOT / "podcast" / "episodes.json"
PAGE = ROOT / "podcast.html"


def _thumb(e):
    return e.get("card") or f'https://img.youtube.com/vi/{e["youtube"]}/hqdefault.jpg'


def _embed(e):
    return (f'<div class="podcast-embed"><iframe src="https://www.youtube-nocookie.com/embed/{e["youtube"]}" '
            f'title="Players League Podcast — Episode {e["n"]}: {html.escape(e["title"])}" loading="lazy" '
            f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
            f'referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe></div>')


def render(episodes):
    eps = [e for e in episodes if e.get("youtube")]
    eps.sort(key=lambda e: e["n"], reverse=True)
    if not eps:
        return '<section class="page-header"><span class="eyebrow">Podcast</span><h1>The <span class="gold">Podcast</span></h1><p>First episode coming soon.</p></section>'
    latest, rest = eps[0], eps[1:]
    out = ['<section class="page-header"><span class="eyebrow">Podcast</span>'
           '<h1>The <span class="gold">Podcast</span></h1>'
           '<p>The whole league, on video, every week. Newest episode first; the library lives below.</p></section>']
    out.append(f'<section class="section" id="ep{latest["n"]}">'
               f'<span class="eyebrow">Episode {latest["n"]} &middot; Week {latest["week"]}, {latest["season"]}</span>'
               f'<h2 class="section-title">{html.escape(latest["title"])}</h2>'
               f'<p class="section-sub">{html.escape(latest["blurb"])}</p>{_embed(latest)}'
               f'<div class="podcast-notes"><p>{html.escape(latest["notes"])}</p></div></section>')
    if rest:
        cards = "".join(
            f'<a class="pod-card" href="https://www.youtube.com/watch?v={e["youtube"]}" target="_blank" rel="noopener">'
            f'<img src="{_thumb(e)}" alt="" loading="lazy">'
            f'<div class="pod-card-body"><span class="eyebrow">Episode {e["n"]} &middot; Week {e["week"]}, {e["season"]}</span>'
            f'<h3>{html.escape(e["title"])}</h3><p>{html.escape(e["blurb"])}</p></div></a>'
            for e in rest)
        out.append(f'<section class="section"><span class="eyebrow">Library</span>'
                   f'<h2 class="section-title">Every Episode</h2>'
                   f'<p class="section-sub">{len(eps)} episodes and counting. Tap one to watch it on YouTube.</p>'
                   f'<div class="pod-grid">{cards}</div></section>')
    return "\n".join(out)


def update():
    episodes = json.loads(EPISODES.read_text())
    src = PAGE.read_text()
    body = render(episodes)
    if "<!-- NAV:end -->" not in src or "<!-- FOOTER:start -->" not in src:
        raise SystemExit("podcast.html markers not found")
    new = re.sub(r"(<!-- NAV:end -->\n)(.*?)(\n<!-- FOOTER:start -->)", lambda m: m.group(1) + body + m.group(3), src, flags=re.S)
    if new != src:
        PAGE.write_text(new)
    print("wrote podcast.html" if new != src else "podcast.html unchanged")


if __name__ == "__main__":
    update()
