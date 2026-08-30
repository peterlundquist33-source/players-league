"""Draft grades: every pick vs a 4-source consensus, curved across the league."""
import statistics
from lib import espn, load_env
from sources import consensus
from lore import owner

POS_ORDER = ["QB", "RB", "WR", "TE", "K", "D/ST"]
SKILL = {"QB", "RB", "WR", "TE"}          # only these count toward the grade


def _value_curve(rank):
    """Consensus overall rank -> a rough 'how much does this player help you' score."""
    if not rank:
        return 0.0
    return round(100.0 * (0.965 ** (rank - 1)), 2)   # ~100 at #1, ~32 at #33, ~13 at #60


def _roster_strength(skill_picks):
    """Best startable core (QB, 2RB, 2WR, TE, FLEX + 2 depth) by consensus value."""
    pool = sorted((p for p in skill_picks if p["consensus_rank"]),
                  key=lambda p: p["consensus_rank"])
    need = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
    core, used = [], set()
    for p in pool:
        if need.get(p["pos"], 0) > 0:
            core.append(p); used.add(id(p)); need[p["pos"]] -= 1
    for p in pool:                                   # FLEX
        if id(p) not in used and p["pos"] in ("RB", "WR", "TE"):
            core.append(p); used.add(id(p)); break
    for p in pool:                                   # 2 bench pieces
        if id(p) not in used:
            core.append(p); used.add(id(p))
        if len(core) >= 9:
            break
    return round(sum(_value_curve(p["consensus_rank"]) for p in core), 1)


def _round_weight(rnd):
    if not rnd:      return 0.5
    if rnd <= 5:     return 1.0
    if rnd <= 9:     return 0.7
    if rnd <= 13:    return 0.4
    return 0.2


def _clamp(v, lo=-50, hi=50):
    return max(lo, min(hi, v))


def _letter(z):
    """z = standard deviations above/below the league mean team score."""
    if z >= 0.9:  return "A" if z < 1.5 else "A+"
    if z >= 0.35: return "B+" if z >= 0.6 else "B"
    if z > -0.35: return "C+" if z >= 0.1 else ("C" if z > -0.15 else "C-")
    if z > -0.9:  return "D+" if z > -0.6 else "D"
    return "F"


def _pos_letter(avg):
    if avg is None:            return "—"
    if avg >= 14:  return "A"
    if avg >= 5:   return "B"
    if avg >= -5:  return "C"
    if avg >= -14: return "D"
    return "F"


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
        # Blend consensus rank and ADP into one "market slot" for this player.
        slots = [x for x in (cr, adp if adp and adp < 350 else None) if x]
        market = sum(slots) / len(slots) if slots else ov
        # Positive raw = drafted LATER than the market = value. Negative = reach.
        raw = ov - market if pos in SKILL else 0.0
        teams[tid]["picks"].append({
            "overall": ov, "round": rnd,
            "name": c.get("name") or pnames.get(pid, "?"),
            "pos": pos, "pro": c.get("pro", "?"), "bye": c.get("bye"),
            "pos_rank": c.get("pos_rank"),
            "consensus_rank": cr, "adp": adp, "market": round(market, 1),
            "raw": raw, "counts": pos in SKILL, "sources": c.get("sources", 0),
        })

    # Remove the league-wide systematic offset per round: grade each pick against
    # what the rest of the league got in that round, not an external ADP.
    from collections import defaultdict
    round_vals = defaultdict(list)
    for t in teams.values():
        for p in t["picks"]:
            if p["counts"]:
                round_vals[p["round"]].append(p["raw"])
    round_mean = {r: (sum(v) / len(v)) for r, v in round_vals.items()}
    for t in teams.values():
        for p in t["picks"]:
            adj = p["raw"] - round_mean.get(p["round"], 0.0) if p["counts"] else 0.0
            p["value"] = round(_clamp(adj, -40, 40), 1)
            p["weighted"] = round(p["value"] * _round_weight(p["round"]), 1)

    for tid, t in teams.items():
        skill = [p for p in t["picks"] if p["counts"]]
        t["efficiency"] = round(sum(p["weighted"] for p in skill), 1)
        t["strength"] = _roster_strength(skill)
        by_pos = {}
        for p in t["picks"]:
            by_pos.setdefault(p["pos"], []).append(p)
        t["_by_pos"] = by_pos
        # positional score = strength of the room (top 2-3 by consensus) + a nudge
        # for draft efficiency at that spot
        t["_pos_val"] = {}
        for pos in SKILL:
            ps = by_pos.get(pos, [])
            if not ps:
                t["_pos_val"][pos] = None
                continue
            keep = 1 if pos in ("QB", "TE") else 3
            best = sorted((p for p in ps if p["consensus_rank"]),
                          key=lambda p: p["consensus_rank"])[:keep]
            strength = sum(_value_curve(p["consensus_rank"]) for p in best)
            eff = sum(p["weighted"] for p in ps)
            t["_pos_val"][pos] = strength + 0.25 * eff
        graded = [p for p in skill if p["consensus_rank"]]
        top = max(graded, key=lambda p: p["value"]) if graded else None
        t["best"] = top if (top and top["value"] >= 8) else None
        worst = min(graded, key=lambda p: p["value"]) if graded else None
        t["reach"] = worst if (worst and worst["value"] <= -8) else None

    # positional sub-grades: relative to the league at that position
    for pos in POS_ORDER:
        vals = [t["_pos_val"].get(pos) for t in teams.values() if t["_pos_val"].get(pos) is not None] \
               if pos in SKILL else []
        mean = statistics.mean(vals) if vals else 0.0
        sd = (statistics.pstdev(vals) or 1.0) if vals else 1.0
        for t in teams.values():
            v = t["_pos_val"].get(pos) if pos in SKILL else None
            n = len(t["_by_pos"].get(pos, []))
            t.setdefault("pos_grades", {})[pos] = {
                "grade": _letter((v - mean) / sd) if v is not None else "—",
                "n": n}

    # Final grade = 65% roster strength (the team you built) + 35% draft efficiency
    # (value vs the market). Both z-scored so they combine fairly.
    def _z(vals):
        m = statistics.mean(vals); s = statistics.pstdev(vals) or 1.0
        return {i: (v - m) / s for i, v in enumerate(vals)}
    tl = list(teams.values())
    zs = _z([t["strength"] for t in tl])
    ze = _z([t["efficiency"] for t in tl])
    for i, t in enumerate(tl):
        t["score"] = round(zs[i] * 0.65 + ze[i] * 0.35, 3)

    ordered = sorted(tl, key=lambda t: -t["score"])
    mean, sd = statistics.mean(t["score"] for t in tl), (statistics.pstdev(t["score"] for t in tl) or 1.0)
    for i, t in enumerate(ordered, 1):
        t["rank"] = i
        t["grade"] = _letter((t["score"] - mean) / sd)

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
                      if t["pos_grades"][p]["grade"])
        print(f'{t["rank"]:2}. {t["grade"]:<2} {t["owner"]:<10} score {t["score"]:+6.1f}  [{pg}]')
        if t["best"]:
            print(f'      steal: {t["best"]["name"]} (#{t["best"]["overall"]}, '
                  f'consensus {t["best"]["consensus_rank"]}, {t["best"]["value"]:+.0f})')
        if t["reach"]:
            print(f'      reach: {t["reach"]["name"]} (#{t["reach"]["overall"]}, '
                  f'consensus {t["reach"]["consensus_rank"]}, {t["reach"]["value"]:+.0f})')
