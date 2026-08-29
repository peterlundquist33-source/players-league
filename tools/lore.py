"""Static league voice — rivalries, records, running jokes.
Fed into every prompt so the AI writes like it's been in the league since 2022.
Sourced from js/teams-data.js, awards.html, history.html, analytics.html."""

# ESPN team-name / owner -> canonical owner first name used in copy
OWNERS = {
    "Adam Stockwell": "Adam", "CJ Woda": "CJ", "Christian Massett": "Christian",
    "Grant Sawyer": "Grant", "Isaac Douglas": "Isaac", "John Lundquist": "John",
    "Kaleb Feahn": "Kaleb", "Leif Engen": "Leif", "Logan Rezac": "Logan",
    "Mitchell Max": "Mitchell", "Noah Thesing": "Noah", "Peter Lundquist": "Peter",
}

LEAGUE_FACTS = """\
The Players League — 12-team ESPN redraft, founded 2022, now in its 5th season (2026).
Draft happens live every August at a lake cabin weekend ("Players Weekend").

Champions: 2022 Peter Lundquist (13-1, league-record 1,936.1 PF) · 2023 Kaleb Feahn
(worst-to-first, 5 seed) · 2024 Noah Thesing (7 seed Cinderella) · 2025 Adam Stockwell
(#1 seed, finally broke the seed curse). Four seasons, four different champions, zero repeats.

Running themes:
- The #1 Seed Curse: Logan Rezac took the top seed in 2023 AND 2024 and won zero playoff games
  both years. Adam broke it in 2025.
- Last place wears a dress for the golf round at Players Weekend. Logan got it for 2025 (4-10).
- The Lundquist brothers: John leads Peter 6-3 all-time head-to-head. Big-brother bragging rights.
- Adam is Mr. Consistent — best career record (34-22), never a losing season, most playoff wins.
- Noah is the postseason assassin — unremarkable regular seasons, 5 career playoff wins.
- Peter's fall: 13-1 champ in 2022, then 4-10 in 2023, the sharpest title-defense collapse ever.
- All-time single-week record: Adam Stockwell 205.6, Week 10 2023.
- Career PF leader: Peter Lundquist (7,046.6). Career wins leader: Adam Stockwell (34).
"""

# owner -> one-line current-form / personality note for previews & recaps
NOTES = {
    "Adam": "Gold standard. Reigning champ, 34-22 career, no losing seasons ever. Quietly relentless.",
    "John": "R.I.C.O. Slow starter turned perennial threat (10-4 in 2025), still hunting his first ring. Owns Peter 6-3.",
    "Peter": "The Basement Of KK. 2022 champ (13-1), hasn't recaptured it since. Younger Lundquist brother.",
    "Noah": "Wan'Dales of London. Nobody wants him in round one — 5 playoff wins, 2024 title from the 7 seed.",
    "Kaleb": "PA Dive Your Way. The original Cinderella (2023 champ). Three straight 8-6 seasons since.",
    "Christian": "The Aura Farm. Boom-or-bust incarnate — 10-4 then 4-10, always in the mix, never last man standing.",
    "Logan": "The face of the #1 Seed Curse. Back-to-back top seeds, zero playoff wins. Wore the dress for 2025.",
    "Mitchell": "Mr. .500 — three 7-7 seasons in four years, but somehow 2 playoff wins. The human coin flip.",
    "Isaac": "A Slap in the Face. Started 11-3 in 2022, has been chasing that high ever since.",
    "CJ": "Elite Defense. One winning season in four (8-6, 2024). Mostly stuck below the line.",
    "Grant": "Lord Save Me. Pure variance — 3-11 then 9-5 then 5-9. Capable of anything, predictable in nothing.",
    "Leif": "Joey Lunchbox. Loyal to the bit for four years, 22-34 career, the lovable basement dweller.",
}

RIVALRIES = [
    ("John", "Peter", "the Lundquist brothers — John leads 6-3 all-time"),
    ("CJ", "Leif", "dead even 4-4, every meeting is personal"),
    ("Grant", "Logan", "Grant leads 5-4, the league's chaos derby"),
    ("Isaac", "Christian", "Christian leads 6-4"),
    ("Adam", "Isaac", "Isaac has Adam's number, 5-3"),
]


_OWNERS_CI = {k.lower(): v for k, v in OWNERS.items()}
_LAST_CI = {k.split()[-1].lower(): v for k, v in OWNERS.items()}


def owner(name):
    """ESPN member name (any casing) -> canonical first name used in copy."""
    if not name:
        return "?"
    n = name.strip().lower()
    if n in _OWNERS_CI:
        return _OWNERS_CI[n]
    parts = n.split()
    if parts and parts[-1] in _LAST_CI:      # match on last name
        return _LAST_CI[parts[-1]]
    return name.split()[0].capitalize()


def rivalry_between(a, b):
    for x, y, desc in RIVALRIES:
        if {x, y} == {owner(a), owner(b)}:
            return desc
    return None
