#!/usr/bin/env python3
"""Generate Pedro's light and dark Neofetch-style profile cards."""

from __future__ import annotations

import datetime as dt
import html
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


USERNAME = "pedrovyg"
BIRTHDAY = dt.date(2001, 10, 5)
OUTPUT_DIR = Path("profile")
CARD_WIDTH = 850
INFO_X = 335
ASCII_ART_PATH = Path("profile/ascii-art.txt")
ASCII_X = 5
ASCII_TOP = 44
ASCII_FONT_SIZE = 3
ASCII_LINE_HEIGHT = 3.6
TITLE = "pedro@vygotsky"
TEXT_CHAR_WIDTH = 8.4
CURSOR_GAP = 5
CURSOR_WIDTH = 8
CURSOR_HEIGHT = 14


def github_request(url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload else None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "pedrovyg-neofetch-profile",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def age_since(birthday: dt.date, today: dt.date) -> str:
    years = today.year - birthday.year
    months = today.month - birthday.month
    days = today.day - birthday.day
    if days < 0:
        previous_month = today.replace(day=1) - dt.timedelta(days=1)
        days += previous_month.day
        months -= 1
    if months < 0:
        months += 12
        years -= 1
    return f"{years} years, {months} months, {days} days"


def load_stats(token: str) -> dict[str, int]:
    user = github_request(f"https://api.github.com/users/{USERNAME}", token)
    repos = github_request(
        f"https://api.github.com/users/{USERNAME}/repos?per_page=100&type=owner&sort=updated",
        token,
    )
    commit_search = github_request(
        f"https://api.github.com/search/commits?q=author:{USERNAME}", token
    )
    contributions = 0
    if token:
        today = dt.datetime.now(dt.timezone.utc)
        start = today - dt.timedelta(days=364)
        query = """
        query($login: String!, $from: DateTime!, $to: DateTime!) {
          user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
              contributionCalendar { totalContributions }
            }
          }
        }
        """
        graph = github_request(
            "https://api.github.com/graphql",
            token,
            {
                "query": query,
                "variables": {
                    "login": USERNAME,
                    "from": start.isoformat(),
                    "to": today.isoformat(),
                },
            },
        )
        contributions = graph["data"]["user"]["contributionsCollection"][
            "contributionCalendar"
        ]["totalContributions"]
    return {
        "repos": int(user.get("public_repos", len(repos))),
        "stars": sum(int(repo.get("stargazers_count", 0)) for repo in repos),
        "followers": int(user.get("followers", 0)),
        "commits": int(commit_search.get("total_count", 0)),
        "contributions": int(contributions),
    }


def tspan(y: int, label: str, value: str, *, heading: bool = False) -> str:
    if heading:
        return f'<tspan x="{INFO_X}" y="{y}" class="text">{html.escape(label)}</tspan>'
    leader = "." * max(2, 22 - len(label))
    return (
        f'<tspan x="{INFO_X}" y="{y}" class="muted">. </tspan>'
        f'<tspan class="key">{html.escape(label)}</tspan>'
        f'<tspan class="muted">: {leader} </tspan>'
        f'<tspan class="value">{html.escape(value)}</tspan>'
    )


def render(theme: str, stats: dict[str, int]) -> str:
    dark = theme == "dark"
    colors = {
        "bg": "#161b22" if dark else "#f6f8fa",
        "text": "#c9d1d9" if dark else "#24292f",
        "key": "#ffa657" if dark else "#bc4c00",
        "value": "#a5d6ff" if dark else "#0969da",
        "muted": "#6e7681" if dark else "#57606a",
        "border": "#30363d" if dark else "#d0d7de",
        "cursor": "#3fb950" if dark else "#1a7f37",
    }
    ascii_green = (
        ("#aff5b4", "#3fb950", "#238636")
        if dark
        else ("#2da44e", "#1a7f37", "#116329")
    )
    ascii_neutral = (
        ("#f0f6fc", "#c9d1d9", "#8b949e")
        if dark
        else ("#57606a", "#424a53", "#24292f")
    )
    ascii_lines = ASCII_ART_PATH.read_text(encoding="utf-8").splitlines()
    ascii_spans = "\n".join(
        f'<tspan x="{ASCII_X}" y="{ASCII_TOP + i * ASCII_LINE_HEIGHT:.1f}">{html.escape(line)}</tspan>'
        for i, line in enumerate(ascii_lines)
    )
    today = dt.datetime.now(dt.timezone.utc).date()
    lines = [
        tspan(50, "OS", "Windows 11, WSL/Linux, Android"),
        tspan(70, "Uptime", age_since(BIRTHDAY, today)),
        tspan(90, "Host", "Computer Science — Estácio"),
        tspan(110, "Kernel", "Software Developer"),
        tspan(130, "IDE", "VS Code, IntelliJ IDEA"),
        tspan(170, "Languages.Programming", "JavaScript, TypeScript, Java"),
        tspan(190, "Languages.Web", "HTML, CSS, React, Node.js"),
        tspan(210, "Tools.Development", "Git, GitHub, Docker, Maven, Gradle"),
        tspan(230, "Languages.Real", "Portuguese, English (learning)"),
        tspan(260, "Interests.Technology", "Generative AI, Web Development"),
        tspan(300, "- Contact ─────────────────────────────────────────", "", heading=True),
        tspan(320, "Email", "pedrovyg.dev@gmail.com"),
        tspan(340, "LinkedIn", "linkedin.com/in/pedrovygotsky"),
        tspan(360, "GitHub", "github.com/pedrovyg"),
        tspan(380, "Location", "Recife, Pernambuco, Brazil"),
        tspan(410, "- GitHub Stats ─────────────────────────────────────", "", heading=True),
        tspan(430, "Repositories", f'{stats["repos"]:,}  |  Stars: {stats["stars"]:,}'),
        tspan(450, "Contributions (1y)", f'{stats["contributions"]:,}'),
        tspan(470, "Public commits", f'{stats["commits"]:,}  |  Followers: {stats["followers"]:,}'),
        tspan(510, "Updated", today.isoformat()),
    ]
    cursor_x = INFO_X + len(TITLE) * TEXT_CHAR_WIDTH + CURSOR_GAP
    divider_x = cursor_x + CURSOR_WIDTH + 7
    header = (
        f'<text x="{INFO_X}" y="30" class="text">{TITLE}</text>'
        f'<rect class="cursor" x="{cursor_x:.1f}" y="17" '
        f'width="{CURSOR_WIDTH}" height="{CURSOR_HEIGHT}" fill="{colors["cursor"]}"/>'
        f'<text x="{divider_x:.1f}" y="30" class="muted">'
        '────────────────────────────────────────</text>'
    )
    gradient = lambda gradient_id, stops: (
        f'<linearGradient id="{gradient_id}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{stops[0]}"/>'
        f'<stop offset="0.5" stop-color="{stops[1]}"/>'
        f'<stop offset="1" stop-color="{stops[2]}"/>'
        '</linearGradient>'
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}" height="530" viewBox="0 0 {CARD_WIDTH} 530" role="img" aria-label="Pedro Vygotsky Neofetch profile">
<style>
@keyframes ascii-color-cycle {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0; }} }}
@keyframes cursor-blink {{ 50% {{ opacity: 0; }} }}
.ascii-neutral {{ animation: ascii-color-cycle 9s ease-in-out infinite; }}
.cursor {{ animation: cursor-blink 1.1s step-end infinite; }}
@media (prefers-reduced-motion: reduce) {{
  .ascii-neutral {{ animation: none; opacity: 0; }}
  .cursor {{ animation: none; opacity: 1; }}
}}
text {{ font: 14px Consolas, "Liberation Mono", monospace; white-space: pre; }}
.ascii {{ font-size: {ASCII_FONT_SIZE}px; }}
.text {{ fill: {colors["text"]}; }} .key {{ fill: {colors["key"]}; }}
.value {{ fill: {colors["value"]}; }} .muted {{ fill: {colors["muted"]}; }}
</style>
<defs>
{gradient("ascii-green", ascii_green)}
{gradient("ascii-neutral", ascii_neutral)}
</defs>
<rect x="0.5" y="0.5" width="{CARD_WIDTH - 1}" height="529" rx="15" fill="{colors["bg"]}" stroke="{colors["border"]}"/>
<text class="ascii" fill="url(#ascii-green)">{ascii_spans}</text>
<text class="ascii ascii-neutral" fill="url(#ascii-neutral)">{ascii_spans}</text>
{header}
<text>{''.join(lines)}</text>
</svg>
'''


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    stats = load_stats(token)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for theme in ("dark", "light"):
        (OUTPUT_DIR / f"neofetch-{theme}.svg").write_text(
            render(theme, stats), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
