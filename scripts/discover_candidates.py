#!/usr/bin/env python3
"""
Discovery helper (manual-review tool, not run automatically yet).

Searches the GitHub REST API for repositories that are actively maintained
but still have a relatively low star count, as a starting point for finding
new "hidden gem" candidates to review and possibly submit to the list.

This is intentionally a *suggestion* generator, not an auto-publisher: every
result should be reviewed by a human against CONTRIBUTING.md before being
added to README.md.

Usage:
    python scripts/discover_candidates.py --topic developer-tools --max-stars 800
    GITHUB_TOKEN=... python scripts/discover_candidates.py --topic cli --min-stars 50 --max-stars 500

Set the GITHUB_TOKEN environment variable to raise the API rate limit
(60 requests/hour unauthenticated vs. 5000/hour authenticated).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API_URL = "https://api.github.com/search/repositories"


def build_query(topic: str, min_stars: int, max_stars: int, pushed_within_days: int) -> str:
    since = (datetime.now(timezone.utc) - timedelta(days=pushed_within_days)).strftime("%Y-%m-%d")
    parts = [
        f"topic:{topic}",
        f"stars:{min_stars}..{max_stars}",
        f"pushed:>={since}",
        "archived:false",
        "is:public",
    ]
    return " ".join(parts)


def fetch_candidates(query: str, limit: int) -> list[dict]:
    url = f"{API_URL}?q={urllib.parse.quote(query)}&sort=updated&order=desc&per_page={limit}"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        print(f"GitHub API error: {error.code} {error.reason}", file=sys.stderr)
        if error.code == 403:
            print("Hint: you may be rate-limited. Set GITHUB_TOKEN to raise the limit.", file=sys.stderr)
        sys.exit(1)

    return payload.get("items", [])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topic", required=True, help="GitHub topic to search within, e.g. 'cli' or 'developer-tools'")
    parser.add_argument("--min-stars", type=int, default=20, help="Minimum star count (default: 20)")
    parser.add_argument("--max-stars", type=int, default=1000, help="Maximum star count to stay 'hidden' (default: 1000)")
    parser.add_argument("--pushed-within-days", type=int, default=90, help="Only include repos pushed to in the last N days (default: 90)")
    parser.add_argument("--limit", type=int, default=20, help="Number of candidates to fetch (default: 20)")
    args = parser.parse_args()

    query = build_query(args.topic, args.min_stars, args.max_stars, args.pushed_within_days)
    candidates = fetch_candidates(query, args.limit)

    if not candidates:
        print("No candidates found. Try widening the star range or the topic.")
        return

    print(f"Found {len(candidates)} candidate(s) for topic '{args.topic}':\n")
    for repo in candidates:
        print(f"- [{repo['full_name']}]({repo['html_url']}) - {repo.get('description') or 'No description.'}")
        print(f"    stars: {repo['stargazers_count']} | last push: {repo['pushed_at']} | language: {repo.get('language')}")

    print("\nReview each candidate against CONTRIBUTING.md before adding it to README.md.")


if __name__ == "__main__":
    import urllib.parse

    main()
