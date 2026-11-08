#!/usr/bin/env python3
"""Add an emailed MFL newsletter issue to data/newsletters.json.

Since mid-October Vulture sends the weekly Movies Fantasy League newsletter by
email only; it no longer lands under the MFL tag on vulture.com, so
scripts/update.py can't see it. Each email has a "View this email in your
browser" link that serves the issue's HTML without signing in. This script takes
that link, extracts the editorial content, and stores it in the same shape the
page already uses for web-published issues ({"tag", "html"} blocks).

What gets dropped: the subscriber's own "Your Team" box, subscribe prompts, the
Gold Rush promo and the footer. Tracking redirects are decoded to the real
destination and the subscriber id (`ueid`/`uid`) is removed, so nothing that
identifies the recipient ends up in the repo.

The issue date comes from the email's sent date (--date): the browser view stamps
its header with the day it is viewed, not the day it went out.

The "Your Team" box is still read, and printed alongside what data/snapshot.json
says for the same team, as a cross-check that the leaderboard refresh matches.

    python3 scripts/add_newsletter.py URL --date 2026-11-03 --title "Subject line" [--teaser "Preheader"]

Re-running for the same issue date replaces that entry. Standard library only.
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update import DATA, clean_html, fetch  # noqa: E402

BLOCK_RE = re.compile(r"<(h1|p|ul)\b[^>]*>(.*?)</\1>", re.S)
SKIP_SECTIONS = {"Your Team"}
STOP_SECTIONS = {"Gold Rush"}
SKIP_PARAS = re.compile(r"Subscribe now|View the MFL leaderboard here|^(WATCH|SIGN UP)$", re.I)


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def tidy(fragment: str) -> str:
    """clean_html, plus email-specific fixes: no stray/trailing <br>, no empty emphasis."""
    out = clean_html(fragment)
    out = out.replace("&nbsp;", " ")
    out = re.sub(r"<(em|strong)>\s*</\1>", " ", out)
    out = re.sub(r"(\s*<br>\s*)+(</(?:em|strong)>)", r"\2<br>", out)  # <em>Title<br></em> -> <em>Title</em><br>
    out = re.sub(r"^(\s*<br>)+|(<br>\s*)+$", "", out)
    out = re.sub(r"<a href=\"#\">(.*?)</a>", r"\1", out)
    return re.sub(r"\s+", " ", out).strip()


def parse(page: str) -> tuple[list[dict], dict | None]:
    blocks, team = [], None
    started, section = False, None
    for tag, inner in BLOCK_RE.findall(page):
        text = text_of(inner)
        if not text:
            continue
        if not started:
            if text.startswith("Vulture Daily Games"):
                started = True
            continue
        if tag == "h1":
            section = text
            if section in STOP_SECTIONS:
                break
            if section in SKIP_SECTIONS:
                continue
            blocks.append({"tag": "h2", "html": re.sub(r"</?strong>", "", tidy(inner)).strip()})
            continue
        if section in SKIP_SECTIONS:
            if team is None and "Display Name:" in text:
                team = your_team(text)
            continue
        if SKIP_PARAS.search(text):
            continue
        if tag == "ul":
            items = [tidy(li) for li in re.findall(r"<li\b[^>]*>(.*?)</li>", inner, re.S)]
            html = "".join(f"<li>{i}</li>" for i in items if i)
        else:
            html = tidy(inner)
        if html:
            blocks.append({"tag": tag, "html": html})
    return blocks, team


def your_team(text: str) -> dict:
    name = re.search(r"Display Name:\s*(.*?)\s*Current Score:", text)
    score = re.search(r"Current Score:\s*([\d,]+)", text)
    rank = re.search(r"Current Rank:\s*([\d,]+)", text)
    movies = re.findall(r"•\s*(.*?):\s*(\d+) points", text)
    return {
        "team": name.group(1) if name else None,
        "score": int(score.group(1).replace(",", "")) if score else None,
        "rank": int(rank.group(1).replace(",", "")) if rank else None,
        "movies": {m: int(p) for m, p in movies},
    }


def cross_check(team: dict | None, issue_date: str) -> None:
    """Compare the email's "Your Team" numbers with the latest snapshot, when they
    describe the same week (older issues naturally differ)."""
    if not team or not team["team"]:
        print("cross-check: no Your Team box found")
        return
    snap = json.loads((DATA / "snapshot.json").read_text())
    try:
        lb = datetime.strptime(snap.get("leaderboardUpdated") or "", "%B %d, %Y").date()
        gap = abs((lb - datetime.fromisoformat(issue_date).date()).days)
    except ValueError:
        gap = 0
    if gap > 3:
        print(f"cross-check: skipped, issue {issue_date} is a different week from the "
              f"{snap.get('leaderboardUpdated')} leaderboard")
        return
    row = snap["members"].get(team["team"])
    if not row:
        print(f"cross-check: {team['team']} not in snapshot")
        return
    ours = {r["title"]: r["points"] for r in row["roster"]}
    diffs = [f"{m}: email {p} vs site {ours.get(m)}" for m, p in team["movies"].items() if ours.get(m) != p]
    same = row["score"] == team["score"] and not diffs
    print(f"cross-check ({snap.get('leaderboardUpdated')} snapshot): {team['team']} "
          f"email {team['score']} / rank {team['rank']}, site {row['score']} / rank {row['rank']} "
          f"-> {'MATCH' if same else 'DIFFERS'}")
    for d in diffs:
        print("  " + d)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url", help='the email\'s "View this email in your browser" link')
    ap.add_argument("--date", required=True, help="the email's sent date, YYYY-MM-DD")
    ap.add_argument("--title", required=True, help="email subject (the 'Movies Fantasy League:' prefix is dropped)")
    ap.add_argument("--teaser", default="", help="email preheader, optional")
    ap.add_argument("--dry-run", action="store_true", help="print the parsed issue instead of saving it")
    args = ap.parse_args()

    page = fetch(args.url).decode("utf-8", "replace")
    issue_date = datetime.strptime(args.date, "%Y-%m-%d").date().isoformat()
    blocks, team = parse(page)
    if len(blocks) < 3:
        sys.exit(f"could not parse the issue ({len(blocks)} blocks); has the email template changed?")

    title = re.sub(r"^Movies Fantasy League:\s*", "", args.title).strip()
    entry = {
        "published": issue_date,
        "date": datetime.fromisoformat(issue_date).strftime("%b. %-d, %Y").replace("May.", "May"),
        "title": htmllib.escape(title, quote=False),
        "teaser": htmllib.escape(args.teaser.strip(), quote=False),
        "source": "email",
        "body": blocks,
    }
    if args.dry_run:
        print(json.dumps(entry, indent=1, ensure_ascii=False))
    else:
        path = DATA / "newsletters.json"
        issues = json.loads(path.read_text()) if path.exists() else []
        issues = [i for i in issues if i["published"] != issue_date] + [entry]
        issues.sort(key=lambda i: i["published"], reverse=True)
        path.write_text(json.dumps(issues, indent=1, ensure_ascii=False) + "\n")
        print(f"saved {issue_date}: {title} ({len(blocks)} blocks); {len(issues)} issues in newsletters.json")
    cross_check(team, issue_date)


if __name__ == "__main__":
    main()
