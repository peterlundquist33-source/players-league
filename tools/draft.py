"""Draft grades: absolute (not curved) — a 0-100 score with a matching letter.

The score is mostly 'how good is the team you built' (roster quality, judged
against fixed positional benchmarks) with a small +/- for draft-value efficiency.
"""
from lib import espn, load_env
from sources import consensus
from lore import owner

POS_ORDER = ["QB", "RB", "WR", "TE", "K", "D/ST"]
SKILL = {"QB", "RB", "WR", "TE"}

# positional-rank ladders for a "solid starter" at each lineup spot
BENCH = {"QB": [12], "RB": [11, 24, 38], "WR": [13, 27, 41], "TE": [12]}
# weight of each spot toward the roster score
SLOT_W = {"QB": [1.0], "RB": [1.5, 1.2, 0.5], "WR": [1.5, 1.2, 0.9], "TE": [1.0]}


def _round_weight(rnd):
    if not rnd:      return 0.5
    if rnd <= 5:     return 1.0
    if rnd <= 9:     return 0.7
    if rnd <= 13:    return 0.4
    return 0.2


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _posrank_num(pr):
    """'RB14' -> 14 ; missing -> a deep number."""
    if not pr:
        return 999
    m = "".join(ch for ch in str(pr) if ch.isdigit())
    return int(m) if m else 999


def _lerp(x, x0, x1, y0, y1):
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _slot_score(r, bench):
    """positional rank r vs a 'solid starter' benchmark -> 0..100.
    elite ~100, at benchmark ~70, weak starter ~48, a hole ~10."""
    if r <= 0.35 * bench:
        return 100.0
    if r <= 0.8 * bench:
        return _lerp(r, 0.35 * bench, 0.8 * bench, 100, 80)
    if r <= 1.3 * bench:
        return _lerp(r, 0.8 * bench, 1.3 * bench, 80, 62)
    if r <= 2.2 * bench:
        return _lerp(r, 1.3 * bench, 2.2 * bench, 62, 20)
    if r <= 3.5 * bench:
        return _lerp(r, 2.2 * bench, 3.5 * bench, 20, 0)
    return 0.0


def _letter100(s):
    for cut, g in [(93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
                   (77, "C+"), (73, "C"), (70, "C-"), (67, "D+"), (63, "D"), (60, "D-")]:
        if s >= cut:
            return g
    return "F"


def _pos_assess(picks_at_pos, pos):
    """Best players at one position vs the benchmark ladder -> (0-100 score, letter)."""
    ranks = sorted(_posrank_num(p["pos_rank"]) for p in picks_at_pos)
    ladder = BENCH[pos]
    scores = [_slot_score(ranks[i] if i < len(ranks) else 999, ladder[i])
              for i in range(len(ladder))]
    val = round(sum(scores) / len(scores), 1)
    return val, _letter100(val)


def _roster_score(skill_picks):
    by_pos = {}
    for p in skill_picks:
        by_pos.setdefault(p["pos"], []).append(p)
    num, den = 0.0, 0.0
    for pos, ladder in BENCH.items():
        ranks = sorted(_posrank_num(p["pos_rank"]) for p in by_pos.get(pos, []))
        for i, b in enumerate(ladder):
            r = ranks[i] if i < len(ranks) else 999
            w = SLOT_W[pos][i]
            num += _slot_score(r, b) * w
            den += w
    return round(num / den, 1)


def build(season):
    load_env()
    cons = consensus(season)
    d = espn(["mDraftDetail", "mRoster", "mTeam"], season)

    teams = {}
    for t in d["teams"]:
        nm = (t.get("name") or "").strip()
        prim = t.get("primaryOwner")
        owner_name = nm
        for mem in d.get("members", []):
            if mem.get("id") == prim:
                owner_name = f'{mem.get("firstName","")} {mem.get("lastName","")}'.strip()
        teams[t["id"]] = {"team": nm, "owner": owner(owner_name), "picks": []}

    pnames = {}
    for t in d["teams"]:
        for e in t.get("roster", {}).get("entries", []):
            p = e["playerPoolEntry"]["player"]
            pnames[p["id"]] = p.get("fullName", "?")

    for pk in d["draftDetail"]["picks"]:
        tid, pid = pk.get("teamId"), pk.get("playerId")
        if tid not in teams:
            continue
        c = cons.get(pid, {})
        cr = c.get("consensus_rank")
        adp = c.get("adp")
        ov = pk.get("overallPickNumber")
        rnd = pk.get("roundId")
        pos = c.get("pos") or "?"
        # market slot = 5-source consensus rank (ADP left out — it's miscalibrated
        # for this league's draft habits and skews the late rounds).
        market = cr if cr else ov
        # Positive raw = drafted LATER than consensus = value. Negative = reach.
        raw = ov - market if pos in SKILL else 0.0
        teams[tid]["picks"].append({
            "overall": ov, "round": rnd,
            "name": c.get("name") or pnames.get(pid, "?"),
            "pos": pos, "pro": c.get("pro", "?"), "bye": c.get("bye"),
            "pos_rank": c.get("pos_rank"),
            "consensus_rank": cr, "adp": adp, "market": round(market, 1),
            "raw": raw, "counts": pos in SKILL, "sources": c.get("sources", 0),
        })

    # per-pick value vs consensus (absolute, no league de-bias)
    for t in teams.values():
        for p in t["picks"]:
            p["value"] = round(_clamp(p["raw"], -30, 30), 1) if p["counts"] else 0.0
            p["weighted"] = round(p["value"] * _round_weight(p["round"]), 1)

    for tid, t in teams.items():
        skill = [p for p in t["picks"] if p["counts"]]
        by_pos = {}
        for p in t["picks"]:
            by_pos.setdefault(p["pos"], []).append(p)
        t["_by_pos"] = by_pos
        t["roster_score"] = _roster_score(skill)
        t["_eff_raw"] = sum(p["weighted"] for p in skill if p["round"] and p["round"] <= 9)

    # value adjustment: how efficiently you drafted vs the league norm (this league
    # reaches slightly on average, so center it) -> small +/- on the absolute score
    _eff_mean = sum(t["_eff_raw"] for t in teams.values()) / len(teams)
    for tid, t in teams.items():
        skill = [p for p in t["picks"] if p["counts"]]
        by_pos = t["_by_pos"]
        t["efficiency"] = round(t["_eff_raw"], 1)
        t["value_adj"] = round(_clamp((t["_eff_raw"] - _eff_mean) / 9.0, -5.0, 5.0), 1)
        t["score"] = int(round(_clamp(t["roster_score"] + t["value_adj"], 0, 100)))
        t["grade"] = _letter100(t["score"])

        # absolute positional sub-grades
        t["pos_grades"] = {}
        for pos in POS_ORDER:
            ps = by_pos.get(pos, [])
            if pos in SKILL and ps:
                val, lt = _pos_assess(ps, pos)
                t["pos_grades"][pos] = {"grade": lt, "score": val, "n": len(ps)}
            else:
                t["pos_grades"][pos] = {"grade": "—", "score": None, "n": len(ps)}

        graded = [p for p in skill if p["consensus_rank"]]
        top = max((p for p in graded if p["round"] and p["round"] <= 12),
                  key=lambda p: p["value"], default=None)
        t["best"] = top if (top and top["value"] >= 8) else None
        worst = min((p for p in graded if p["round"] and p["round"] <= 9),
                    key=lambda p: p["value"], default=None)
        t["reach"] = worst if (worst and worst["value"] <= -8) else None

    tl = list(teams.values())
    ordered = sorted(tl, key=lambda t: -t["score"])
    for i, t in enumerate(ordered, 1):
        t["rank"] = i

    # League-wide extremes so writeups can reference the real ones, not guess.
    # Rounds 1-10 only — a round-13 backup swinging +/-40 is noise.
    all_skill = [dict(p, owner=t["owner"]) for t in tl for p in t["picks"]
                 if p["counts"] and p["consensus_rank"] and p["round"] and p["round"] <= 10]
    biggest_reach = min(all_skill, key=lambda p: p["value"])
    best_value = max(all_skill, key=lambda p: p["value"])
    extremes = {
        "biggest_reach": f'{biggest_reach["name"]} ({biggest_reach["owner"]}, '
                         f'round {biggest_reach["round"]}, {biggest_reach["value"]:.0f})',
        "best_value": f'{best_value["name"]} ({best_value["owner"]}, '
                      f'round {best_value["round"]}, +{best_value["value"]:.0f})',
    }
    return {"season": season, "mode": "draft", "teams": ordered, "extremes": extremes}


if __name__ == "__main__":
    g = build(2026)
    for t in g["teams"]:
        pg = " ".join(f'{p}:{t["pos_grades"][p]["grade"]}' for p in POS_ORDER
                      if t["pos_grades"][p]["grade"] != "—")
        print(f'{t["rank"]:2}. {t["grade"]:<2} {t["score"]:>3}/100  {t["owner"]:<10} '
              f'(roster {t["roster_score"]:.0f}, value {t["value_adj"]:+.1f})  [{pg}]')
        if t["best"]:
            print(f'      steal: {t["best"]["name"]} R{t["best"]["round"]} ({t["best"]["value"]:+.0f})')
        if t["reach"]:
            print(f'      reach: {t["reach"]["name"]} R{t["reach"]["round"]} ({t["reach"]["value"]:+.0f})')
