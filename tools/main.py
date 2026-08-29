#!/usr/bin/env python3
"""Generate Players League matchup pages.

  python3 tools/main.py preview            # this week, force preview
  python3 tools/main.py recap  --week 10 --season 2025
  python3 tools/main.py auto               # detect phase from ESPN state
  python3 tools/main.py auto  --dry        # no AI calls, placeholder copy
"""
import argparse, datetime, json, sys
from lib import ROOT, load_env
import league as L
import render as R

DATA = ROOT / "tools" / "data"


def _placeholder(m, phase):
    a, h = m["away"]["owner"], m["home"]["owner"]
    return {"headline": f"{a} at {h}",
            "body": f"[dry run — {phase} copy not generated]\n"
                    f"Projected {m['away']['projected']}-{m['home']['projected']}."
                    if phase == "preview"
                    else f"[dry run]\nFinal {m['away']['actual']}-{m['home']['actual']}."}


def run(phase_arg, season, week, dry, force=False):
    load_env()
    phase = None if phase_arg == "auto" else phase_arg
    data = L.build(season, week, phase)
    wk, phase = data["week"], data["phase"]
    print(f"season {season} · week {wk} · phase {phase} · {len(data['matchups'])} matchups")

    if not data["matchups"]:
        print("no matchups for this week — nothing to do"); return None

    out = ROOT / "matchups" / f"{season}-week-{wk:02d}.html"
    if phase == "preview" and out.exists() and "PREVIEW" in out.read_text() and not force:
        print(f"{out.name} preview already exists — skipping (use --force to rebuild)")
        return None
    if phase == "recap" and not all(m["played"] for m in data["matchups"]) and not force:
        print("recap requested but not all games are final — skipping"); return None

    if dry:
        copies = [_placeholder(m, phase) for m in data["matchups"]]
        intro = f"[dry run] Week {wk} {phase}."
    else:
        import write as W
        copies = []
        for i, m in enumerate(data["matchups"], 1):
            print(f"  writing {i}/{len(data['matchups'])}: "
                  f"{m['away']['owner']} at {m['home']['owner']}")
            copies.append(W.write_matchup(m, wk, phase))
        intro = W.write_intro(data, wk, phase)

    page = R.week_page(data, copies, intro)
    R.index_page(season)

    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"{season}-week-{wk:02d}.json").write_text(json.dumps(
        {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
         "phase": phase, "data": data, "copies": copies, "intro": intro}, indent=2))
    print(f"wrote {page.relative_to(ROOT)}")
    return page


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["auto", "preview", "recap"], nargs="?", default="auto")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    run(a.phase, a.season, a.week, a.dry, a.force)
