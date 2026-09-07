#!/usr/bin/env python3
"""Generate Pedro's light and dark Neofetch-style profile cards."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
from collections.abc import Mapping
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USERNAME = "pedrovyg"
BIRTHDAY = dt.date(2001, 10, 5)
OUTPUT_DIR = Path("profile")
CARD_WIDTH = 850
CARD_HEIGHT = 530
INFO_X = 335
ASCII_ART_PATH = Path("profile/ascii-art.txt")
ASCII_X = 18
ASCII_TOP = 38
ASCII_FONT_SIZE = 12
ASCII_LINE_HEIGHT = 8.5
ASCII_FRAME_SEPARATOR = "\n===FRAME===\n"
ASCII_FRAME_INTERVAL = 0.1
ASCII_FRAME_FADE_RATIO = 1.0
TITLE = "pedro@vygotsky"
TEXT_CHAR_WIDTH = 8.4
CURSOR_GAP = 5
CURSOR_WIDTH = 8
CURSOR_HEIGHT = 14
THEMES = ("dark", "light")
TITLE_ID = "svg-title"
DESCRIPTION_ID = "svg-description"


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
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as error:
        body = error.read(512).decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API returned HTTP {error.code} for {url}: {body}"
        ) from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"GitHub API request failed for {url}: {error}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"GitHub API returned invalid JSON for {url}") from error

    if not isinstance(result, dict):
        raise RuntimeError(f"GitHub API returned an unexpected response for {url}")
    return result


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
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN is required for live stats; use --stats-json for local tests."
        )

    user = github_request(f"https://api.github.com/users/{USERNAME}", token)
    commit_search = github_request(
        f"https://api.github.com/search/commits?q=author:{USERNAME}", token
    )
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
    if graph.get("errors"):
        raise RuntimeError(f"GitHub GraphQL returned errors: {graph['errors']}")
    try:
        contributions = graph["data"]["user"]["contributionsCollection"][
            "contributionCalendar"
        ]["totalContributions"]
        stats = {
            "repos": int(user["public_repos"]),
            "commits": int(commit_search["total_count"]),
            "contributions": int(contributions),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("GitHub response is missing required numeric stats") from error
    return validate_stats(stats)


def validate_stats(stats: Mapping[str, object]) -> dict[str, int]:
    """Return the supported stats after strict type and range checks."""
    required = ("repos", "commits", "contributions")
    validated: dict[str, int] = {}
    for key in required:
        value = stats.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Stat {key!r} must be a non-negative integer")
        validated[key] = value
    return validated


def read_ascii_frames(ascii_art_path: Path) -> list[list[str]]:
    """Read frames byte-for-byte without trimming visible whitespace."""
    try:
        ascii_source = ascii_art_path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"ASCII source is not valid UTF-8: {ascii_art_path}") from error
    if "\r" in ascii_source:
        raise ValueError("ASCII source must use LF line endings")
    if not ascii_source.endswith("\n"):
        raise ValueError("ASCII source must end with exactly one LF")
    source_body = ascii_source[:-1]
    if source_body.endswith("\n"):
        raise ValueError("ASCII source contains an unexpected extra trailing LF")
    frames = [
        frame.split("\n") for frame in source_body.split(ASCII_FRAME_SEPARATOR)
    ]
    if not frames or any(not frame for frame in frames):
        raise ValueError("ASCII animation source contains an empty frame")
    return frames


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


def render(
    theme: str,
    stats: Mapping[str, int],
    ascii_frames: list[list[str]],
    rendered_on: dt.date,
) -> str:
    if theme not in THEMES:
        raise ValueError(f"Unsupported theme: {theme}")
    stats = validate_stats(stats)
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
    frame_count = len(ascii_frames)
    motion_duration = frame_count * ASCII_FRAME_INTERVAL
    frame_step = 100 / frame_count
    fade_step = frame_step * ASCII_FRAME_FADE_RATIO
    frame_styles = "".join(
        f'.ascii-frame-{index}{{animation-delay:'
        f'{index * ASCII_FRAME_INTERVAL - motion_duration:.2f}s}}'
        for index in range(frame_count)
    )
    ascii_layers = "\n".join(
        f'<text class="ascii ascii-frame ascii-frame-{frame_index}" '
        f'fill="url(#ascii-color)">'
        + "\n".join(
            f'<tspan x="{ASCII_X}" '
            f'y="{ASCII_TOP + line_index * ASCII_LINE_HEIGHT:.1f}">'
            f'{html.escape(line)}</tspan>'
            for line_index, line in enumerate(frame)
        )
        + "</text>"
        for frame_index, frame in enumerate(ascii_frames)
    )
    lines = [
        tspan(50, "OS", "Windows 11, WSL/Linux, Android"),
        tspan(70, "Uptime", age_since(BIRTHDAY, rendered_on)),
        tspan(90, "Host", "Computer Science"),
        tspan(110, "Kernel", "Software Developer"),
        tspan(130, "IDE", "VS Code, IntelliJ IDEA"),
        tspan(170, "Languages.Coding", "JavaScript, TypeScript, Java"),
        tspan(190, "Languages.Web", "HTML, CSS, React, Node.js"),
        tspan(210, "Tools.Development", "Git, GitHub, Docker, Maven, Gradle"),
        tspan(230, "Languages.Real", "Portuguese, English"),
        tspan(260, "Interests.Technology", "Generative AI, Web Development"),
        tspan(300, "- Contact ─────────────────────────────────────────", "", heading=True),
        tspan(320, "Email", "pedrovyg.dev@gmail.com"),
        tspan(340, "LinkedIn", "linkedin.com/in/pedrovygotsky"),
        tspan(360, "Instagram", "instagram.com/pedrovyg"),
        tspan(380, "Discord", "discord.com/users/pedrovyg"),
        tspan(410, "- GitHub Stats ─────────────────────────────────────", "", heading=True),
        tspan(430, "Repositories", f'{stats["repos"]:,}'),
        tspan(450, "Contributions (1y)", f'{stats["contributions"]:,}'),
        tspan(470, "Public commits", f'{stats["commits"]:,}'),
        tspan(510, "Updated", rendered_on.isoformat()),
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
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" role="img" aria-labelledby="{TITLE_ID} {DESCRIPTION_ID}" focusable="false">
<title id="{TITLE_ID}">Pedro Vygotsky Neofetch profile</title>
<desc id="{DESCRIPTION_ID}">Animated fluid diamond ASCII art with development tools, contact details, and current public GitHub statistics.</desc>
<style>
@keyframes ascii-frame-motion {{
  0% {{ opacity: 0; }}
  {fade_step:.3f}% {{ opacity: 1; }}
  {frame_step:.3f}% {{ opacity: 1; }}
  {frame_step + fade_step:.3f}% {{ opacity: 0; }}
  100% {{ opacity: 0; }}
}}
@keyframes ascii-top-color {{
  0%, 100% {{ stop-color: {ascii_neutral[0]}; }}
  50% {{ stop-color: {ascii_green[0]}; }}
}}
@keyframes ascii-middle-color {{
  0%, 100% {{ stop-color: {ascii_neutral[1]}; }}
  50% {{ stop-color: {ascii_green[1]}; }}
}}
@keyframes ascii-bottom-color {{
  0%, 100% {{ stop-color: {ascii_neutral[2]}; }}
  50% {{ stop-color: {ascii_green[2]}; }}
}}
@keyframes cursor-blink {{ 50% {{ opacity: 0; }} }}
.ascii-frame {{
  opacity: 0;
  animation: ascii-frame-motion {motion_duration:.1f}s ease-in-out infinite;
}}
{frame_styles}
.ascii-frame-0 {{ opacity: 1; }}
.ascii-stop-top {{ animation: ascii-top-color 9s ease-in-out infinite; }}
.ascii-stop-middle {{ animation: ascii-middle-color 9s ease-in-out infinite; }}
.ascii-stop-bottom {{ animation: ascii-bottom-color 9s ease-in-out infinite; }}
.cursor {{ animation: cursor-blink 1.1s step-end infinite; }}
@media (prefers-reduced-motion: reduce) {{
  .ascii-frame {{ animation: none; opacity: 0; }}
  .ascii-frame-0 {{ opacity: 1; }}
  .ascii-stop-top, .ascii-stop-middle, .ascii-stop-bottom {{ animation: none; }}
  .cursor {{ animation: none; opacity: 1; }}
}}
text {{ font: 14px Consolas, "Liberation Mono", monospace; white-space: pre; }}
.ascii {{
  font-size: {ASCII_FONT_SIZE}px;
  font-family: Consolas, "DejaVu Sans Mono", "Liberation Mono", monospace;
  text-rendering: geometricPrecision;
}}
.text {{ fill: {colors["text"]}; }} .key {{ fill: {colors["key"]}; }}
.value {{ fill: {colors["value"]}; }} .muted {{ fill: {colors["muted"]}; }}
</style>
<defs>
<linearGradient id="ascii-color" x1="0" y1="0" x2="0" y2="1">
  <stop class="ascii-stop-top" offset="0" stop-color="{ascii_green[0]}"/>
  <stop class="ascii-stop-middle" offset="0.5" stop-color="{ascii_green[1]}"/>
  <stop class="ascii-stop-bottom" offset="1" stop-color="{ascii_green[2]}"/>
</linearGradient>
</defs>
<rect x="0.5" y="0.5" width="{CARD_WIDTH - 1}" height="{CARD_HEIGHT - 1}" rx="15" fill="{colors["bg"]}" stroke="{colors["border"]}"/>
{ascii_layers}
{header}
<text>{''.join(lines)}</text>
</svg>
'''


def write_assets(
    output_dir: Path,
    ascii_art_path: Path,
    stats: Mapping[str, int],
    rendered_on: dt.date,
) -> list[Path]:
    """Render both themes with explicit inputs and stable LF line endings."""
    frames = read_ascii_frames(ascii_art_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for theme in THEMES:
        output_path = output_dir / f"neofetch-{theme}.svg"
        with output_path.open("w", encoding="utf-8", newline="\n") as output:
            output.write(render(theme, stats, frames, rendered_on))
        outputs.append(output_path)
    return outputs


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--ascii-art", type=Path, default=ASCII_ART_PATH)
    parser.add_argument(
        "--date",
        type=parse_date,
        default=dt.datetime.now(dt.timezone.utc).date(),
        help="Stable UTC rendering date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--stats-json",
        help="Optional inline JSON stats for deterministic local testing.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.stats_json:
        try:
            raw_stats = json.loads(args.stats_json)
        except json.JSONDecodeError as error:
            raise SystemExit(f"Invalid --stats-json: {error}") from error
        if not isinstance(raw_stats, dict):
            raise SystemExit("--stats-json must contain a JSON object")
        stats = validate_stats(raw_stats)
    else:
        stats = load_stats(os.environ.get("GITHUB_TOKEN", ""))
    write_assets(args.output_dir, args.ascii_art, stats, args.date)


if __name__ == "__main__":
    main()
