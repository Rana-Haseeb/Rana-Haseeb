#!/usr/bin/env python3
"""Generate every rendered asset the profile README embeds.

The README used to hotlink a handful of free single-maintainer deployments
(github-readme-stats, github-readme-streak-stats, the activity graph,
capsule-render, the quote widget). When one of those pauses, the profile
shows broken images and nothing in the README can fix it - which is exactly
what happened. Everything here is rendered inside Actions with the automatic
GITHUB_TOKEN and committed, so these assets can only break if this repo does.

Each card is emitted twice, dark and light, and the README picks between them
with <picture> + prefers-color-scheme. Page chrome (banner, footer, divider)
sits on a transparent ground, so one copy serves both themes.

Env:
    GITHUB_TOKEN  automatic token provided by Actions
    USERNAME      profile to render
    OUT_DIR       where the SVGs land (default: assets)
    README_PATH   README to inject the projects table into (default: README.md)
"""

import json
import os
import random
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.github.com/graphql"

FONT = "-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"

# Brand ramp, shared by the chrome in both themes.
BRAND = ("#6c5ce7", "#a55eea", "#22d3ee")

# suffix -> palette. "" is the dark default; cards are emitted for both.
THEMES = {
    "": {
        "bg": "#0d1117",
        "border": "#21262d",
        "title": "#a55eea",
        "text": "#c9d1d9",
        "accent": "#22d3ee",
        "muted": "#8b949e",
    },
    "-light": {
        "bg": "#ffffff",
        "border": "#d0d7de",
        "title": "#6c5ce7",
        "text": "#1f2328",
        # The brand cyan is unreadable on white, so the light theme drops to
        # a darker stop of the same hue.
        "accent": "#0e7490",
        "muted": "#656d76",
    },
}

# Hand-picked showcase, best first. Auto-discovery ranked by recency alone,
# which buried the strongest work, so the order is editorial.
#
# kind "demo" links the repo's homepage; "code" links the repo itself, for
# entries with no working deployment to point at.
FEATURED = [
    ("🤖", "AI CSV Analyzer", "AI-Powered-CSV-Cleaner-Summarizer",
     "Upload a CSV, get instant AI insights powered by Gemini", "demo"),
    ("🧠", "Multi-Agent Research Platform", "Multi-Agent-Research-Platform",
     "Six AI agents research, debate, and cite every claim", "demo"),
    ("🗂️", "Productivity Agent", "productivity-agent-2026",
     "LangGraph agent with human approval before every write", "demo"),
    ("🗽", "NYC Congestion Audit", "NYC-Congestion-Audit",
     "PySpark and GeoPandas pipeline auditing 2025 congestion pricing", "demo"),
    ("✨", "Self-Updating Portfolio", "Portfolio",
     "Reads GitHub live and writes up new projects with AI", "demo"),
    ("📋", "TaskFlow", "Ai-Task-Management-System",
     "Real-time glassmorphic Kanban board with threaded comments", "demo"),
    ("💬", "Plume", "plume-realtime-messaging",
     "Real-time 1-on-1 and group chat over Socket.io", "demo"),
    ("🛒", "Next.js Commerce", "nextjs-ecommerce-platform",
     "Full-stack store with Auth.js credentials and a local cart", "demo"),
    ("⚡", "Zap", "link-shortener",
     "Tiny links with AI summary, safety check and QR code", "demo"),
    ("💎", "Finovo", "expense-tracker-mern",
     "Premium expense tracker with live balance and analytics", "demo"),
    ("🎬", "CineSearch", "cine-vault",
     "Cinema-grade movie discovery platform", "demo"),
]

# Phrases for the locally rendered typing effect, replacing the demolab
# service the README used to call.
TYPING_HERO = [
    "AI / ML Enthusiast",
    "Building Intelligent Applications",
    "Machine Learning & Generative AI",
    "C++ & Data Structures Enthusiast",
    "Full-Stack MERN Developer",
    "Turning data into decisions",
]

TYPING_OUTRO = [
    "Thanks for visiting!",
    "Let's build something intelligent together!",
]

QUOTES = [
    ("Simplicity is the soul of efficiency.", "Austin Freeman"),
    ("Make it work, make it right, make it fast.", "Kent Beck"),
    ("Programs must be written for people to read.", "Harold Abelson"),
    ("The best error message is the one that never shows up.", "Thomas Fuchs"),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    ("Code is like humour. When you have to explain it, it is bad.", "Cory House"),
    ("Premature optimization is the root of all evil.", "Donald Knuth"),
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    ("Any fool can write code a computer understands.", "Martin Fowler"),
    ("Deleted code is debugged code.", "Jeff Sickel"),
    ("Testing shows the presence, not the absence of bugs.", "Edsger Dijkstra"),
    ("Controlling complexity is the essence of programming.", "Brian Kernighan"),
]


def gql(query, variables):
    """Run one GraphQL request, exiting with a useful message on failure."""
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
        name
        description
        homepageUrl
        stargazerCount
        pushedAt
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
            colors[name] = edge["node"]["color"] or "#8b949e"

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


def glow_trail(width, height, dur=7):
    """A short bright dash that travels once around the card border."""
    perimeter = 2 * ((width - 1) + (height - 1))
    lit = max(90, perimeter * 0.12)
    return (
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="6" '
        f'fill="none" stroke="url(#trail)" stroke-width="2" '
        f'stroke-dasharray="{lit:.0f} {perimeter - lit:.0f}" '
        f'stroke-linecap="round" opacity="0.9">'
        f'<animate attributeName="stroke-dashoffset" values="{perimeter:.0f};0" '
        f'dur="{dur}s" repeatCount="indefinite"/></rect>'
    )


def frame(th, width, height, title, body):
    """Shared card chrome: rounded panel, border, travelling glow, title."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" \
viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
  <title>{esc(title)}</title>
  <defs>
    <linearGradient id="trail" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{th['title']}"/>
      <stop offset="1" stop-color="{th['accent']}"/>
    </linearGradient>
  </defs>
  <style>
    .t {{ font: 600 16px {FONT}; fill: {th['title']}; }}
    .k {{ font: 400 13px {FONT}; fill: {th['text']}; }}
    .v {{ font: 700 13px {FONT}; fill: {th['accent']}; }}
    .s {{ font: 400 11px {FONT}; fill: {th['muted']}; }}
    .n {{ font: 700 26px {FONT}; fill: {th['text']}; }}
    .c {{ opacity: 0; animation: f .5s ease-out forwards; }}
    @keyframes f {{ to {{ opacity: 1; }} }}
    @media (prefers-reduced-motion: reduce) {{
      .c {{ animation: none; opacity: 1; }}
    }}
  </style>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="6"
        fill="{th['bg']}" stroke="{th['border']}"/>
  {glow_trail(width, height)}
  <text x="25" y="35" class="t">{esc(title)}</text>
{body}
</svg>
"""


def render_stats(th, name, stars, totals, repo_count, followers):
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
            f'<circle cx="30" cy="{y - 4}" r="3" fill="{th["accent"]}"/>'
            f'<text x="45" y="{y}" class="k">{esc(label)}</text>'
            f'<text x="425" y="{y}" class="v" text-anchor="end">'
            f"{human(value)}</text></g>"
        )
    return frame(th, 450, 215, f"{name}'s GitHub Stats", "\n".join(body))


def render_langs(th, langs):
    if not langs:
        return frame(
            th, 340, 215, "Most Used Languages",
            '  <text x="25" y="70" class="s">No language data</text>',
        )

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
    return frame(th, 340, 215, "Most Used Languages", body)


def render_streak(th, total, current, longest, first_day, last_day):
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
            f'stroke="{th["accent"]}" stroke-width="4"/>'
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
            f'  <line x1="{x}" y1="55" x2="{x}" y2="160" stroke="{th["border"]}"/>'
        )
    return frame(th, 450, 215, "Contribution Streak", "\n".join(body))


def render_activity(th, days, window=31):
    """Area chart of daily contributions across the trailing window."""
    today = datetime.now(timezone.utc).date()
    series = [
        (today - timedelta(days=i), days.get((today - timedelta(days=i)).isoformat(), 0))
        for i in range(window - 1, -1, -1)
    ]

    width, height = 880, 260
    left, right, top_pad, bottom = 52, 26, 62, 46
    plot_w = width - left - right
    plot_h = height - top_pad - bottom
    peak = max(count for _, count in series) or 1

    def px(i):
        return left + plot_w * i / (len(series) - 1)

    def py(count):
        return top_pad + plot_h * (1 - count / peak)

    grid = []
    for frac in (0, 0.5, 1):
        gy = top_pad + plot_h * (1 - frac)
        grid.append(
            f'  <line x1="{left}" y1="{gy:.1f}" x2="{width - right}" y2="{gy:.1f}" '
            f'stroke="{th["border"]}"/>'
            f'<text x="{left - 10}" y="{gy + 4:.1f}" class="s" text-anchor="end">'
            f"{round(peak * frac)}</text>"
        )

    points = " ".join(f"{px(i):.1f},{py(c):.1f}" for i, (_, c) in enumerate(series))
    area = f"{left},{top_pad + plot_h} {points} {width - right},{top_pad + plot_h}"

    # Dot centres are filled with the card background so they read as rings in
    # either theme; a white fill would vanish on the light card.
    dots = [
        f'<circle cx="{px(i):.1f}" cy="{py(c):.1f}" r="2.5" fill="{th["bg"]}" '
        f'stroke="{th["accent"]}" stroke-width="1.5"/>'
        for i, (_, c) in enumerate(series)
    ]

    # Label roughly six dates so the axis stays readable at any window size.
    every = max(1, len(series) // 6)
    labels = [
        f'  <text x="{px(i):.1f}" y="{height - 18}" class="s" text-anchor="middle">'
        f'{date.strftime("%b %d")}</text>'
        for i, (date, _) in enumerate(series)
        if i % every == 0
    ]

    body = "\n".join(
        grid
        + [
            f'  <g class="c" style="animation-delay:.1s">'
            f'<polygon points="{area}" fill="{th["title"]}" fill-opacity="0.18"/>'
            f'<polyline points="{points}" fill="none" stroke="{th["accent"]}" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
            f'{"".join(dots)}</g>'
        ]
        + labels
    )
    total = sum(count for _, count in series)
    title = f"Contribution Graph - last {window} days ({total} contributions)"
    return frame(th, width, height, title, body)


def render_quote(th, day):
    """Rotate one quote per day, deterministically from the date."""
    text, author = QUOTES[day.toordinal() % len(QUOTES)]
    width, height = 700, 130
    body = (
        f'  <g class="c" style="animation-delay:.1s">'
        f'<text x="{width // 2}" y="62" text-anchor="middle" '
        f'style="font: 400 17px {FONT}; fill: {th["text"]}">'
        f"&#8220;{esc(text)}&#8221;</text>"
        f'<text x="{width // 2}" y="92" text-anchor="middle" '
        f'style="font: 400 13px {FONT}; fill: {th["muted"]}">'
        f"&#8212; {esc(author)}</text></g>"
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" \
viewBox="0 0 {width} {height}" role="img" aria-label="Developer quote">
  <title>{esc(text)} - {esc(author)}</title>
  <style>
    .c {{ opacity: 0; animation: f .6s ease-out forwards; }}
    @keyframes f {{ to {{ opacity: 1; }} }}
    @media (prefers-reduced-motion: reduce) {{
      .c {{ animation: none; opacity: 1; }}
    }}
  </style>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="6"
        fill="{th['bg']}" stroke="{th['border']}"/>
{body}
</svg>
"""


def wave(width, base, amp, humps):
    """Quadratic wave along y=base, alternating above and below."""
    seg = width / humps
    d = [f"M0,{base}"]
    for i in range(humps):
        x1 = (i + 1) * seg
        cx = i * seg + seg / 2
        cy = base + (amp if i % 2 == 0 else -amp)
        d.append(f"Q{cx:.1f},{cy:.1f} {x1:.1f},{base}")
    return " ".join(d)


def gradient(ident, colors, reverse=False, animate=True, dur=12):
    """Brand gradient. Each stop cycles through the ramp so the fill drifts.

    SMIL animation renders fine in GitHub READMEs - it is what drives the
    snake and typing SVGs already embedded here.
    """
    stops = list(colors[::-1] if reverse else colors)
    marks = []
    for i, colour in enumerate(stops):
        offset = i / (len(stops) - 1)
        # Walk the ramp starting from this stop, returning to itself so the
        # loop closes without a visible jump.
        cycle = stops[i:] + stops[:i] + [colour]
        anim = (
            f'<animate attributeName="stop-color" '
            f'values="{";".join(cycle)}" dur="{dur}s" '
            f'repeatCount="indefinite"/>'
            if animate
            else ""
        )
        marks.append(
            f'<stop offset="{offset:.2f}" stop-color="{colour}">{anim}</stop>'
        )
    return (
        f'<linearGradient id="{ident}" x1="0" y1="0" x2="1" y2="0">'
        f'{"".join(marks)}</linearGradient>'
    )


def drifting_wave(width, base, amp, humps, dur, fill, close_to):
    """A wave twice as wide as the frame, sliding left forever.

    The pattern repeats every 2*width/humps, so translating by exactly one
    period loops seamlessly with no visible seam.
    """
    span = width * 2
    total_humps = humps * 2
    period = span / total_humps * 2
    path = wave(span, base, amp, total_humps) + f" L{span},{close_to} L0,{close_to} Z"
    return (
        f'<g><path d="{path}" fill="{fill}"/>'
        f'<animateTransform attributeName="transform" type="translate" '
        f'from="0 0" to="-{period:.1f} 0" dur="{dur}s" '
        f'repeatCount="indefinite"/></g>'
    )


def particles(width, base, count=16, seed=11):
    """Motes drifting up through the band, fading as they rise."""
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        x = rng.uniform(30, width - 30)
        r = rng.uniform(1.2, 3.0)
        rise = rng.uniform(70, 150)
        dur = rng.uniform(7, 14)
        begin = rng.uniform(0, 10)
        out.append(
            f'<circle cx="{x:.0f}" cy="{base - 6:.0f}" r="{r:.1f}" '
            f'fill="#ffffff" opacity="0">'
            f'<animateTransform attributeName="transform" type="translate" '
            f'values="0 0;0 -{rise:.0f}" dur="{dur:.1f}s" begin="{begin:.1f}s" '
            f'repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0;.55;0" '
            f'dur="{dur:.1f}s" begin="{begin:.1f}s" repeatCount="indefinite"/>'
            f"</circle>"
        )
    return "".join(out)


def twinkles(width, height, count=26, seed=7):
    """Deterministic star field, so the file does not churn between runs."""
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        x = rng.uniform(20, width - 20)
        y = rng.uniform(14, height - 30)
        r = rng.uniform(0.9, 2.2)
        dur = rng.uniform(1.8, 4.2)
        begin = rng.uniform(0, 4)
        out.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.1f}" fill="#ffffff" '
            f'opacity="0">'
            f'<animate attributeName="opacity" values="0;.9;0" '
            f'dur="{dur:.1f}s" begin="{begin:.1f}s" repeatCount="indefinite"/>'
            f"</circle>"
        )
    return "".join(out)


def render_banner(name, subtitle):
    """Header band: drifting gradient, two sliding waves, twinkling stars.

    Transparent outside the band, so one copy serves light and dark.
    """
    width, height, base = 1200, 240, 186
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" \
viewBox="0 0 {width} {height}" role="img" aria-label="{esc(name)} - {esc(subtitle)}">
  <title>{esc(name)}</title>
  <defs>
    {gradient("g", BRAND, dur=14)}
    {gradient("g2", BRAND, reverse=True, dur=19)}
    <clipPath id="band"><rect width="{width}" height="{base + 30}"/></clipPath>
    <linearGradient id="shine" gradientUnits="userSpaceOnUse"
                    x1="-320" y1="0" x2="0" y2="0">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.72"/>
      <stop offset="0.5" stop-color="#ffffff" stop-opacity="1"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0.72"/>
      <animateTransform attributeName="gradientTransform" type="translate"
                        values="0 0;{width + 340} 0" dur="5s"
                        repeatCount="indefinite"/>
    </linearGradient>
  </defs>
  <g clip-path="url(#band)">
    {drifting_wave(width, base, 26, 4, 18, "url(#g)", 0)}
    <g opacity="0.35">
      {drifting_wave(width, base - 14, 20, 3, 27, "url(#g2)", 0)}
    </g>
    {twinkles(width, base)}
    {particles(width, base)}
  </g>
  <text x="{width // 2}" y="96" text-anchor="middle"
        style="font: 700 44px {FONT}" fill="url(#shine)">{esc(name)}
    <animate attributeName="opacity" values="0;1" dur="1s" fill="freeze"/>
  </text>
  <text x="{width // 2}" y="134" text-anchor="middle"
        style="font: 400 18px {FONT}; fill: #f0eaff">{esc(subtitle)}
    <animate attributeName="opacity" values="0;1" dur="1.4s" begin="0.3s"
             fill="freeze"/>
  </text>
</svg>
"""


def render_footer():
    width, height, base = 1200, 120, 46
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" \
viewBox="0 0 {width} {height}" role="img" aria-label="">
  <defs>
    {gradient("g", BRAND, reverse=True, dur=14)}
    {gradient("g2", BRAND, dur=21)}
    <clipPath id="fband"><rect y="{base - 30}" width="{width}" height="{height}"/></clipPath>
  </defs>
  <g clip-path="url(#fband)">
    {drifting_wave(width, base, 22, 4, 20, "url(#g)", height)}
    <g opacity="0.35">
      {drifting_wave(width, base + 12, 16, 3, 29, "url(#g2)", height)}
    </g>
  </g>
</svg>
"""


def render_divider():
    """Thin rule with a gradient that slides along it."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="3" \
viewBox="0 0 1200 3" role="img" aria-label="">
  <defs>{gradient("g", BRAND, dur=9)}</defs>
  <rect width="1200" height="3" rx="1.5" fill="url(#g)"/>
</svg>
"""


def title_case(name):
    """Capitalise all-lowercase words only, so acronym casing survives."""
    words = name.replace("_", "-").split("-")
    return " ".join(w.capitalize() if w.islower() else w for w in words)


MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,DejaVu Sans Mono,monospace"

TILE_BG = "#1a1b27"


def readable(hex_colour, floor=0.28):
    """Lift near-black brand colours so they show on the dark tile.

    Next.js, Express, GitHub, pandas and NumPy all ship almost-black marks,
    which would be invisible against the tile.
    """
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (0, 2, 4))
    if (0.2126 * r + 0.7152 * g + 0.0722 * b) < floor:
        return "#ffffff"
    return f"#{hex_colour}"


def glyph(key, x, y, size):
    """One brand mark, scaled from its native 24x24 box."""
    from brand_icons import ICONS, LETTERS

    if key in ICONS:
        _, hexv, path = ICONS[key]
        scale = size / 24
        return (
            f'<g transform="translate({x:.1f},{y:.1f}) scale({scale:.4f})">'
            f'<path d="{path}" fill="{readable(hexv)}"/></g>'
        )

    _, hexv, initials = LETTERS[key]
    return (
        f'<text x="{x + size / 2:.1f}" y="{y + size * 0.78:.1f}" '
        f'text-anchor="middle" style="font: 700 {size * 0.62:.0f}px {FONT}" '
        f'fill="{readable(hexv)}">{esc(initials)}</text>'
    )


def render_icon_row(keys, tile=50, gap=9, icon=26):
    """Row of brand tiles, each bobbing on its own stagger."""
    width = len(keys) * tile + (len(keys) - 1) * gap
    height = tile + 12
    cells = []
    for i, key in enumerate(keys):
        x = i * (tile + gap)
        pad = (tile - icon) / 2
        cells.append(
            f'  <g transform="translate({x},6)">'
            f'<animateTransform attributeName="transform" type="translate" '
            f'values="0 0;0 -4;0 0" dur="3.2s" begin="{i * 0.18:.2f}s" '
            f'repeatCount="indefinite" additive="sum"/>'
            f'<rect width="{tile}" height="{tile}" rx="11" fill="{TILE_BG}"/>'
            f"{glyph(key, pad, pad, icon)}</g>"
        )
    label = ", ".join(keys)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" \
height="{height}" viewBox="0 0 {width} {height}" role="img" \
aria-label="{esc(label)}">
  <title>{esc(label)}</title>
{chr(10).join(cells)}
</svg>
"""


def render_badge(message, colour, icon=None, label=None, height=28):
    """Pill badge in the flat for-the-badge style.

    Text is uppercase bold, sized from a per-character estimate; the padding
    absorbs the small error so nothing clips.
    """
    per, pad, gap = 8.4, 15, 8
    icon_w = 15 if icon else 0

    msg = message.upper()
    msg_w = len(msg) * per + pad * 2
    parts, width = [], 0

    if label:
        lab = label.upper()
        lab_w = len(lab) * per + pad * 2 + (icon_w + gap if icon else 0)
        parts.append(f'<rect width="{lab_w:.0f}" height="{height}" fill="#3a3f4b"/>')
        if icon:
            parts.append(glyph(icon, pad, (height - icon_w) / 2, icon_w))
        parts.append(
            f'<text x="{pad + (icon_w + gap if icon else 0):.0f}" '
            f'y="{height * 0.66:.0f}" style="font: 700 11px {FONT}; '
            f'letter-spacing: 1.1px" fill="#ffffff">{esc(lab)}</text>'
        )
        parts.append(
            f'<rect x="{lab_w:.0f}" width="{msg_w:.0f}" height="{height}" '
            f'fill="#{colour}"/>'
        )
        parts.append(
            f'<text x="{lab_w + msg_w / 2:.0f}" y="{height * 0.66:.0f}" '
            f'text-anchor="middle" style="font: 700 11px {FONT}; '
            f'letter-spacing: 1.1px" fill="#ffffff">{esc(msg)}</text>'
        )
        width = lab_w + msg_w
    else:
        width = msg_w + (icon_w + gap if icon else 0)
        parts.append(f'<rect width="{width:.0f}" height="{height}" fill="#{colour}"/>')
        if icon:
            parts.append(glyph(icon, pad, (height - icon_w) / 2, icon_w))
        parts.append(
            f'<text x="{pad + (icon_w + gap if icon else 0):.0f}" '
            f'y="{height * 0.66:.0f}" style="font: 700 11px {FONT}; '
            f'letter-spacing: 1.1px" fill="#ffffff">{esc(msg)}</text>'
        )

    body = "".join(parts)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" \
height="{height}" viewBox="0 0 {width:.0f} {height}" role="img" \
aria-label="{esc((label + ' ' if label else '') + message)}">
  <title>{esc((label + ' ' if label else '') + message)}</title>
  <clipPath id="r"><rect width="{width:.0f}" height="{height}" rx="4"/></clipPath>
  <g clip-path="url(#r)">{body}</g>
</svg>
"""


def keyframes(points):
    """Build (values, keyTimes) for SMIL from (time_fraction, value) pairs.

    Collapses duplicate times and pins the series to 0 and 1, which SMIL
    requires and which the first and last phrase would otherwise violate.
    """
    out = []
    for t, v in points:
        t = min(max(t, 0.0), 1.0)
        if out and abs(out[-1][0] - t) < 1e-6:
            out[-1] = (t, v)
        else:
            out.append((t, v))
    if out[0][0] > 0:
        out.insert(0, (0.0, out[0][1]))
    if out[-1][0] < 1:
        out.append((1.0, out[-1][1]))
    return (
        ";".join(str(v) for _, v in out),
        ";".join(f"{t:.4f}" for t, _ in out),
    )


def text_width(s, size):
    """Monospace advance. Non-ASCII (emoji) take roughly two cells."""
    cells = sum(2 if ord(c) > 0x2000 else 1 for c in s)
    return cells * size * 0.6


def render_typing(th, phrases, size=26, width=760, slot=3.6, colour=None):
    """Typing effect with a tracking cursor, replacing the demolab service.

    Each phrase types out, holds, then backspaces, so the clip returns to
    zero before the next one starts and no frame shows a half-erased line.
    """
    colour = colour or th["title"]
    height = int(size * 2.2)
    cy = height * 0.68
    cycle = slot * len(phrases)
    bar_h = size * 1.15
    bar_y = cy - size * 0.92

    defs, body = [], []
    for i, phrase in enumerate(phrases):
        w = text_width(phrase, size)
        x0 = (width - w) / 2
        t0 = i * slot / cycle
        t_type = (i * slot + slot * 0.45) / cycle
        t_hold = (i * slot + slot * 0.80) / cycle
        t_end = (i + 1) * slot / cycle

        wid_v, wid_t = keyframes(
            [(0, 0), (t0, 0), (t_type, round(w, 1)), (t_hold, round(w, 1)),
             (t_end, 0)]
        )
        cur_v, cur_t = keyframes(
            [(0, round(x0, 1)), (t0, round(x0, 1)),
             (t_type, round(x0 + w, 1)), (t_hold, round(x0 + w, 1)),
             (t_end, round(x0, 1))]
        )
        vis_v, vis_t = keyframes([(0, 0), (t0, 1), (t_end, 0)])

        defs.append(
            f'<clipPath id="tc{i}"><rect x="{x0:.1f}" y="0" '
            f'height="{height}" width="0">'
            f'<animate attributeName="width" values="{wid_v}" '
            f'keyTimes="{wid_t}" dur="{cycle:.1f}s" '
            f'repeatCount="indefinite"/></rect></clipPath>'
        )
        body.append(
            f'  <g clip-path="url(#tc{i})">'
            f'<text x="{x0:.1f}" y="{cy:.1f}" '
            f'style="font: 700 {size}px {MONO}; fill: {colour}">'
            f"{esc(phrase)}</text></g>\n"
            f'  <g opacity="0"><animate attributeName="opacity" '
            f'values="{vis_v}" keyTimes="{vis_t}" calcMode="discrete" '
            f'dur="{cycle:.1f}s" repeatCount="indefinite"/>'
            f'<rect y="{bar_y:.1f}" width="2.5" height="{bar_h:.1f}" '
            f'rx="1" fill="{th["accent"]}" x="{x0:.1f}">'
            f'<animate attributeName="x" values="{cur_v}" keyTimes="{cur_t}" '
            f'dur="{cycle:.1f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="1;1;0;0" '
            f'keyTimes="0;0.49;0.5;1" calcMode="discrete" dur="1.1s" '
            f'repeatCount="indefinite"/></rect></g>'
        )

    label = " / ".join(phrases)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" \
height="{height}" viewBox="0 0 {width} {height}" role="img" \
aria-label="{esc(label)}">
  <title>{esc(label)}</title>
  <defs>{"".join(defs)}</defs>
{chr(10).join(body)}
</svg>
"""


def projects_table(repos, login, limit=12):
    """Markdown table of the featured projects.

    Uses the hand-picked FEATURED order, looking each entry up in the API
    data for its tech stack. Entries whose repo no longer exists are skipped
    rather than emitting a dead row. If none resolve at all, it falls back to
    auto-discovery so the table degrades instead of vanishing.
    """
    by_name = {r["name"].lower(): r for r in repos}
    picked = []

    for emoji, label, repo_name, blurb, kind in FEATURED:
        repo = by_name.get(repo_name.lower())
        if repo is None:
            print(f"note: featured repo {repo_name} not found, skipping")
            continue
        target = (
            repo.get("homepageUrl")
            if kind == "demo"
            else f"https://github.com/{login}/{repo['name']}"
        )
        if not (target or "").startswith("http"):
            print(f"note: featured repo {repo_name} has no usable link")
            continue
        picked.append((emoji, label, repo, blurb, kind, target))

    if not picked:
        auto = [
            r for r in repos
            if (r.get("homepageUrl") or "").startswith("http")
            and r["name"].lower() != login.lower()
        ]
        auto.sort(key=lambda r: (r["stargazerCount"], r["pushedAt"]), reverse=True)
        picked = [
            ("🚀", title_case(r["name"]), r, (r["description"] or "").strip(),
             "demo", r["homepageUrl"])
            for r in auto[:limit]
        ]

    rows = ["| 🚀 Project | 💡 Description | 🧰 Tech | 🔗 Link |",
            "| :--- | :--- | :--- | :---: |"]
    for emoji, label, repo, blurb, kind, target in picked[:limit]:
        desc = (blurb or repo.get("description") or "").strip()
        # Keep the table one line per row however long the description is.
        if len(desc) > 78:
            desc = desc[:75].rstrip() + "..."
        desc = desc.replace("|", "\\|") or "&mdash;"
        langs = [e["node"]["name"] for e in repo["languages"]["edges"][:3]]
        tech = " ".join(f"`{l}`" for l in langs) or "-"
        text = "Demo" if kind == "demo" else "Code"
        rows.append(
            f"| **{emoji} {label}** | {desc} | {tech} | [{text}]({target}) |"
        )
    return "\n".join(rows), len(picked[:limit])


def inject(readme_path, table, count):
    """Replace the marked regions of the README in place."""
    if not os.path.exists(readme_path):
        print(f"note: {readme_path} not found, skipping injection")
        return False

    with open(readme_path, encoding="utf-8") as fh:
        original = fh.read()

    updated = original
    for name, value in (("PROJECTS", table), ("PROJECTCOUNT", str(count))):
        pattern = re.compile(
            rf"(<!-- {name}:START -->)(.*?)(<!-- {name}:END -->)", re.S
        )
        if not pattern.search(updated):
            print(f"note: no {name} markers in {readme_path}")
            continue
        joiner = "\n\n" if name == "PROJECTS" else ""
        updated = pattern.sub(
            lambda m: f"{m.group(1)}{joiner}{value}{joiner}{m.group(3)}", updated
        )

    if updated == original:
        return False
    with open(readme_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(updated)
    return True


def main():
    login = os.environ.get("USERNAME") or sys.exit("USERNAME is not set")
    out = os.environ.get("OUT_DIR", "assets")
    readme = os.environ.get("README_PATH", "README.md")
    os.makedirs(out, exist_ok=True)

    profile, totals, days = fetch(login)
    repos = profile["repositories"]["nodes"]
    stars = sum(r["stargazerCount"] for r in repos)
    total, current, longest, cur_start, cur_end = streaks(days)
    langs = top_languages(repos)
    name = profile["name"] or login

    def pretty(iso, fmt="%b %d, %Y"):
        return datetime.fromisoformat(iso).strftime(fmt) if iso else ""

    dates = sorted(days)
    first = pretty(dates[0]) if dates else ""
    if current:
        # A live streak reads as "Jun 25 - Present"; a stale one keeps its
        # real end date rather than implying it is still running.
        today_iso = datetime.now(timezone.utc).date().isoformat()
        tail = "Present" if cur_end >= today_iso else pretty(cur_end, "%b %d")
        last = f"{pretty(cur_start, '%b %d')} - {tail}"
    else:
        last = ""

    today = datetime.now(timezone.utc).date()
    written = []

    for suffix, th in THEMES.items():
        cards = {
            f"stats{suffix}.svg": render_stats(
                th, name, stars, totals,
                profile["repositories"]["totalCount"],
                profile["followers"]["totalCount"],
            ),
            f"top-langs{suffix}.svg": render_langs(th, langs),
            f"streak{suffix}.svg": render_streak(
                th, total, current, longest, first, last
            ),
            f"activity{suffix}.svg": render_activity(th, days),
            f"quote{suffix}.svg": render_quote(th, today),
            f"typing{suffix}.svg": render_typing(th, TYPING_HERO),
            f"typing-outro{suffix}.svg": render_typing(
                th, TYPING_OUTRO, size=18, width=620, slot=4.0,
                colour=th["accent"],
            ),
        }
        for filename, svg in cards.items():
            with open(os.path.join(out, filename), "w", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(svg)
            written.append(filename)

    followers = profile["followers"]["totalCount"]
    chrome = {
        "banner.svg": render_banner(
            name, "Software Engineer - Full-Stack Developer - AI/ML Enthusiast"
        ),
        "footer.svg": render_footer(),
        "divider.svg": render_divider(),
        # Tiles and pills carry their own colour, so one copy serves both
        # themes and there is no -light variant to keep in step.
        "icons-ai.svg": render_icon_row(
            ["python", "tensorflow", "pytorch", "sklearn", "opencv"]
        ),
        "icons-lang.svg": render_icon_row(
            ["cpp", "python", "js", "ts", "html", "css"]
        ),
        "icons-frameworks.svg": render_icon_row(
            ["react", "nextjs", "nodejs", "express", "tailwind", "vite"]
        ),
        "icons-tools.svg": render_icon_row(
            ["mongodb", "mysql", "git", "github", "vscode", "postman"]
        ),
        "badge-followers.svg": render_badge(
            str(followers), "6c5ce7", "github", "Followers"
        ),
        "badge-linkedin.svg": render_badge("Connect", "0A66C2", "linkedin", "LinkedIn"),
        "badge-email.svg": render_badge("Say Hi", "0e7490", "gmail", "Email"),
        "badge-pandas.svg": render_badge("Pandas", "150458", "pandas"),
        "badge-numpy.svg": render_badge("NumPy", "013243", "numpy"),
        "badge-jupyter.svg": render_badge("Jupyter", "F37626", "jupyter"),
        "badge-gemini.svg": render_badge("Google Gemini", "8E75B2", "gemini"),
        "badge-openai.svg": render_badge("OpenAI", "412991", "openai"),
        "badge-linkedin-solo.svg": render_badge("LinkedIn", "0A66C2", "linkedin"),
        "badge-gmail.svg": render_badge("Gmail", "EA4335", "gmail"),
        "badge-github.svg": render_badge("GitHub", "181717", "github"),
    }
    for filename, svg in chrome.items():
        with open(os.path.join(out, filename), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(svg)
        written.append(filename)

    table, count = projects_table(repos, login)
    changed = inject(readme, table, count)

    print(f"wrote {len(written)} assets: {', '.join(sorted(written))}")
    print(f"projects table: {count} live projects, readme changed={changed}")
    print(
        f"stars={stars} commits={totals['commits']} prs={totals['prs']} "
        f"issues={totals['issues']} streak={current} longest={longest}"
    )


if __name__ == "__main__":
    main()
