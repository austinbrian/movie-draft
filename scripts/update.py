#!/usr/bin/env python3
"""Refresh data/snapshot.json and data/history.json from Vulture's official leaderboard.

Vulture publishes the whole Movies Fantasy League leaderboard as one JSON file
(every team: display name, mini-league, score, roster). The file's URL carries an
id that changes between publishes, so we scrape the MFL hub page for the current
one, download it, and derive two things:

  1. the rows for our members (matched by exact team name) plus everyone in the
     official "dc movie club" mini-league, which we share with another group;
  2. per-movie point totals, inferred by solving the linear system
     "sum of a team's eight movies = team score" across all ~30k teams.
     Scoring is additive by movie, so this recovers the official per-movie
     points without scraping Box Office Mojo or awards results.

Standard library only, so it runs anywhere (GitHub Actions included).
"""

import gzip
import io
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HUB_URL = "https://www.vulture.com/movies-league/"
LEADERBOARD_RE = re.compile(r"https://www\.vulture\.com/static/leaderboard/production/[A-Za-z0-9]+\.json")
UPDATED_RE = re.compile(r"Leaderboard\s*</h2>\s*<p[^>]*>\s*Updated\s+([A-Za-z]+\.? \d{1,2}, \d{4})", re.S)
UA = "movie-draft-tracker (github.com/austinbrian/movie-draft)"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
            body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
        return body


def find_leaderboard(hub_html: str) -> tuple[str, str | None]:
    m = LEADERBOARD_RE.search(hub_html)
    if not m:
        sys.exit("could not find a leaderboard JSON URL on the hub page")
    updated = None
    u = re.search(r"Updated\s+([A-Z][a-z]+\.? \d{1,2}, \d{4})", hub_html)
    if u:
        updated = u.group(1)
    return m.group(0), updated


TAG_URL = "https://www.vulture.com/tags/movies-fantasy-league/"
KEEP_TAGS = re.compile(r"</?(em|strong|i|b)>|<br\s*/?>|<a [^>]*href=\"[^\"]+\"[^>]*>|</a>")
BODY_BLOCK_RE = re.compile(
    r'<(p|h2)\s+class="(clay-paragraph|clay-subheader_fancy[^"]*|list-item-text)"[^>]*>(.*?)</\1>', re.S)


def clean_html(fragment: str) -> str:
    """Keep only emphasis and links from a Vulture paragraph; drop everything else."""
    out, pos = [], 0
    for m in re.finditer(r"<[^>]+>", fragment):
        out.append(fragment[pos:m.start()])
        tag = m.group(0)
        if KEEP_TAGS.fullmatch(tag):
            if tag.startswith("<a "):
                href = re.search(r'href="([^"]+)"', tag).group(1)
                tag = f'<a href="{href}">'
            elif tag.startswith("<br"):
                tag = "<br>"
            out.append(tag)
        pos = m.end()
    out.append(fragment[pos:])
    return re.sub(r"\s+", " ", "".join(out)).strip()


def hub_recap(hub_html: str) -> list[str]:
    """The weekly write-up at the top of the hub page: the paragraphs between the
    in-page nav and the 'Draft Your Team' button, which Vulture replaces each week."""
    start = hub_html.find('<li><a href="#faq">')
    end = hub_html.find('data-vars-anchor-text="Draft Your Team"', start)
    if start < 0 or end < 0:
        return []
    paras = re.findall(r'<p class="clay-paragraph"[^>]*>(.*?)</p>', hub_html[start:end], re.S)
    return [p for p in (clean_html(p) for p in paras) if p]


def article_body(url: str) -> list[dict]:
    """The paragraphs and subheads of a Vulture article, in order, as
    [{"tag": "p"|"h2", "html": ...}] with the markup reduced like the recap."""
    html = fetch(url).decode("utf-8", "replace")
    start = html.find('class="article-content')
    if start < 0:
        return []
    end = html.find("<aside", start)
    blocks = []
    for tag, _cls, inner in BODY_BLOCK_RE.findall(html[start:end if end > 0 else None]):
        # "Hanging" subheads carry a decorative bullet element; drop it.
        inner = re.sub(r'<span class="unordered-list-item">.*?</span>', "", inner, flags=re.S)
        text = clean_html(inner).replace("\ufeff", "")
        if text:
            blocks.append({"tag": tag, "html": text})
    return blocks


def recent_articles(limit: int = 8, cached: dict[str, list] | None = None) -> list[dict]:
    """Latest MFL-tagged articles, which is where the weekly newsletter gets
    republished. Newsletter issues also get their full text, so the page can show
    it inline; bodies already in the last snapshot are reused rather than refetched."""
    html = fetch(TAG_URL).decode("utf-8", "replace")
    cached = cached or {}
    items = []
    for block in re.findall(r'<li\s+class="article "(.*?)</li>', html, re.S):
        link = re.search(r'<a href="(https://www\.vulture\.com/article/[^"]+)" class="link-text"><span class="headline">(.*?)</span></a>', block, re.S)
        if not link:
            continue
        when = re.search(r'<time class="paginate-time">([^<]+)</time>', block)
        # Same-day articles show a clock time ("5:00 p.m.") rather than a date.
        if when and not re.search(r"\d{4}", when.group(1)):
            when = None
            label = date.today().strftime("%b. %-d, %Y")
        else:
            label = when.group(1).strip() if when else None
        teaser = re.search(r'<span class="teaser">(.*?)</span>', block, re.S)
        url = link.group(1)
        item = {
            "url": url,
            "title": clean_html(link.group(2)),
            "date": label,
            "teaser": clean_html(teaser.group(1)) if teaser else "",
            "newsletter": "newsletter" in url,
        }
        if item["newsletter"]:
            try:
                item["body"] = cached.get(url) or article_body(url)
            except Exception as exc:
                print(f"warning: could not fetch {url}: {exc}", file=sys.stderr)
                item["body"] = cached.get(url, [])
        items.append(item)
        if len(items) >= limit:
            break
    return items


def comma_titles(rows: list[dict]) -> set[str]:
    """Titles that contain commas, learned from the rows where Vulture quoted them."""
    found = set()
    for row in rows:
        found.update(m.strip('"') for m in re.findall(r'"[^"]+"', row.get("movies", "")))
    return found


def split_movies(s: str, known: set[str]) -> list[str]:
    """Rosters are comma-joined. Titles containing commas are usually double-quoted,
    but not always, so fragments are re-joined when they form a known title."""
    parts = [m.strip().strip('"') for m in re.findall(r'"[^"]+"|[^,]+', s) if m.strip()]
    out = []
    i = 0
    while i < len(parts):
        merged = None
        for j in range(min(len(parts), i + 4), i + 1, -1):
            cand = ", ".join(parts[i:j])
            if cand in known:
                merged, i = cand, j
                break
        if merged is None:
            merged = parts[i]
            i += 1
        out.append(merged)
    return out


def solve_movie_points(teams: list[dict]) -> tuple[dict[str, float], int]:
    """Least-squares fit of per-movie points to team scores.

    Builds the normal equations (A^T A) x = A^T b directly from the rosters and
    solves them with Gaussian elimination. A tiny ridge keeps movies that are
    never separable (always drafted together) from blowing up; they get the
    shared value split between them, which the residual check will flag.
    Returns the fitted values and the number of teams whose roster sum, after
    rounding, does not reproduce the official score.
    """
    movies = sorted({m for t in teams for m in t["roster"]})
    idx = {m: i for i, m in enumerate(movies)}
    n = len(movies)
    ata = [[0.0] * n for _ in range(n)]
    atb = [0.0] * n
    for t in teams:
        ids = [idx[m] for m in t["roster"]]
        for i in ids:
            atb[i] += t["score"]
            row = ata[i]
            for j in ids:
                row[j] += 1.0
    for i in range(n):
        ata[i][i] += 1e-6

    # Gaussian elimination with partial pivoting.
    aug = [ata[i] + [atb[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-12:
            continue
        aug[col], aug[piv] = aug[piv], aug[col]
        prow = aug[col]
        pv = prow[col]
        for r in range(n):
            if r == col:
                continue
            f = aug[r][col] / pv
            if f == 0.0:
                continue
            row = aug[r]
            for c in range(col, n + 1):
                row[c] -= f * prow[c]
    x = {movies[i]: (aug[i][n] / aug[i][i] if abs(aug[i][i]) > 1e-12 else 0.0) for i in range(n)}

    mismatches = 0
    for t in teams:
        if round(sum(x[m] for m in t["roster"])) != t["score"]:
            mismatches += 1
    return x, mismatches


def main() -> None:
    league = json.loads((DATA / "league.json").read_text())
    member_names = {m["team"] for m in league["members"]}
    shared_league = league["officialLeague"].lower()

    hub_html = fetch(HUB_URL).decode("utf-8", "replace")
    lb_url, updated_label = find_leaderboard(hub_html)
    raw = json.loads(fetch(lb_url))
    recap = hub_recap(hub_html)
    snap_path = DATA / "snapshot.json"
    previous = json.loads(snap_path.read_text()) if snap_path.exists() else {}
    cached_bodies = {a["url"]: a["body"] for a in previous.get("articles", []) if a.get("body")}
    try:
        articles = recent_articles(cached=cached_bodies)
    except Exception as exc:  # the news list is a nicety; never block the leaderboard on it
        print(f"warning: could not fetch articles: {exc}", file=sys.stderr)
        articles = []

    known = comma_titles(raw)
    teams = []
    for row in raw:
        if "displayName" not in row or "movies" not in row:
            continue  # a handful of blank registrations sit at the bottom
        teams.append({
            "team": row["displayName"],
            "league": row.get("leagueName") or "",
            "score": int(row["score"]),
            "rank": int(row["ranking"]) if row.get("ranking") is not None else None,
            "roster": split_movies(row["movies"], known),
        })
    total_teams = len(teams)

    points, mismatches = solve_movie_points(teams)
    movie_points = {m: round(v) for m, v in points.items()}

    def pick(t: dict) -> dict:
        return {
            "team": t["team"],
            "league": t["league"],
            "score": t["score"],
            "rank": t["rank"],
            "roster": [{"title": m, "points": movie_points.get(m, 0)} for m in t["roster"]],
        }

    members = {t["team"]: pick(t) for t in teams if t["team"] in member_names}
    missing = sorted(member_names - members.keys())
    if missing:
        print(f"warning: no leaderboard row for {missing}", file=sys.stderr)
    official = sorted(
        (pick(t) for t in teams if t["league"].lower() == shared_league),
        key=lambda t: (-t["score"], t["team"].lower()),
    )

    # Popularity: how many teams drafted each movie, for the movie table.
    drafted = {}
    for t in teams:
        for m in t["roster"]:
            drafted[m] = drafted.get(m, 0) + 1

    today = date.today().isoformat()
    snapshot = {
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "leaderboardUpdated": updated_label,
        "leaderboardUrl": lb_url,
        "totalTeams": total_teams,
        "topScore": max(t["score"] for t in teams),
        "fitMismatches": mismatches,
        "recap": recap,
        "articles": articles,
        "members": members,
        "officialLeague": official,
        "movies": {
            m: {"points": movie_points[m], "drafted": drafted.get(m, 0)}
            for m in sorted(movie_points)
        },
    }
    snap_path.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n")

    # History: one entry per leaderboard publish (keyed on the label when we
    # have it, else the fetch date), replacing any earlier entry for the same key.
    hist_path = DATA / "history.json"
    history = json.loads(hist_path.read_text()) if hist_path.exists() else []
    key = updated_label or today
    history = [h for h in history if h["key"] != key]
    history.append({
        "key": key,
        "date": today,
        "teams": {name: {"score": t["score"], "rank": t["rank"]} for name, t in members.items()},
        "movies": {m: p for m, p in movie_points.items() if p},
    })
    hist_path.write_text(json.dumps(history, indent=1, ensure_ascii=False) + "\n")

    print(f"{total_teams} teams, leaderboard {updated_label or 'date unknown'}, "
          f"{len(movie_points)} movies fitted, {mismatches} teams off by rounding")
    for name, t in sorted(members.items(), key=lambda kv: -kv[1]["score"]):
        print(f"  {t['score']:4d}  #{t['rank']:<6} {name}")


if __name__ == "__main__":
    main()
