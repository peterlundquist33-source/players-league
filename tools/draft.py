"""Draft grades: every pick vs a 4-source consensus, curved across the league."""
import statistics
from lib import espn, load_env
from sources import consensus
from lore import owner

POS_ORDER = ["QB", "RB", "WR", "TE", "K", "D/ST"]
SKILL = {"QB", "RB", "WR", "TE"}          # only these count toward the grade


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
            "pos": pos, "consensus_rank": cr, "adp": adp, "market": round(market, 1),
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
        t["score"] = round(sum(p["weighted"] for p in skill), 1)
        by_pos = {}
        for p in t["picks"]:
            by_pos.setdefault(p["pos"], []).append(p)
        t["_by_pos"] = by_pos
        t["_pos_val"] = {pos: (sum(p["weighted"] for p in by_pos[pos]) if by_pos.get(pos) else None)
                         for pos in SKILL}
        early = [p for p in skill if p["round"] and p["round"] <= 9]
        top = max(early, key=lambda p: p["value"]) if early else None
        t["best"] = top if (top and top["value"] >= 8) else None
        worst = min(early, key=lambda p: p["value"]) if early else None
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

    scores = [t["score"] for t in teams.values()]
    mean, sd = statistics.mean(scores), (statistics.pstdev(scores) or 1.0)
    ordered = sorted(teams.values(), key=lambda t: -t["score"])
    for i, t in enumerate(ordered, 1):
        t["rank"] = i
        t["grade"] = _letter((t["score"] - mean) / sd)

    return {"season": season, "mode": "draft", "teams": ordered,
            "league_avg_value": round(mean, 1)}


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
