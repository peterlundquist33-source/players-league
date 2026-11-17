"""Per-player injury context from Sleeper's free NFL player database.

ESPN's league API gives a bare injuryStatus tag and often leaves it empty for
players who were hurt during the game. Sleeper carries status *and* body part
for the same players, with no auth and no key:

    A.J. Brown  -> Out, Hamstring
    Brock Bowers-> Out, Ankle

That is the difference between "missed projection by 11" and "missed projection
by 11 and is now out with an ankle".

The payload is ~14 MB, so it is cached to tools/data/sleeper-injuries.json and
only refetched when the cache is older than MAX_AGE_H hours.

Stdlib only, matching the rest of tools/.
"""
import json, re, time, urllib.request

from lib import TOOLS

URL = "https://api.sleeper.app/v1/players/nfl"
CACHE = TOOLS / "data" / "sleeper-injuries.json"
MAX_AGE_H = 6

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)
_NONWORD = re.compile(r"[^a-z0-9 ]")

# Sleeper statuses worth putting in front of the model. "Questionable" is kept
# because a questionable player who cratered is still the story; day-to-day
# noise below this bar is not.
MEANINGFUL = {"out", "doubtful", "questionable", "ir",
              "injured reserve", "pup", "sus", "suspended", "nfi", "dnr"}


def norm(name):
    """Match sources.py's normalization so the join key is identical."""
    n = (name or "").lower().replace(".", "").replace("'", "")
    n = _SUFFIX.sub("", n)
    n = _NONWORD.sub("", n).strip()
    return re.sub(r"\s+", " ", n)


def _fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "players-league/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def _fresh_cache():
    if not CACHE.exists():
        return None
    try:
        blob = json.loads(CACHE.read_text())
    except (ValueError, OSError):
        return None
    if time.time() - blob.get("fetched", 0) > MAX_AGE_H * 3600:
        return None
    return blob.get("players")


def load(force=False):
    """-> {"normalized name|POS": {"status": str, "part": str}}

    Only players carrying a meaningful designation are kept, which takes the
    cache from ~14 MB to a few KB.
    """
    if not force:
        cached = _fresh_cache()
        if cached is not None:
            return cached

    try:
        raw = _fetch()
    except Exception as e:                      # never block a recap on this
        print(f"injuries: Sleeper fetch failed ({e}) — continuing without")
        stale = CACHE.exists() and json.loads(CACHE.read_text()).get("players")
        return stale or {}

    out = {}
    for p in raw.values():
        status = (p.get("injury_status") or "").strip()
        name, pos = p.get("full_name"), p.get("position")
        if not status or not name or not pos:
            continue
        if status.lower() not in MEANINGFUL:
            continue
        entry = {"status": status}
        part = (p.get("injury_body_part") or "").strip()
        if part and part.lower() not in ("", "n/a", "not injury related"):
            entry["part"] = part
        note = (p.get("injury_notes") or "").strip()
        if note:
            entry["note"] = note[:140]
        out[f"{norm(name)}|{pos}"] = entry

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"fetched": time.time(), "players": out}, indent=1))
    return out


def describe(player, table):
    """-> "Out, hamstring" / "Questionable, ankle" / "" for one starter dict.

    Returns only what the source actually states. No timeline, no claim about
    when in the game it happened — the data does not say.
    """
    if not table:
        return ""
    hit = table.get(f'{norm(player.get("name"))}|{player.get("pos")}')
    if not hit:
        return ""
    bits = hit["status"]
    if hit.get("part"):
        bits += f', {hit["part"].lower()}'
    if hit.get("note"):
        bits += f' ({hit["note"]})'
    return bits
