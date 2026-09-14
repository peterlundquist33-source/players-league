"""Monday Night Madness — the pre-MNF state of every matchup, plus the group-chat post.

Runs Monday afternoon, after the Sunday slate is final and before kickoff. For each
matchup we bank what's already scored, list every starter who still has a game to
play, and show ESPN's own win probability for both sides (the same number the app
shows). If ESPN ever stops sending it, a simple normal model on the remaining
starters' projections fills in and the page says so.
"""
import math, re
from lib import claude
from lore import LEAGUE_FACTS, owner
import nfl as NF


# --------------------------------------------------------------- game state

def game_states(season, week):
    """{TEAM_ABBR: 'pre' | 'in' | 'post'} from the public NFL scoreboard.
    Empty on failure — the caller then treats every game as final."""
    try:
        d = NF._get(NF.URL.format(week=week, season=season))
        events = d["content"]["sbData"]["events"]
    except Exception:
        return {}
    out = {}
    for ev in events:
        state = ((ev.get("status") or {}).get("type") or {}).get("state") or "post"
        for comp in ev.get("competitions", []):
            for t in comp.get("competitors", []):
                abbr = (t.get("team") or {}).get("abbreviation")
                if abbr:
                    out[NF.ALIAS.get(abbr, abbr)] = state
    return out


# --------------------------------------------------------------- the model

def _sd(proj):
    # a 15-point projection lands within roughly 15 +/- 9 two-thirds of the time
    return max(0.6 * proj, 3.0)


def _phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _pending(side, states):
    """Starters whose NFL game hasn't finished, with the points we still expect."""
    out = []
    for p in side["starters"]:
        st = states.get(p["pro"], "post")
        p["done"] = st == "post"
        if p["done"]:
            continue
        # a player mid-game keeps whatever is left of his projection
        left = p["proj"] if st == "pre" else max(p["proj"] - p["actual"], 0.0)
        out.append({"name": p["name"], "pos": p["pos"], "pro": p["pro"],
                    "proj": round(left, 1), "state": st})
    return out


def compute(league, states, author=None):
    """Attach a `madness` block to every matchup and return the league dict."""
    for m in league["matchups"]:
        a, h = m["away"], m["home"]
        ap, hp = _pending(a, states), _pending(h, states)
        a_exp = a["actual"] + sum(p["proj"] for p in ap)
        h_exp = h["actual"] + sum(p["proj"] for p in hp)
        var = sum(_sd(p["proj"]) ** 2 for p in ap + hp)
        source = "espn"
        if not ap and not hp:
            a_win = 1.0 if a["actual"] > h["actual"] else 0.0
        elif a.get("win_prob") is not None and h.get("win_prob") is not None:
            a_win = float(a["win_prob"])          # the number the ESPN app shows
        else:
            source = "model"
            a_win = _phi((a_exp - h_exp) / math.sqrt(var))
        lead, trail = (a, h) if a["actual"] >= h["actual"] else (h, a)
        m["madness"] = {
            "final": not ap and not hp,
            "away_pending": ap, "home_pending": hp,
            "away_win": round(100 * a_win), "home_win": round(100 * (1 - a_win)),
            "source": source,
            "away_expected": round(a_exp, 1), "home_expected": round(h_exp, 1),
            "leader": lead["owner"], "trailer": trail["owner"],
            "deficit": round(lead["actual"] - trail["actual"], 1),
        }
    league["madness_author"] = author or ""
    return league


# --------------------------------------------------------------- the post

SYSTEM = """\
You write the Players League's "Monday Night Madness" post: the Monday-afternoon
recap that goes in the league group chat before the Monday night game. 12-team
fantasy football league of close friends, 5th season. Voice: a guy in the league
texting the group — casual, funny, roasting people the way friends do, confident
with the numbers. Plain text. NO markdown, NO bullet points, NO emoji, NO hashtags,
NO em dashes or en dashes (use commas and periods), no fantasy-guru cliches.
Loose grammar is fine; polished magazine prose is not.

Format — follow it EXACTLY, it's a house style:

Week N Monday Night Madness

<one or two sentence opener about the week>

GGs

<for EVERY matchup that is FINAL: a line with the two TEAM NAMES "Team A vs Team B",
then ONE sentence. Who won, the one thing that decided it, a jab if it fits. One
sentence, not two. Separate matchups with a blank line.>

<then for EVERY matchup still ALIVE tonight, in order from least likely comeback to
most: a line with the underdog's win chance and owner (the side with the LOWER win
chance, whether or not they lead on points right now), like "8% Isaac", then
the two TEAM NAMES "Team A vs Team B", then 1-3 sentences that are ONLY about the
comeback: how many points the trailer needs, from which players still playing,
against what the leader has left, and whether that's realistic. No recap of Sunday,
no box scores from games already played. Use the numbers you're given.>

<one or two sentences of league-wide notes: high scorer of the week, a streak, a
standings note. Week 1 has no standings so skip those.>

Fun MNF game so send picks. I want a first TD winner. Good luck players and happy Monday!

Rules:
- Only use players, scores and numbers from the DATA block. Quote scores as given.
- Use owners' first names for people and the TEAM NAMES on the "vs" lines.
- If an AUTHOR is named, that owner is writing the post: refer to that owner's own
  matchup in the first person ("I", "my", "me") and never by name.
- Roast people with their own lineups and team names. Nothing about anyone's
  personal life, job, family, or anything outside the league.
- ~200-350 words total. Short. Output only the post, nothing before or after.
"""


def _lines(m):
    a, h, x = m["away"], m["home"], m["madness"]
    out = [f'{a["team"]} ({a["owner"]}) vs {h["team"]} ({h["owner"]})']
    out.append(f'  banked: {a["owner"]} {a["actual"]}, {h["owner"]} {h["actual"]}')
    if x["final"]:
        out.append(f'  FINAL — {m["winner"]} won by {m["margin"]}')
    else:
        out.append(f'  ALIVE — {x["leader"]} leads {x["trailer"]} by {x["deficit"]}; '
                   f'win chance {a["owner"]} {x["away_win"]}%, {h["owner"]} {x["home_win"]}%')
        for side, pend in ((a, x["away_pending"]), (h, x["home_pending"])):
            if pend:
                out.append(f'  {side["owner"]} still playing: ' + ", ".join(
                    f'{p["name"]} ({p["pos"]} {p["pro"]}, proj {p["proj"]})' for p in pend))
            else:
                out.append(f'  {side["owner"]} is done')
    # the day's notable box-score lines, so the roast has material
    for side in (a, h):
        st = sorted(side["starters"], key=lambda p: p["actual"])
        lo = [p for p in st if p["actual"] <= 2 and p.get("done", True)]
        hi = sorted(side["starters"], key=lambda p: -p["actual"])[:2]
        if hi:
            out.append(f'  {side["owner"]} best: ' + ", ".join(f'{p["name"]} {p["actual"]}' for p in hi))
        if lo:
            out.append(f'  {side["owner"]} duds: ' + ", ".join(f'{p["name"]} {p["actual"]}' for p in lo))
    return "\n".join(out)


def write_post(league):
    wk = league["week"]
    finals = [m for m in league["matchups"] if m["madness"]["final"]]
    alive = sorted((m for m in league["matchups"] if not m["madness"]["final"]),
                   key=lambda m: min(m["madness"]["away_win"], m["madness"]["home_win"]))
    top = max(league["matchups"], key=lambda m: max(m["away"]["actual"], m["home"]["actual"]))
    top_side = max((top["away"], top["home"]), key=lambda s: s["actual"])
    data = "\n\n".join(_lines(m) for m in finals + alive)
    standings = "\n".join(f'{owner(s["owner"])}: {s["record"]}, {s["pf"]} PF'
                          for s in league["standings"])
    author = league.get("madness_author") or ""
    user = (
        f"League background (light touch):\n{LEAGUE_FACTS}\n\n"
        f"Week {wk}. {len(finals)} matchups final, {len(alive)} alive tonight.\n"
        f"Current high score: {top_side['owner']} {top_side['actual']}.\n"
        + (f"AUTHOR: {author}\n" if author else "")
        + f"\nDATA:\n{data}\n\nStandings:\n{standings}\n\nWrite the Week {wk} post."
    )
    allowed = set(re.findall(r"\b\d{2,3}\.\d\b", user))
    text = ""
    for attempt in range(2):
        text = claude(SYSTEM, user, max_tokens=2000).strip()
        text = text.replace("—", ",").replace("–", ",")
        bad = [n for n in set(re.findall(r"\b\d{2,3}\.\d\b", text)) if n not in allowed]
        if not bad:
            break
        user += ("\n\nREWRITE — these numbers are not in the data: " + ", ".join(bad)
                 + ". Quote scores exactly as given. Same format.")
        print("      fact-check retry:", ", ".join(bad)[:100])
    return text


def placeholder(league):
    wk = league["week"]
    rows = []
    for m in league["matchups"]:
        a, h, x = m["away"], m["home"], m["madness"]
        tag = "FINAL" if x["final"] else f'{x["away_win"]}% / {x["home_win"]}%'
        rows.append(f'{a["team"]} vs {h["team"]}\n[dry run] {a["actual"]} - {h["actual"]} {tag}')
    return (f"Week {wk} Monday Night Madness\n\n[dry run]\n\nGGs\n\n" + "\n\n".join(rows)
            + "\n\nFun MNF game so send picks. I want a first TD winner. "
              "Good luck players and happy Monday!")
