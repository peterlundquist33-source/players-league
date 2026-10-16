"""One-off export: the complete draft board (every pick) to JSON.

Reuses draft.py's own ESPN fetch and pick parsing — draft.py already computes
every single pick, draft-grades.html just only narrates the notable ones.
This just dumps the full list, unfiltered, for ad-hoc analysis.

    python3 tools/draft_board.py [season]
"""
import json
import sys
from pathlib import Path

import draft


def main():
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    g = draft.build(season)

    picks = []
    for t in g["teams"]:
        for p in t["picks"]:
            picks.append({
                "overall": p["overall"],
                "round": p["round"],
                "owner": t["owner"],
                "team": t["team"],
                "name": p["name"],
                "pos": p["pos"],
                "pro": p["pro"],
            })
    picks.sort(key=lambda p: p["overall"] or 0)

    out = Path(__file__).resolve().parent / "data" / f"{season}-draft-board.json"
    out.write_text(json.dumps({"season": season, "picks": picks}, indent=2))
    print(f"wrote {len(picks)} picks to {out}")


if __name__ == "__main__":
    main()
