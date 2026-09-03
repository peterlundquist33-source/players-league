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
import facts as FA
import records as RC

DATA = ROOT / "tools" / "data"


def _placeholder(m, phase):
    a, h = m["away"]["owner"], m["home"]["owner"]
    return {"headline": f"{a} at {h}",
            "body": f"[dry run — {phase} copy not generated]\n"
                    f"Projected {m['away']['projected']}-{m['home']['projected']}."
                    if phase == "preview"
                    else f"[dry run]\nFinal {m['away']['actual']}-{m['home']['actual']}."}


def _build_context(season, week, phase, data=None):
    """Season form + power rank + real NFL lines, fetched once and shared by every
    matchup in the run. Any piece that fails just goes missing from the fact block."""
    ctx = {"season": season, "week": week}
    # every rostered player in the league -> their manager, so the fact-checker can
    # catch copy that hands one manager's player to another
    if data:
        pool = {}
        for mm in data.get("matchups", []):
            for side in (mm["away"], mm["home"]):
                for p in side.get("players", []):
                    pool[p["name"]] = side["owner"]
        ctx["all_players"] = pool
    # form through the last completed week (a preview shouldn't see this week's scores)
    through = week - 1 if phase == "preview" else week
    try:
        import power as PW
        ctx["results"] = PW.results_context(season, through)
        ctx["power"] = PW.latest_board(season)
    except Exception as e:
        print(f"  season context unavailable: {e}")
    if phase == "preview":
        try:
            import nfl as NF
            ctx["nfl"] = NF.games(season, week)
            print(f'  NFL lines: {len(ctx["nfl"])} teams')
        except Exception as e:
            print(f"  NFL lines unavailable: {e}")
    return ctx


def _attach_picks(season, week, matchups):
    """Hand each recap the pick its own preview made, so it can own the call."""
    f = DATA / f"{season}-week-{week:02d}.json"
    if not f.exists():
        return
    try:
        prev = json.loads(f.read_text())
    except Exception:
        return
    if prev.get("phase") != "preview":
        return
    by_pair = {}
    for mm, cc in zip(prev.get("data", {}).get("matchups", []), prev.get("copies", [])):
        if cc.get("pick"):
            by_pair[frozenset((mm["away"]["owner"], mm["home"]["owner"]))] = cc["pick"]
    for m in matchups:
        p = by_pair.get(frozenset((m["away"]["owner"], m["home"]["owner"])))
        if p:
            m["predicted"] = p
            m["week"] = week


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

    # cheap, no-AI: refresh standings + expected-wins + weekly-scoring records
    # every run, even if the matchup page itself is skipped below
    HP.update(season)
    AN.update(season)
    RC.update(season)

    # Teams-page fun facts: a few AI calls, so only on the weekly recap run (and
    # self-skips if team-facts.js is still fresh).
    if phase == "recap":
        FA.update(season)

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
        ctx = _build_context(season, wk, phase, data)
        if phase == "recap":
            _attach_picks(season, wk, data["matchups"])
        copies = []
        for i, m in enumerate(data["matchups"], 1):
            print(f"  writing {i}/{len(data['matchups'])}: "
                  f"{m['away']['owner']} at {m['home']['owner']}")
            copies.append(W.write_matchup(m, wk, phase, ctx))
        intro = W.write_intro(data, wk, phase)

    page = R.week_page(data, copies, intro)
    R.index_page(season)

    if phase == "preview" and not dry:
        try:
            import podcast as PC
            PC.build_csv(season, wk)
        except Exception as e:
            print(f"podcast prep skipped: {e}")

    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"{season}-week-{wk:02d}.json").write_text(json.dumps(
        {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
         "phase": phase, "data": data, "copies": copies, "intro": intro}, indent=2))
    print(f"wrote {page.relative_to(ROOT)}")

    # Tuesday recap doubles as the weekly power-rankings refresh.
    if phase == "recap":
        try:
            run_power(season, wk, dry)
        except Exception as e:
            print(f"power rankings skipped: {e}")
    return page


def run_power(season, week=None, dry=False):
    """Weekly power rankings — model board, AI nudge, AI copy, page."""
    load_env()
    import power as PW
    board = PW.compute(season, week)
    board_text = PW.board_lines(board)
    print(f'power board through week {board["week"]} '
          f'({board["gp"]} games, {board["w_results"]*100:.0f}% results)')

    reasons = []
    if dry:
        copies = [{"headline": f'#{r["rank"]} {r["owner"]}', "body": "[dry run]"}
                  for r in board["rows"]]
        intro = "[dry run] power rankings"
        PW.apply_movement(board, season)
    else:
        import write as W
        deltas, why = W.power_nudge(board, board_text)
        if deltas:
            PW.apply_nudge(board, deltas)
            board_text = PW.board_lines(board)
            # report what actually happened — teams nudging past each other means
            # the applied move often isn't the one that was asked for
            reasons = [f'{r["owner"]} {r["nudge"]:+d}'
                       + (f': {why[r["owner"]]}' if why.get(r["owner"]) else '')
                       for r in board["rows"] if r.get("nudge")]
            print("  nudges: " + ("; ".join(reasons) if reasons
                                  else "requested, but they cancelled out"))
        else:
            print("  nudges: none — model board stands")
        PW.apply_movement(board, season)
        copies = []
        for r in board["rows"]:
            print(f'  writing #{r["rank"]} {r["owner"]}')
            copies.append(W.power_team(r, board))
        intro = W.power_intro(board, board_text, reasons)

    page = R.power_page(board, copies, intro)
    DATA.mkdir(parents=True, exist_ok=True)
    slim = dict(board, rows=[{k: v for k, v in r.items() if k != "players"}
                             for r in board["rows"]])
    (DATA / f'{season}-power-week-{board["week"]:02d}.json').write_text(json.dumps(
        {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
         "board": slim, "copies": copies, "intro": intro, "nudges": reasons},
        indent=2, default=str))
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
    ap.add_argument("phase", choices=["auto", "preview", "recap", "rankings", "power", "site",
                                      "facts", "records"],
                    nargs="?", default="auto")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.phase == "rankings":
        run_rankings(a.season, a.dry)
    elif a.phase == "power":
        run_power(a.season, a.week, a.dry)
    elif a.phase == "site":
        import chrome as SITE
        for pg in SITE.stamp_all():
            print("stamped", pg)
    elif a.phase == "facts":
        FA.update(a.season, force=a.force)
    elif a.phase == "records":
        RC.update(a.season)
    else:
        run(a.phase, a.season, a.week, a.dry, a.force)
