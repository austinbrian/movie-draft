#!/usr/bin/env python3
"""Add leaderboard weeks we never fetched to data/history.json.

Vulture overwrites its leaderboard JSON in place and nobody archived the early
publishes, so weeks before this tracker existed are reconstructed from
data/backfill.json: for each week, the per-movie points Vulture reported (in
the newsletter or hub recap) are applied to our members' rosters, which have
been fixed since the draft closed. Ranks are unknown for these weeks.

Safe to re-run: it replaces any history entry with the same label and leaves
fetched entries alone.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def main() -> None:
    snapshot = json.loads((DATA / "snapshot.json").read_text())
    rosters = {name: [r["title"] for r in t["roster"]] for name, t in snapshot["members"].items()}
    hist_path = DATA / "history.json"
    history = json.loads(hist_path.read_text()) if hist_path.exists() else []

    for week in json.loads((DATA / "backfill.json").read_text()):
        key = week["label"]
        points = week["movies"]
        entry = {
            "key": key,
            "date": week["published"],
            "published": week["published"],
            "source": week.get("source", "backfilled"),
            "teams": {
                name: {"score": sum(points.get(m, 0) for m in roster), "rank": None}
                for name, roster in rosters.items()
            },
            "movies": {m: p for m, p in points.items() if p},
        }
        history = [h for h in history if h["key"] != key]
        history.append(entry)
        print(f"{key}: " + ", ".join(f"{n} {t['score']}" for n, t in entry["teams"].items()))

    history.sort(key=lambda h: h.get("published") or h["date"])
    hist_path.write_text(json.dumps(history, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
