#!/usr/bin/env python3
"""Generate Players League matchup pages.

  python3 tools/main.py preview            # this week, force preview
  python3 tools/main.py recap  --week 10 --season 2025
  python3 tools/main.py auto               # detect phase from ESPN state
  python3 tools/main.py auto  --dry        # no AI calls, placeholder copy
"""
import argparse, datetime, json, os, sys
from lib import ROOT, load_env
import league as L
import render as R
import homepage as HP
import analytics as AN

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

    # A recap with no explicit week targets the week that just finished, not the
    # current one (ESPN rolls currentMatchupPeriod forward right after MNF).
    if phase == "recap" and week is None:
        probe = L.build(season, None, None)
        week = max(1, probe["current_week"] - (0 if probe["phase"] == "recap" else 1))

    data = L.build(season, week, phase)
    wk, phase = data["week"], data["phase"]
    print(f"season {season} · week {wk} · phase {phase} · {len(data['matchups'])} matchups")

    # cheap, no-AI: refresh standings + expected-wins every run, even if the
    # matchup page itself is skipped below
    HP.update(season)
    AN.update(season)

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


def run_rankings(season, dry=False):
    load_env()
    # Draft grades are a one-time, accuracy-sensitive page — use the strongest model.
    os.environ.setdefault("ANTHROPIC_MODEL", "claude-opus-5")
    import draft as D
    g = D.build(season)
    print(f"{season} draft grades: " + ", ".join(f'{t["grade"]} {t["owner"]}' for t in g["teams"]))
    if dry:
        copies = [{"headline": f'{t["owner"]}: {t["grade"]}', "body": "[dry run]"} for t in g["teams"]]
        intro = "[dry run] draft grades"
    else:
        import write as W
        copies = []
        for t in g["teams"]:
            print(f"  grading {t['owner']} ({t['grade']})")
            copies.append(W.grade_team(t, season, g.get("extremes")))
        intro = W.grade_intro(g)
    page = R.rankings_page(g, copies, intro)
    HP.update(season)
    AN.update(season)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"{season}-rankings.json").write_text(json.dumps(
        {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
         "mode": g["mode"], "grades": g, "copies": copies, "intro": intro}, indent=2, default=str))
    print(f"wrote {page.relative_to(ROOT)}")
    return page


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["auto", "preview", "recap", "rankings"], nargs="?", default="auto")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.phase == "rankings":
        run_rankings(a.season, a.dry)
    else:
        run(a.phase, a.season, a.week, a.dry, a.force)
