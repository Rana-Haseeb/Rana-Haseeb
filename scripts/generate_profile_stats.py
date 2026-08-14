#!/usr/bin/env python3
"""Generate the profile's GitHub Analytics cards as static SVGs.

Replaces the third-party card services (github-readme-stats.vercel.app and
github-readme-streak-stats) that the README used to embed. Those are shared
public deployments; when they pause or hit GitHub's API limits the profile
silently shows broken images. Everything here is rendered inside Actions with
the automatic GITHUB_TOKEN and committed to the repo, so the cards can only
break if this repo breaks.

Env:
    GITHUB_TOKEN  automatic token provided by Actions
    USERNAME      profile to render (defaults to the repo owner)
    OUT_DIR       where the SVGs land (default: assets)
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.github.com/graphql"

# Matches the README's palette.
BG = "#0d1117"
BORDER = "#21262d"
TITLE = "#a55eea"
TEXT = "#c9d1d9"
ACCENT = "#22d3ee"
MUTED = "#8b949e"

FONT = (
    "-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"
)


def gql(query, variables):
    """Run one GraphQL request, raising with a useful message on failure."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")

    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats-generator",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        sys.exit(f"GitHub API returned HTTP {exc.code}: {exc.read()[:400]!r}")

    if "errors" in payload:
        sys.exit(f"GraphQL errors: {json.dumps(payload['errors'])[:400]}")
    return payload["data"]


PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    createdAt
    followers { totalCount }
    repositories(
      first: 100
      ownerAffiliations: OWNER
      isFork: false
      orderBy: {field: STARGAZERS, direction: DESC}
    ) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

# contributionsCollection accepts at most a one-year window, so each year of
# the account's life is fetched separately and merged.
YEAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch(login):
    profile = gql(PROFILE_QUERY, {"login": login})["user"]
    if profile is None:
        sys.exit(f"no such user: {login}")

    created = datetime.fromisoformat(profile["createdAt"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)

    totals = {"commits": 0, "prs": 0, "issues": 0, "reviews": 0}
    days = {}

    start = created
    while start < now:
        end = min(start + timedelta(days=365), now)
        block = gql(
            YEAR_QUERY,
            {
                "login": login,
                "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )["user"]["contributionsCollection"]

        totals["commits"] += block["totalCommitContributions"]
        totals["prs"] += block["totalPullRequestContributions"]
        totals["issues"] += block["totalIssueContributions"]
        totals["reviews"] += block["totalPullRequestReviewContributions"]

        for week in block["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                # Overlapping windows can repeat a day; assignment dedupes.
                days[day["date"]] = day["contributionCount"]

        start = end

    return profile, totals, days


def streaks(days):
    """Summarise a date->count map.

    Returns (total, current, longest, current_start, current_end) where the
    two dates bound the running streak and are "" when there is none.

    Today is skipped when empty so the streak does not visibly reset at
    midnight UTC before the day's work has happened.
    """
    if not days:
        return 0, 0, 0, "", ""

    ordered = sorted(days.items())
    total = sum(count for _, count in ordered)

    longest = run = 0
    for _, count in ordered:
        run = run + 1 if count > 0 else 0
        longest = max(longest, run)

    today = datetime.now(timezone.utc).date().isoformat()
    current = 0
    start = end = ""
    for date, count in reversed(ordered):
        if count > 0:
            current += 1
            start = date
            end = end or date
        elif date == today:
            continue
        else:
            break

    return total, current, longest, start, end


def top_languages(repos, limit=6):
    sizes = {}
    colors = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            sizes[name] = sizes.get(name, 0) + edge["size"]
            colors[name] = edge["node"]["color"] or MUTED

    ranked = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    total = sum(size for _, size in ranked) or 1
    return [(name, size / total * 100, colors[name]) for name, size in ranked]


def human(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m".replace(".0m", "m")
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def frame(width, height, title, body):
    """Shared card chrome: rounded panel, border, title, fade-in."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" \
viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
  <title>{esc(title)}</title>
  <style>
    .t {{ font: 600 16px {FONT}; fill: {TITLE}; }}
    .k {{ font: 400 13px {FONT}; fill: {TEXT}; }}
    .v {{ font: 700 13px {FONT}; fill: {ACCENT}; }}
    .s {{ font: 400 11px {FONT}; fill: {MUTED}; }}
    .n {{ font: 700 26px {FONT}; fill: {TEXT}; }}
    .c {{ opacity: 0; animation: f .5s ease-out forwards; }}
    @keyframes f {{ to {{ opacity: 1; }} }}
    @media (prefers-reduced-motion: reduce) {{
      .c {{ animation: none; opacity: 1; }}
    }}
  </style>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="6"
        fill="{BG}" stroke="{BORDER}"/>
  <text x="25" y="35" class="t">{esc(title)}</text>
{body}
</svg>
"""


def render_stats(name, stars, totals, repo_count, followers):
    rows = [
        ("Total Stars Earned", stars),
        ("Total Commits", totals["commits"]),
        ("Total PRs", totals["prs"]),
        ("Total Issues", totals["issues"]),
        ("Public Repositories", repo_count),
        ("Followers", followers),
    ]
    body = []
    for i, (label, value) in enumerate(rows):
        y = 68 + i * 24
        delay = 0.1 + i * 0.08
        body.append(
            f'  <g class="c" style="animation-delay:{delay:.2f}s">'
            f'<circle cx="30" cy="{y - 4}" r="3" fill="{ACCENT}"/>'
            f'<text x="45" y="{y}" class="k">{esc(label)}</text>'
            f'<text x="425" y="{y}" class="v" text-anchor="end">'
            f"{human(value)}</text></g>"
        )
    return frame(450, 215, f"{name}'s GitHub Stats", "\n".join(body))


def render_langs(langs):
    if not langs:
        return frame(340, 215, "Most Used Languages",
                     f'  <text x="25" y="70" class="s">No language data</text>')

    bar, x = [], 25.0
    width = 290.0
    for name, pct, color in langs:
        seg = width * pct / 100
        bar.append(
            f'<rect x="{x:.1f}" y="55" width="{max(seg, 0.5):.1f}" height="9" '
            f'fill="{color}"/>'
        )
        x += seg

    legend = []
    for i, (name, pct, color) in enumerate(langs):
        col, row = i % 2, i // 2
        lx = 25 + col * 155
        ly = 92 + row * 24
        delay = 0.15 + i * 0.08
        legend.append(
            f'  <g class="c" style="animation-delay:{delay:.2f}s">'
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>'
            f'<text x="{lx + 18}" y="{ly}" class="k">{esc(name)}</text>'
            f'<text x="{lx + 138}" y="{ly}" class="s" text-anchor="end">'
            f"{pct:.1f}%</text></g>"
        )

    body = (
        f'  <g class="c" style="animation-delay:.1s">'
        f'<clipPath id="r"><rect x="25" y="55" width="{width}" height="9" rx="4.5"/>'
        f"</clipPath><g clip-path=\"url(#r)\">{''.join(bar)}</g></g>\n"
        + "\n".join(legend)
    )
    return frame(340, 215, "Most Used Languages", body)


def render_streak(total, current, longest, first_day, last_day):
    cols = [
        (78, human(total), "Total Contributions", f"{first_day} - Present"),
        (225, str(current), "Current Streak", last_day),
        (372, str(longest), "Longest Streak", ""),
    ]
    body = []
    for i, (cx, big, label, sub) in enumerate(cols):
        delay = 0.1 + i * 0.12
        ring = (
            f'<circle cx="{cx}" cy="95" r="40" fill="none" '
            f'stroke="{ACCENT}" stroke-width="4"/>'
            if i == 1
            else ""
        )
        body.append(
            f'  <g class="c" style="animation-delay:{delay:.2f}s">{ring}'
            f'<text x="{cx}" y="103" class="n" text-anchor="middle">{big}</text>'
            f'<text x="{cx}" y="150" class="k" text-anchor="middle">{esc(label)}</text>'
            f'<text x="{cx}" y="168" class="s" text-anchor="middle">{esc(sub)}</text>'
            f"</g>"
        )
    for x in (151, 298):
        body.append(
            f'  <line x1="{x}" y1="55" x2="{x}" y2="160" stroke="{BORDER}"/>'
        )
    return frame(450, 215, "Contribution Streak", "\n".join(body))


def main():
    login = os.environ.get("USERNAME") or sys.exit("USERNAME is not set")
    out = os.environ.get("OUT_DIR", "assets")
    os.makedirs(out, exist_ok=True)

    profile, totals, days = fetch(login)
    repos = profile["repositories"]["nodes"]
    stars = sum(r["stargazerCount"] for r in repos)
    total, current, longest, cur_start, cur_end = streaks(days)

    def pretty(iso, fmt="%b %d, %Y"):
        return datetime.fromisoformat(iso).strftime(fmt) if iso else ""

    dates = sorted(days)
    first = pretty(dates[0]) if dates else ""
    if current:
        # A live streak reads as "Jun 25 - Present"; a stale one keeps its
        # real end date rather than implying it is still running.
        today = datetime.now(timezone.utc).date().isoformat()
        tail = "Present" if cur_end >= today else pretty(cur_end, "%b %d")
        last = f"{pretty(cur_start, '%b %d')} - {tail}"
    else:
        last = ""

    cards = {
        "stats.svg": render_stats(
            profile["name"] or login,
            stars,
            totals,
            profile["repositories"]["totalCount"],
            profile["followers"]["totalCount"],
        ),
        "top-langs.svg": render_langs(top_languages(repos)),
        "streak.svg": render_streak(total, current, longest, first, last),
    }

    for filename, svg in cards.items():
        path = os.path.join(out, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        print(f"wrote {path} ({len(svg)} bytes)")

    print(
        f"stars={stars} commits={totals['commits']} prs={totals['prs']} "
        f"issues={totals['issues']} streak={current} longest={longest}"
    )


if __name__ == "__main__":
    main()
