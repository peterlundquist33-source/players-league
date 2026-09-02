"""Weekly power rankings — a hybrid: a deterministic model sets the board, the AI
may nudge a team at most 2 spots.

The model score (0-100) blends two halves:

  RESULTS  — what you've actually done: all-play win%, real win%, points-for index,
             and recent form (last 3 weeks all-play).
  ROSTER   — what you're holding right now: next week's optimal-lineup projection,
             plus the draft-grade roster score as a preseason anchor.

The weight shifts from roster to results as the season goes: week 1 is still mostly
about the roster you drafted, by week 6+ it's ~80% what you've done on the field.
Preseason (no games played) the score is pure roster — that's the Week 0 board.

Every number here is computed, never guessed; the AI only writes copy and proposes
small ordering nudges that this module validates before applying.
"""
import json
from lib import ROOT, load_env
from lore import owner as canon
import analytics as AN
import league as L

DATA = ROOT / "tools" / "data"

# how fast results take over from roster strength
RESULTS_CAP = 0.80
RESULTS_PER_GAME = 0.13

# results sub-score weights
W_ALLPLAY, W_WINPCT, W_PF, W_FORM = 0.38, 0.18, 0.27, 0.17
# roster: the draft anchor fades out as live projections pile up
DRAFT_W0, DRAFT_DECAY = 0.40, 0.05

# roster strength is averaged over this many upcoming weeks so a bye week
# doesn't yank a team down the board for a reason nobody controls
ROSTER_WEEKS = 3

FORM_WEEKS = 3
MAX_NUDGE = 2


# ---------------------------------------------------------------- scaling

def _index(vals, spread=12.0):
    """{key: raw} -> {key: 0-100 index}, 50 = league average, ~1 sd = 12 points."""
    ks = list(vals)
    if not ks:
        return {}
    xs = [vals[k] for k in ks]
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / len(xs)
    sd = var ** 0.5
    if sd < 1e-9:
        return {k: 50.0 for k in ks}
    return {k: max(0.0, min(100.0, 50.0 + spread * (vals[k] - mean) / sd)) for k in ks}


def _allplay(scores_by_week, weeks, owners):
    """-> {owner: (allplay_wins, allplay_losses, allplay_ties)} over `weeks`."""
    rec = {o: [0, 0, 0] for o in owners}
    for w in weeks:
        sc = scores_by_week.get(w, {})
        for o, s in sc.items():
            for x, xs in sc.items():
                if x == o:
                    continue
                if s > xs:
                    rec[o][0] += 1
                elif s < xs:
                    rec[o][1] += 1
                else:
                    rec[o][2] += 1
    return rec


def _pct(rec):
    w, l, t = rec
    n = w + l + t
    return (w + 0.5 * t) / n if n else 0.0


def _rank_map(vals, high_is_better=True):
    """{key: value} -> {key: 'Nth of M'} with ties sharing a rank (T-3rd)."""
    ks = [k for k in vals if vals[k] is not None]
    if not ks:
        return {}
    n = len(ks)
    order = sorted(ks, key=lambda k: vals[k], reverse=high_is_better)
    out, i = {}, 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        pos = i + 1
        sfx = "th" if 11 <= pos % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(pos % 10, "th")
        label = f"{'T-' if j > i else ''}{pos}{sfx} of {n}"
        for k in order[i:j + 1]:
            out[k] = label
        i = j + 1
    return out


# ---------------------------------------------------------------- inputs

def _draft_anchor(season):
    """{owner: roster_score} from the cached draft grades, if we have them."""
    f = DATA / f"{season}-rankings.json"
    if not f.exists():
        return {}
    try:
        g = json.loads(f.read_text())["grades"]
    except Exception:
        return {}
    return {t["owner"]: t["roster_score"] for t in g.get("teams", [])
            if t.get("roster_score") is not None}


def _roster_view(season, week):
    """League build for `week`, falling back to the last week that has matchups."""
    lg = L.build(season, week, "preview")
    if not lg["matchups"] and week > 1:
        lg = L.build(season, week - 1, "preview")
    return lg


def _sides_by_owner(lg):
    out = {}
    for m in lg["matchups"]:
        for side in (m["away"], m["home"]):
            out[side["owner"]] = side
    return out


def _roster_strength(season, week):
    """(avg optimal projection by owner, sides for `week`, next opponent by owner).

    Averaged over the next ROSTER_WEEKS so byes wash out. Weeks with no schedule
    (past the regular season) are simply skipped.
    """
    lg = _roster_view(season, week)
    sides = _sides_by_owner(lg)
    opp = {}
    for m in lg["matchups"]:
        opp[m["away"]["owner"]] = m["home"]["owner"]
        opp[m["home"]["owner"]] = m["away"]["owner"]

    totals = {o: [s["optimal_proj"]] for o, s in sides.items()}
    for w in range(week + 1, week + ROSTER_WEEKS):
        try:
            extra = _sides_by_owner(L.build(season, w, "preview"))
        except SystemExit:
            break
        if not extra:
            break
        for o, s in extra.items():
            if o in totals and s["optimal_proj"]:
                totals[o].append(s["optimal_proj"])
    proj = {o: sum(v) / len(v) for o, v in totals.items() if v}
    return proj, sides, opp


def _top_options(players, pos, n):
    ps = sorted((p for p in players if p["pos"] == pos), key=lambda x: -x["proj"])[:n]
    return ps


# ---------------------------------------------------------------- compute

def compute(season, through_week=None):
    load_env()
    p = AN._pull(season)
    weeks = [w for w in p["weeks"] if through_week is None or w <= through_week]
    owners = p["owners"]
    gp = len(weeks)

    next_week = (weeks[-1] + 1) if weeks else 1
    proj_raw, sides, opp = _roster_strength(season, next_week)

    # ---- results half ----
    ap_all = _allplay(p["scores"], weeks, owners)
    form_weeks = weeks[-FORM_WEEKS:]
    ap_form = _allplay(p["scores"], form_weeks, owners)

    # record/streak are computed from the weeks we pulled, so they always agree
    # with the rest of the board (ESPN's live standings would be the FULL season)
    wins = {o: 0.0 for o in owners}
    wlt = {o: [0, 0, 0] for o in owners}
    pf = {o: 0.0 for o in owners}
    pa = {o: 0.0 for o in owners}
    for w in weeks:
        sc, res = p["scores"][w], p["result"][w]
        for o in owners:
            if o not in sc:
                continue
            pf[o] += sc[o]
            pa[o] += sc[p["opp"][w][o]]
            r = res[o]
            wins[o] += 1.0 if r == "W" else 0.5 if r == "T" else 0.0
            wlt[o][0 if r == "W" else 1 if r == "L" else 2] += 1

    def _streak(o):
        seq = [p["result"][w][o] for w in weeks if o in p["result"][w]]
        if not seq:
            return ""
        last, n = seq[-1], 1
        for r in reversed(seq[:-1]):
            if r != last:
                break
            n += 1
        return f"{last}{n}"

    pf_pg = {o: (pf[o] / gp if gp else 0.0) for o in owners}
    pf_ix = _index(pf_pg) if gp else {o: 50.0 for o in owners}

    results = {}
    for o in owners:
        results[o] = (W_ALLPLAY * _pct(ap_all[o]) * 100
                      + W_WINPCT * (wins[o] / gp * 100 if gp else 0.0)
                      + W_PF * pf_ix[o]
                      + W_FORM * _pct(ap_form[o]) * 100)

    # ---- roster half ----
    proj_ix = _index({o: v for o, v in proj_raw.items() if v}) if any(proj_raw.values()) else {}
    draft_raw = _draft_anchor(season)
    draft_ix = _index(draft_raw) if draft_raw else {}
    w_draft = max(0.0, DRAFT_W0 - DRAFT_DECAY * gp)

    roster = {}
    for o in owners:
        parts, wts = [], []
        if o in proj_ix:
            parts.append(proj_ix[o]); wts.append(1.0 - w_draft)
        if o in draft_ix and w_draft > 0:
            parts.append(draft_ix[o]); wts.append(w_draft)
        tot = sum(wts)
        roster[o] = (sum(v * w for v, w in zip(parts, wts)) / tot) if tot else 50.0

    # ---- blend ----
    w_res = min(RESULTS_CAP, RESULTS_PER_GAME * gp)
    rows = []
    for o in owners:
        score = w_res * results[o] + (1 - w_res) * roster[o]
        last3 = [p["scores"][w][o] for w in form_weeks if o in p["scores"][w]]
        wk_scores = {w: p["scores"][w][o] for w in weeks if o in p["scores"][w]}
        best = max(wk_scores.items(), key=lambda kv: kv[1], default=None)
        worst = min(wk_scores.items(), key=lambda kv: kv[1], default=None)
        side = sides.get(o, {})
        w_, l_, t_ = wlt[o]
        rows.append({
            "owner": o,
            "team": side.get("team") or p["tname"].get(o, ""),
            "score": round(score, 1),
            "results_score": round(results[o], 1),
            "roster_score": round(roster[o], 1),
            "gp": gp,
            "record": f"{w_}-{l_}" + (f"-{t_}" if t_ else ""),
            "streak": _streak(o),
            "pf": round(pf[o], 1), "pa": round(pa[o], 1),
            "pf_pg": round(pf_pg[o], 1),
            "allplay": tuple(ap_all[o]),
            "allplay_pct": round(_pct(ap_all[o]) * 100, 1),
            "form": tuple(ap_form[o]),
            "form_pct": round(_pct(ap_form[o]) * 100, 1),
            "luck": round(wins[o] - _pct(ap_all[o]) * gp, 1),
            "last3": last3,
            "best_week": best, "worst_week": worst,
            "proj_next": side.get("optimal_proj"),
            "proj_avg": round(proj_raw[o], 1) if proj_raw.get(o) else None,
            "next_opp": opp.get(o),
            "draft_roster": draft_raw.get(o),
            "players": side.get("players", []),
        })

    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows, 1):
        r["base_rank"] = i
        r["rank"] = i

    # league rank on each stat, so the writer can make comparative claims that are
    # actually checkable instead of guessing at the rest of the board
    by = {r["owner"]: r for r in rows}
    for field, better_high in (("pf_pg", True), ("pf", True), ("pa", False),
                               ("allplay_pct", True), ("form_pct", True),
                               ("proj_avg", True), ("draft_roster", True),
                               ("luck", True)):
        rk = _rank_map({o: v[field] for o, v in by.items()}, better_high)
        for o, label in rk.items():
            by[o].setdefault("ranks", {})[field] = label

    return {
        "season": season,
        "week": weeks[-1] if weeks else 0,
        "next_week": next_week,
        "gp": gp,
        "w_results": round(w_res, 2),
        "rows": rows,
    }


# ---------------------------------------------------------------- movement

def previous(season, week):
    """The most recent stored board before `week`, for movement arrows."""
    best = None
    for f in sorted(DATA.glob(f"{season}-power-week-*.json")):
        try:
            n = int(f.stem.split("-")[-1])
        except ValueError:
            continue
        if n < week:
            best = f
    if best is None:
        return {}
    try:
        d = json.loads(best.read_text())
    except Exception:
        return {}
    return {r["owner"]: r["rank"] for r in d.get("board", {}).get("rows", [])}


def apply_movement(board, season):
    prev = previous(season, board["week"])
    for r in board["rows"]:
        pr = prev.get(r["owner"])
        r["prev_rank"] = pr
        r["move"] = (pr - r["rank"]) if pr else 0
    board["has_prev"] = bool(prev)
    return board


# ---------------------------------------------------------------- AI nudge

def apply_nudge(board, deltas):
    """deltas = {owner: int}. Re-sort by (base_rank - delta) and re-rank.

    Any team that ends up more than MAX_NUDGE off its model rank gets pulled back,
    so the AI can lean on the board but never overturn it.
    """
    rows = board["rows"]
    d = {r["owner"]: max(-MAX_NUDGE, min(MAX_NUDGE, int(deltas.get(r["owner"], 0))))
         for r in rows}

    def _key(r):
        delta = d[r["owner"]]
        # the half-step makes a moved team land past the team it's passing rather
        # than tying with it — without it, a swap (one down, one up) cancels out
        bump = 0.5 if delta < 0 else -0.5 if delta > 0 else 0.0
        return (r["base_rank"] - delta + bump, r["base_rank"])

    ordered = sorted(rows, key=_key)
    for i, r in enumerate(ordered, 1):
        if abs(i - r["base_rank"]) > MAX_NUDGE:      # interaction pushed it too far
            d[r["owner"]] = 0
            ordered = sorted(rows, key=_key)
            break
    for i, r in enumerate(ordered, 1):
        r["rank"] = i
        r["nudge"] = r["base_rank"] - i
    board["rows"] = ordered
    return board


# ---------------------------------------------------------------- fact block

def _fmt_rec(t):
    w, l, ti = t
    return f"{w}-{l}" + (f"-{ti}" if ti else "")


def team_facts(r, board):
    """The per-team DATA block handed to the writer. Every line is computed.

    Anything with "(Nth of 12)" is a verified league rank — those are the only
    comparative claims the writer is allowed to make.
    """
    gp = r["gp"]
    rk = r.get("ranks", {})

    def at(field):
        return f' ({rk[field]} in the league)' if field in rk else ''

    out = [f'{r["owner"]} ("{r["team"]}") — ranked #{r["rank"]} of 12 this week, '
           f'power score {r["score"]:.1f}.']
    if r.get("prev_rank"):
        mv = r["move"]
        out.append(f'Last week they were #{r["prev_rank"]} ('
                   + (f'up {mv} spot{"s" if mv > 1 else ""}' if mv > 0
                      else f'down {abs(mv)} spot{"s" if mv < -1 else ""}' if mv < 0
                      else 'no change') + ').')
    if gp:
        out += [
            f'Record {r["record"]}' + (f', currently on a {r["streak"]} streak' if r["streak"] else '') + '.',
            f'Points for {r["pf"]:.1f}, an average of {r["pf_pg"]:.1f} per game{at("pf_pg")}. '
            f'Points against {r["pa"]:.1f}'
            + (f' ({rk["pa"].replace(" of ", "-fewest of ")})' if "pa" in rk else '') + '.',
            f'All-play record {_fmt_rec(r["allplay"])} — {r["allplay_pct"]:.0f}% '
            f'{at("allplay_pct").strip()} — that is their record if they had played every '
            f'team every week. It is the truest read on how well they have scored.',
            f'Luck {r["luck"]:+.1f} wins vs expected'
            + (f' ({rk["luck"].replace(" of ", "-luckiest of ")})' if "luck" in rk else '')
            + (' — winning more than their scores earned.' if r["luck"] >= 0.5
               else ' — scoring well and losing anyway.' if r["luck"] <= -0.5
               else ' — about fair.'),
        ]
        if r["last3"]:
            out.append(f'Last {len(r["last3"])} weeks they scored '
                       + ", ".join(f"{s:.1f}" for s in r["last3"])
                       + f' — all-play {_fmt_rec(r["form"])} over that stretch, '
                       f'{r["form_pct"]:.0f}%{at("form_pct")}.')
        if r["best_week"]:
            out.append(f'Season high {r["best_week"][1]:.1f} (week {r["best_week"][0]}), '
                       f'season low {r["worst_week"][1]:.1f} (week {r["worst_week"][0]}).')
    else:
        out.append('No games have been played yet — this is the preseason board.')

    if r.get("draft_roster") is not None:
        out.append(f'\nDraft grade: their draft-night roster scored '
                   f'{r["draft_roster"]:.0f} out of 100{at("draft_roster")}. That is a '
                   f'DIFFERENT number from the power score above — do not mix them up, and '
                   f'do not call it a "roster score".')
    out.append(f'\nHow the power score was built (these are league-relative indexes where '
               f'50 = league average, NOT grades out of 100 — never quote them as "X/100"): '
               f'results index {r["results_score"]:.0f}, roster index {r["roster_score"]:.0f}. '
               f'This week the score is {board["w_results"]*100:.0f}% results and '
               f'{(1-board["w_results"])*100:.0f}% roster.')

    ps = r.get("players", [])
    if ps:
        out.append('\nCurrent roster — best options by position (projected pts next week):')
        for pos, n in (("QB", 2), ("RB", 3), ("WR", 3), ("TE", 2)):
            top = _top_options(ps, pos, n)
            if top:
                out.append(f'  {pos}: ' + ", ".join(
                    f'{x["name"]} ({x["pro"]}, {x["proj"]:.0f}'
                    + (f', {x["injury"]}' if x.get("injury") else '') + ')' for x in top))
    if r.get("proj_avg") is not None:
        out.append(f'\nRoster projection: this roster projects to score about '
                   f'{r["proj_avg"]:.0f} a week from its best lineup{at("proj_avg")}, '
                   f'averaged over the next few weeks so byes do not distort it.')
    if r.get("proj_next"):
        out.append(f'Week {board["next_week"]} best-lineup projection {r["proj_next"]:.0f}'
                   + (f', against {r["next_opp"]}.' if r.get("next_opp") else '.'))
    return "\n".join(out)


def board_lines(board):
    """One-line-per-team summary of the whole board, for the nudge + intro prompts."""
    out = []
    for r in board["rows"]:
        bits = [f'{r["rank"]:2}. {r["owner"]:<10} score {r["score"]:5.1f}']
        if r["gp"]:
            bits.append(f'{r["record"]:<6} {r["pf_pg"]:.1f}/gm  all-play {r["allplay_pct"]:.0f}%'
                        f'  luck {r["luck"]:+.1f}  form {r["form_pct"]:.0f}%')
        else:
            bits.append(f'draft {r["draft_roster"]:.1f}' if r.get("draft_roster") else '')
        if r.get("proj_next") is not None:
            bits.append(f'next-wk proj {r["proj_next"]:.0f}')
        out.append("  ".join(b for b in bits if b))
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    wk = int(sys.argv[2]) if len(sys.argv) > 2 else None
    b = apply_movement(compute(season, wk), season)
    print(f'season {season} · through week {b["week"]} · {b["gp"]} games · '
          f'results weight {b["w_results"]}')
    print(board_lines(b))
