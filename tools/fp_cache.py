"""Refresh a cached consensus-rankings snapshot for live fantasy Q&A in chat.

Reuses sources.consensus() — the same ESPN+FantasyPros+FantasyCalc+Sleeper
blend and the same FantasyPros auth-with-fallback logic already used by
draft.py — so this never re-guesses the API shape and degrades the same way
(free feed) if the authenticated call fails.

Run on a timer by .github/workflows/fantasypros-cache.yml. The API key only
ever exists inside that GitHub Actions runner; this script's job is to turn
it into a plain data file (data/fantasypros-cache.json) that is safe to read
from anywhere, including a chat session that must never hold the key itself.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib import load_env
from sources import consensus

OUT = os.path.join(os.path.dirname(__file__), "data", "fantasypros-cache.json")


def main():
    load_env()
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    c = consensus(season)
    rows = sorted(
        (v for v in c.values() if v["consensus_rank"]),
        key=lambda v: v["consensus_rank"],
    )
    snapshot = {
        "season": season,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fantasypros_authenticated": bool(os.environ.get("FANTASYPROS_API_KEY")),
        "players": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(snapshot, f, indent=1)
    print(
        f"wrote {OUT}: {len(rows)} players, "
        f"fp authenticated={snapshot['fantasypros_authenticated']}"
    )


if __name__ == "__main__":
    main()
