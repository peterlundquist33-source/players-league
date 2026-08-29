"""Shared helpers: env loading, ESPN client, Anthropic client. Stdlib only."""
import json, os, pathlib, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def load_env():
    """Load tools/.env into os.environ (does not override already-set vars — CI wins)."""
    f = TOOLS / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _get(name):
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"missing env var: {name} (set it in tools/.env or CI secrets)")
    return v


# ---------------------------------------------------------------- ESPN

ESPN_HOST = "https://lm-api-reads.fantasy.espn.com"


def espn(views, season, scoring_period=None):
    league = _get("LEAGUE_ID")
    q = "&".join(f"view={v}" for v in views)
    if scoring_period is not None:
        q += f"&scoringPeriodId={scoring_period}"
    url = f"{ESPN_HOST}/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league}?{q}"
    req = urllib.request.Request(url, headers={
        "Cookie": f'espn_s2={_get("ESPN_S2")}; SWID={_get("ESPN_SWID")}',
        "User-Agent": "Mozilla/5.0 (players-league-bot)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ESPN HTTP {e.code} {e.reason} — creds expired? ({url})")


# ---------------------------------------------------------------- Anthropic

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")


def claude(system, user, max_tokens=1024):
    headers = {
        "x-api-key": _get("ANTHROPIC_API_KEY"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if ws:
        headers["anthropic-workspace-id"] = ws
    body = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(ANTHROPIC_URL, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Anthropic HTTP {e.code}: {e.read().decode()[:400]}")
    return "".join(b.get("text", "") for b in data.get("content", [])).strip()


POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
SLOT = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "D/ST", 17: "K", 20: "BE", 21: "IR", 23: "FLEX"}
PRO = {0:"FA",1:"ATL",2:"BUF",3:"CHI",4:"CIN",5:"CLE",6:"DAL",7:"DEN",8:"DET",9:"GB",10:"TEN",
       11:"IND",12:"KC",13:"LV",14:"LAR",15:"MIA",16:"MIN",17:"NE",18:"NO",19:"NYG",20:"NYJ",
       21:"PHI",22:"ARI",23:"PIT",24:"LAC",25:"SF",26:"SEA",27:"TB",28:"WSH",29:"CAR",30:"JAX",
       33:"BAL",34:"HOU"}
