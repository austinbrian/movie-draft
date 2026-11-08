# DC Movie Club

Standings page for our teams in Vulture's Movies Fantasy League (Season 6, 2026–27),
served from GitHub Pages at <https://austinbrian.github.io/movie-draft/>.

Vulture publishes the full leaderboard — every team's name, mini-league, score and
roster — as a single JSON file embedded on the [MFL hub page](https://www.vulture.com/movies-league/).
We mirror it, pick out our four teams, and work out how many points each movie is
worth by solving the system "sum of a team's eight movies = team score" across all
~30k teams. Scoring is additive by movie, so the fit is exact; `fitMismatches` in
`snapshot.json` says how many teams it failed to reproduce (it should be 0).

Our mini-league name, `dc movie club`, was also used by an unrelated group, so membership
is by team name in `data/league.json`, not by Vulture's league filter. The official
mini-league is still shown for context, with the other group tagged.

## Files

| File | Purpose |
|------|---------|
| `index.html`, `app.js`, `styles.css` | The page. Vanilla JS, no build step. |
| `data/league.json` | Who we are: name → exact Vulture team name. Edit to add people. |
| `data/snapshot.json` | Generated. Latest leaderboard rows for us and the official league, plus per-movie points. |
| `data/history.json` | Generated. One entry per leaderboard publish: team scores/ranks and movie points. Feeds the week-by-week chart. |
| `data/backfill.json` | Weeks from before the tracker existed, as the per-movie points Vulture reported; `scripts/backfill.py` turns them into history entries from the rosters. |
| `data/newsletters.json` | Newsletter issues that went out by email only (since mid-October). Added with `scripts/add_newsletter.py`; the page merges them with any republished on vulture.com. |
| `data/prices.json` | Draft price and box-office eligibility per movie, from the [draft guide](https://www.vulture.com/article/movies-fantasy-league-draft-guide.html). |
| `data/rules.json` | Scoring tables and awards calendar, transcribed from the hub page. |
| `scripts/update.py` | Fetches the leaderboard and regenerates `snapshot.json` and `history.json`. Standard library only (Python 3.9+). |
| `scripts/add_newsletter.py` | Imports one emailed issue from its "View this email in your browser" link. It resolves tracking links, drops the subscriber's own team box and footer, and cross-checks that team's score against `snapshot.json`. |
| `.github/workflows/update.yml` | Runs the script Tuesdays/Wednesdays and commits changes. |

## Running locally

```bash
python3 scripts/update.py        # refresh data/
python3 -m http.server 8000      # then open http://localhost:8000
```

## Weekly newsletter

The Action can't read email, so emailed issues are added by hand or by the
`movie-draft-weekly` Claude skill (in `~/dev/claude-skills/`), which runs Wednesdays
through the Oscars:

```bash
python3 scripts/add_newsletter.py '<view-in-browser URL>' --date 2026-11-03 \
    --title '<email subject>' --teaser '<preheader>'
```

When Vulture publishes per-movie points for a week the tracker missed, add that week
to `data/backfill.json` and run `scripts/backfill.py`.

## Adding a person

Add `{ "name": "...", "team": "<exact display name on Vulture>" }` to `members` in
`data/league.json` and rerun the script. Team names are matched exactly, including
case; search the hub leaderboard to get it right.

## Later

- Link to / fold in the Oscar predictions page for the 2027 ceremony.
- Per-movie event log (which award or box-office milestone added the points) — the
  week-over-week diff in `history.json` plus the awards calendar makes most of these
  inferable.
