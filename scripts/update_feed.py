#!/usr/bin/env python3
"""
Fully automated feed updater — this is what makes the repo "post stuff on its own".

Runs on a schedule (see .github/workflows/auto-update.yml), with no human input:

1. Fetches recent "Show HN" posts from the Hacker News Algolia API (free, no key
   needed) — this is where people share projects they built and the community
   votes on the ones they actually like.
2. Filters for posts that link to a real GitHub repo and have decent traction
   (points/comments above a threshold).
3. Skips anything already posted before (tracked in data/seen.json).
4. Rewrites the "Latest picks (auto-updated)" block in README.md with the
   newest finds, keeping a rolling window so the README doesn't grow forever.

This script has no interactive input and is safe to run unattended in CI.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README_PATH = ROOT / "README.md"
SEEN_PATH = ROOT / "data" / "seen.json"

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
GITHUB_REPO_RE = re.compile(r"https?://github\.com/([\w.-]+)/([\w.-]+?)/?(?:[#?].*)?$", re.IGNORECASE)

LOOKBACK_DAYS = 3
MIN_POINTS = 15
MAX_NEW_ITEMS_PER_RUN = 6
MAX_ITEMS_IN_README = 25
MAX_SEEN_IDS_STORED = 2000

AUTO_FEED_START = "<!-- AUTO-FEED:START -->"
AUTO_FEED_END = "<!-- AUTO-FEED:END -->"


def fetch_show_hn_candidates() -> list[dict]:
    since = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp())
    params = {
        "tags": "show_hn",
        "numericFilters": f"created_at_i>{since},points>={MIN_POINTS}",
        "hitsPerPage": "50",
    }
    url = f"{HN_SEARCH_URL}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"Warning: could not reach Hacker News API: {error}", file=sys.stderr)
        return []

    return payload.get("hits", [])


def extract_github_repo(url: str | None) -> tuple[str, str] | None:
    if not url:
        return None
    match = GITHUB_REPO_RE.match(url.strip())
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    if owner.lower() in {"topics", "sponsors", "marketplace", "orgs"}:
        return None
    return owner, repo


def load_seen() -> set[str]:
    if not SEEN_PATH.exists():
        return set()
    try:
        return set(json.loads(SEEN_PATH.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return set()


def save_seen(seen: set[str]) -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    trimmed = sorted(seen)[-MAX_SEEN_IDS_STORED:]
    SEEN_PATH.write_text(json.dumps(trimmed, indent=2) + "\n", encoding="utf-8")


def build_new_entries(hits: list[dict], seen: set[str]) -> list[str]:
    entries: list[str] = []
    hits_sorted = sorted(hits, key=lambda hit: hit.get("points", 0), reverse=True)

    for hit in hits_sorted:
        if len(entries) >= MAX_NEW_ITEMS_PER_RUN:
            break

        object_id = hit.get("objectID")
        if not object_id or object_id in seen:
            continue

        repo_info = extract_github_repo(hit.get("url"))
        if not repo_info:
            continue

        owner, repo = repo_info
        title = (hit.get("title") or f"{owner}/{repo}").strip()
        points = hit.get("points", 0)
        comments = hit.get("num_comments", 0)
        hn_link = f"https://news.ycombinator.com/item?id={object_id}"
        repo_url = f"https://github.com/{owner}/{repo}"
        date_str = datetime.fromtimestamp(hit.get("created_at_i", 0), tz=timezone.utc).strftime("%Y-%m-%d")

        entries.append(
            f"- **[{title}]({repo_url})** — {points} points, {comments} comments on "
            f"[Show HN]({hn_link}) ({date_str})"
        )
        seen.add(object_id)

    return entries


def update_readme(new_entries: list[str]) -> bool:
    text = README_PATH.read_text(encoding="utf-8")

    if AUTO_FEED_START not in text or AUTO_FEED_END not in text:
        print("Warning: AUTO-FEED markers not found in README.md, skipping update.", file=sys.stderr)
        return False

    before, rest = text.split(AUTO_FEED_START, 1)
    old_block, after = rest.split(AUTO_FEED_END, 1)

    existing_lines = [line for line in old_block.strip().splitlines() if line.startswith("- **[")]

    combined = new_entries + existing_lines
    combined = combined[:MAX_ITEMS_IN_README]

    if not combined:
        combined = ["_No picks yet — the first automated run will populate this section._"]

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    block_body = "\n".join(combined)
    new_block = f"{AUTO_FEED_START}\n_Last checked: {timestamp}._\n\n{block_body}\n{AUTO_FEED_END}"

    new_text = before + new_block + after

    if new_text == text:
        return False

    README_PATH.write_text(new_text, encoding="utf-8")
    return True


def main() -> None:
    seen = load_seen()
    hits = fetch_show_hn_candidates()
    print(f"Fetched {len(hits)} Show HN candidate(s) from the last {LOOKBACK_DAYS} day(s).")

    new_entries = build_new_entries(hits, seen)
    print(f"Found {len(new_entries)} new GitHub project(s) to add.")

    changed = update_readme(new_entries)
    save_seen(seen)

    if changed:
        print("README.md updated.")
    else:
        print("Nothing new to add — README.md left unchanged.")


if __name__ == "__main__":
    main()
