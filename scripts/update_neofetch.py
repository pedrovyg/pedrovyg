#!/usr/bin/env python3
"""Generate Pedro's light and dark Neofetch-style profile cards."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError

from generate_ascii_animation import (
    DEFAULT_QUALITY,
    QUALITY_PRESETS,
    QualityPreset,
    get_quality,
)
from urllib.request import Request, urlopen


USERNAME = "pedrovyg"
BIRTHDAY = dt.date(2001, 10, 5)
PROFILE_VIEWS_BASELINE = 764
PROFILE_VIEWS_TIMEOUT = 5
PROFILE_VIEWS_URL = (
    "https://komarev.com/ghpvc/"
    "?username=pedrovyg&label=profile%20views&color=green&style=flat"
)
PROFILE_VIEWS_X = 820
PROFILE_VIEWS_LABEL_Y = 15
PROFILE_VIEWS_VALUE_Y = 34
OUTPUT_DIR = Path("profile")
CARD_WIDTH = 850
CARD_HEIGHT = 530
INFO_X = 335
INFO_RIGHT = 832
ASCII_ART_PATH = Path("profile/ascii-art.txt")
ASCII_X = 18
ASCII_TOP = 38
ASCII_FONT_SIZE = 12
ASCII_LINE_HEIGHT = 8.5
ASCII_FRAME_SEPARATOR = "\n===FRAME===\n"
TEXT_CHAR_WIDTH = 8.4
TYPING_PHRASES = (
    "Pedro Vygotsky",
    "Full-Stack & AI Developer",
    "Building real projects for businesses",
)
TYPING_Y = 30
TYPING_CHAR_SECONDS = 0.075
TYPING_DELETE_SECONDS = 0.04
TYPING_HOLD_SECONDS = 1.1
TYPING_PAUSE_SECONDS = 0.35
CURSOR_GAP = 2
THEMES = ("dark", "light")
TITLE_ID = "svg-title"
DESCRIPTION_ID = "svg-description"
GRAPH_X = 585
GRAPH_Y = 412
GRAPH_WIDTH = 247
GRAPH_HEIGHT = 112
GRAPH_PADDING_LEFT = 24
GRAPH_PADDING_RIGHT = 4
GRAPH_PADDING_TOP = 18
GRAPH_PADDING_BOTTOM = 16
GRAPH_MAX_WEEKS = 52
GRAPH_ID = "github-contrib-chart"
GRAPH_TITLE_ID = "github-contrib-title"
GRAPH_GRADIENT_ID = "github-contrib-gradient"
GRAPH_CLIP_ID = "github-contrib-clip"
METRICS_X = INFO_X + 16
METRICS_Y = 420
METRICS_WIDTH = GRAPH_X - METRICS_X - 10
METRICS_HEIGHT = CARD_HEIGHT - METRICS_Y - 10


@dataclass(frozen=True)
class ContributionWeek:
    """A validated weekly contribution total and its first calendar day."""

    start: dt.date
    count: int


@dataclass(frozen=True)
class GitHubProfileData:
    """Public profile totals plus the contribution series used by the chart."""

    stats: dict[str, int]
    contribution_weeks: tuple[ContributionWeek, ...] = ()
    profile_views: int = PROFILE_VIEWS_BASELINE


def parse_profile_views_svg(payload: bytes) -> int:
    """Extract the integer rendered by Komarev without relying on SVG positions."""
    if not payload or len(payload) > 65_536:
        raise RuntimeError("Komarev returned an empty or oversized response")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise RuntimeError("Komarev returned invalid SVG") from error
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise RuntimeError("Komarev response is not an SVG")

    values: set[int] = set()
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "text":
            continue
        text = "".join(element.itertext()).strip()
        if re.fullmatch(r"(?:\d{1,3}(?:,\d{3})*|\d+)", text):
            values.add(int(text.replace(",", "")))
    if len(values) != 1:
        raise RuntimeError("Komarev SVG does not contain one unambiguous view count")
    return values.pop()


def fetch_profile_views(timeout: int = PROFILE_VIEWS_TIMEOUT) -> int:
    """Fetch the current public Komarev counter with a bounded request."""
    request = Request(
        PROFILE_VIEWS_URL,
        headers={
            "Accept": "image/svg+xml",
            "User-Agent": "pedrovyg-neofetch-profile",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(65_537)
    except HTTPError as error:
        raise RuntimeError(f"Komarev returned HTTP {error.code}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"Komarev request failed: {error}") from error
    return parse_profile_views_svg(payload)


def resolve_profile_views(
    fetched_value: object | None, cached_value: object | None = None
) -> int:
    """Keep the public counter monotonic and never below the migration baseline."""
    values = [PROFILE_VIEWS_BASELINE]
    for value in (cached_value, fetched_value):
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            values.append(value)
    return max(values)


def load_profile_views(cached_value: int | None = None) -> int:
    """Use the live counter when available and the embedded value when offline."""
    try:
        fetched_value: int | None = fetch_profile_views()
    except RuntimeError:
        fetched_value = None
    return resolve_profile_views(fetched_value, cached_value)


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


def parse_iso_date(value: object) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def aggregate_contributions(raw_weeks: object) -> tuple[ContributionWeek, ...]:
    """Aggregate GitHub calendar days and retain the most recent 52 weeks."""
    if not isinstance(raw_weeks, list):
        return ()

    aggregated: list[ContributionWeek] = []
    for raw_week in raw_weeks:
        if not isinstance(raw_week, Mapping):
            continue
        raw_days = raw_week.get("contributionDays")
        if not isinstance(raw_days, list) or not raw_days:
            continue

        start = parse_iso_date(raw_week.get("firstDay"))
        if start is None:
            first_day = raw_days[0]
            if isinstance(first_day, Mapping):
                start = parse_iso_date(first_day.get("date"))
        if start is None:
            continue

        count = 0
        valid_week = True
        for raw_day in raw_days:
            if not isinstance(raw_day, Mapping):
                valid_week = False
                break
            day_count = raw_day.get("contributionCount")
            if (
                isinstance(day_count, bool)
                or not isinstance(day_count, int)
                or day_count < 0
            ):
                valid_week = False
                break
            count += day_count
        if valid_week:
            aggregated.append(ContributionWeek(start=start, count=count))

    aggregated.sort(key=lambda week: week.start)
    return tuple(aggregated[-GRAPH_MAX_WEEKS:])


def validate_contribution_weeks(raw_weeks: object) -> tuple[ContributionWeek, ...]:
    """Validate deterministic contribution data supplied by tests or cache."""
    if raw_weeks is None:
        return ()
    if not isinstance(raw_weeks, list):
        raise ValueError("contribution_weeks must be a list")

    weeks: list[ContributionWeek] = []
    for raw_week in raw_weeks:
        if not isinstance(raw_week, Mapping):
            raise ValueError("Each contribution week must be an object")
        start = parse_iso_date(raw_week.get("start"))
        count = raw_week.get("count")
        if start is None:
            raise ValueError("Contribution week start must use YYYY-MM-DD")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("Contribution week count must be a non-negative integer")
        weeks.append(ContributionWeek(start=start, count=count))

    if any(
        current.start >= following.start
        for current, following in zip(weeks, weeks[1:])
    ):
        raise ValueError("Contribution weeks must be strictly chronological")
    return tuple(weeks[-GRAPH_MAX_WEEKS:])


def profile_data_from_mapping(raw_data: Mapping[str, object]) -> GitHubProfileData:
    """Build validated profile data from a deterministic JSON-compatible mapping."""
    return GitHubProfileData(
        stats=validate_stats(raw_data),
        contribution_weeks=validate_contribution_weeks(
            raw_data.get("contribution_weeks")
        ),
        profile_views=resolve_profile_views(raw_data.get("profile_views")),
    )


def fetch_github_contribution_data(
    token: str, start: dt.datetime, end: dt.datetime
) -> tuple[int, tuple[ContributionWeek, ...]]:
    """Fetch the annual total and weekly series in one GitHub GraphQL request."""
    query = """
        query($login: String!, $from: DateTime!, $to: DateTime!) {
          user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
              contributionCalendar {
                totalContributions
                weeks {
                  firstDay
                  contributionDays { date contributionCount }
                }
              }
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
                "to": end.isoformat(),
            },
        },
    )
    if graph.get("errors") and not graph.get("data"):
        raise RuntimeError(f"GitHub GraphQL returned errors: {graph['errors']}")
    try:
        calendar = graph["data"]["user"]["contributionsCollection"][
            "contributionCalendar"
        ]
        total = int(calendar["totalContributions"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(
            "GitHub response is missing the annual contribution total"
        ) from error
    if total < 0:
        raise RuntimeError("GitHub returned a negative contribution total")
    contribution_weeks = aggregate_contributions(calendar.get("weeks"))
    if not contribution_weeks:
        raise RuntimeError("GitHub response is missing the weekly contribution calendar")
    return total, contribution_weeks


def code_lines_from_environment() -> int:
    raw_value = os.environ.get("CODE_LINES")
    if raw_value is None:
        raise RuntimeError(
            "CODE_LINES is required for live stats; run scripts/count_code_lines.py first."
        )
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError("CODE_LINES must be a non-negative integer") from error
    if value < 0:
        raise RuntimeError("CODE_LINES must be a non-negative integer")
    return value


def load_stats(
    token: str,
    code_lines: int | None = None,
    cached_profile_views: int | None = None,
) -> GitHubProfileData:
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
    contributions, contribution_weeks = fetch_github_contribution_data(
        token, start, today
    )
    try:
        stats = {
            "repos": int(user["public_repos"]),
            "commits": int(commit_search["total_count"]),
            "contributions": int(contributions),
            "code_lines": (
                code_lines if code_lines is not None else code_lines_from_environment()
            ),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("GitHub response is missing required numeric stats") from error
    return GitHubProfileData(
        stats=validate_stats(stats),
        contribution_weeks=contribution_weeks,
        profile_views=load_profile_views(cached_profile_views),
    )


def validate_stats(stats: Mapping[str, object]) -> dict[str, int]:
    """Return the supported stats after strict type and range checks."""
    required = ("repos", "commits", "contributions", "code_lines")
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


def section_heading(y: int, label: str) -> str:
    """Build a heading whose terminal rule ends at the shared inner edge."""
    prefix = f"- {label} "
    remaining = INFO_RIGHT - (INFO_X + len(prefix) * TEXT_CHAR_WIDTH)
    rule = "─" * max(1, math.floor(remaining / TEXT_CHAR_WIDTH))
    return tspan(y, f"{prefix}{rule}", "", heading=True)


def format_code_lines(value: int) -> str:
    """Prefer the full SLOC total, compacting only when the chart needs room."""
    if value < 10_000:
        return f"{value:,}"
    if value >= 999_500_000:
        scale, suffix = 1_000_000_000, "B"
    elif value >= 999_500:
        scale, suffix = 1_000_000, "M"
    else:
        scale, suffix = 1_000, "k"
    scaled = value / scale
    precision = 2 if scaled < 10 else 1 if scaled < 100 else 0
    compact = f"{scaled:.{precision}f}"
    if precision:
        compact = compact.rstrip("0").rstrip(".")
    return f"{compact}{suffix}"


def format_profile_views(value: int) -> str:
    """Prefer the full counter while it fits the compact header component."""
    value = resolve_profile_views(value)
    if value < 1_000_000_000:
        return f"{value:,}"
    return format_code_lines(value)


def build_profile_views_svg(profile_views: int) -> str:
    """Render the compact, native Profile Views component in the free header area."""
    profile_views = resolve_profile_views(profile_views)
    display_value = format_profile_views(profile_views)
    return (
        f'<g id="profile-views" role="group" '
        f'aria-label="Profile Views: {display_value}" data-value="{profile_views}">'
        f'<text x="{PROFILE_VIEWS_X}" y="{PROFILE_VIEWS_LABEL_Y}" '
        f'text-anchor="end" class="profile-views-label">Profile Views</text>'
        f'<text x="{PROFILE_VIEWS_X}" y="{PROFILE_VIEWS_VALUE_Y}" '
        f'text-anchor="end" class="profile-views-value">{display_value}</text>'
        '</g>'
    )


def build_metrics_dashboard(stats: Mapping[str, int]) -> str:
    """Present the existing totals in the reserved box beside the chart."""
    cell_width, cell_height = METRICS_WIDTH / 2, METRICS_HEIGHT / 2
    metrics = (
        ("repos", "Repositories"),
        ("contributions", "Contributions"),
        ("commits", "Public Commits"),
        ("code_lines", "Code Lines"),
    )
    cells = []
    for index, (key, label) in enumerate(metrics):
        x = METRICS_X + (index % 2 + 0.5) * cell_width
        y = METRICS_Y + (index // 2) * cell_height
        value = format_code_lines(stats[key])
        cells.append(
            f'<g id="metric-{key}" data-value="{stats[key]}">'
            f'<text x="{x:g}" y="{y + 23:g}" text-anchor="middle" class="value metric-value">{value}</text>'
            f'<text x="{x:g}" y="{y + 39:g}" text-anchor="middle" class="key metric-label">{label}</text>'
            '</g>'
        )
    center_x = METRICS_X + cell_width
    center_y = METRICS_Y + cell_height
    return (
        '<g id="github-metrics" role="group" aria-label="GitHub metrics; contributions over the last 12 months">'
        f'<line class="metric-divider" x1="{center_x:g}" y1="{METRICS_Y + 4}" x2="{center_x:g}" y2="{METRICS_Y + METRICS_HEIGHT - 4}"/>'
        f'<line class="metric-divider" x1="{METRICS_X + 4}" y1="{center_y:g}" x2="{METRICS_X + METRICS_WIDTH - 4}" y2="{center_y:g}"/>'
        + ''.join(cells) + '</g>'
    )


def append_timeline_event(
    events: list[tuple[float, float]], timestamp: float, value: float
) -> None:
    """Append one monotonic SMIL event, replacing an event at the same instant."""
    if events and math.isclose(events[-1][0], timestamp, abs_tol=1e-9):
        events[-1] = (timestamp, value)
    else:
        events.append((timestamp, value))


def typing_schedule() -> tuple[tuple[float, float], ...]:
    """Return each phrase's visible start and delete completion time."""
    schedule: list[tuple[float, float]] = []
    start = 0.0
    for phrase in TYPING_PHRASES:
        active_end = (
            start
            + len(phrase) * TYPING_CHAR_SECONDS
            + TYPING_HOLD_SECONDS
            + len(phrase) * TYPING_DELETE_SECONDS
        )
        schedule.append((start, active_end))
        start = active_end + TYPING_PAUSE_SECONDS
    return tuple(schedule)


def smil_sequence(events: Sequence[tuple[float, float]], duration: float) -> tuple[str, str]:
    values = ";".join(format_coordinate(value) for _, value in events)
    key_times = ";".join(
        "1" if math.isclose(timestamp, duration) else f"{timestamp / duration:.6f}"
        for timestamp, _ in events
    )
    return values, key_times


def build_typing_svg() -> tuple[str, str]:
    """Build a JavaScript-free, looping terminal typing animation."""
    schedule = typing_schedule()
    duration = schedule[-1][1] + TYPING_PAUSE_SECONDS
    definitions: list[str] = []
    animated_groups: list[str] = []

    for index, (phrase, (start, active_end)) in enumerate(
        zip(TYPING_PHRASES, schedule)
    ):
        phrase_width = len(phrase) * TEXT_CHAR_WIDTH
        type_end = start + len(phrase) * TYPING_CHAR_SECONDS
        hold_end = type_end + TYPING_HOLD_SECONDS

        width_events: list[tuple[float, float]] = [(0.0, 0.0)]
        append_timeline_event(width_events, start, 0.0)
        for count in range(1, len(phrase) + 1):
            append_timeline_event(
                width_events, start + count * TYPING_CHAR_SECONDS, count * TEXT_CHAR_WIDTH
            )
        append_timeline_event(width_events, hold_end, phrase_width)
        for removed in range(1, len(phrase) + 1):
            append_timeline_event(
                width_events,
                hold_end + removed * TYPING_DELETE_SECONDS,
                (len(phrase) - removed) * TEXT_CHAR_WIDTH,
            )
        append_timeline_event(width_events, duration, 0.0)
        width_values, width_times = smil_sequence(width_events, duration)

        cursor_events = [
            (timestamp, INFO_X + width + CURSOR_GAP)
            for timestamp, width in width_events
        ]
        cursor_values, cursor_times = smil_sequence(cursor_events, duration)

        opacity_events: list[tuple[float, float]] = [(0.0, 1.0 if index == 0 else 0.0)]
        append_timeline_event(opacity_events, start, 1.0)
        append_timeline_event(opacity_events, active_end, 0.0)
        append_timeline_event(opacity_events, duration, 0.0)
        opacity_values, opacity_times = smil_sequence(opacity_events, duration)

        definitions.append(
            f'''<clipPath id="typing-clip-{index}">
  <rect id="typing-clip-rect-{index}" x="{INFO_X}" y="12" width="{format_coordinate(phrase_width)}" height="23">
    <animate id="typing-width-{index}-animation" attributeName="width" values="{width_values}" keyTimes="{width_times}" calcMode="discrete" dur="{duration:.3f}s" repeatCount="indefinite"/>
  </rect>
</clipPath>'''
        )
        animated_groups.append(
            f'''<g id="typing-sequence-{index}" class="typing-animation" opacity="{1 if index == 0 else 0}" aria-hidden="true">
  <text id="typing-phrase-{index}" x="{INFO_X}" y="{TYPING_Y}" class="text typing-phrase" clip-path="url(#typing-clip-{index})">{html.escape(phrase)}</text>
  <text id="typing-cursor-{index}" x="{format_coordinate(INFO_X + phrase_width + CURSOR_GAP)}" y="{TYPING_Y}" class="typing-cursor">█<animate id="typing-cursor-{index}-animation" attributeName="x" values="{cursor_values}" keyTimes="{cursor_times}" calcMode="discrete" dur="{duration:.3f}s" repeatCount="indefinite"/></text>
  <animate id="typing-opacity-{index}-animation" attributeName="opacity" values="{opacity_values}" keyTimes="{opacity_times}" calcMode="discrete" dur="{duration:.3f}s" repeatCount="indefinite"/>
</g>'''
        )

    first_phrase = TYPING_PHRASES[0]
    static_cursor_x = INFO_X + len(first_phrase) * TEXT_CHAR_WIDTH + CURSOR_GAP
    body = f'''<g id="readme-typing">
{''.join(animated_groups)}
<g id="typing-static" class="typing-static" aria-hidden="true">
  <text id="typing-static-phrase" x="{INFO_X}" y="{TYPING_Y}" class="text typing-phrase">{html.escape(first_phrase)}</text>
  <text id="typing-static-cursor" x="{format_coordinate(static_cursor_x)}" y="{TYPING_Y}" class="typing-cursor">█</text>
</g>
</g>'''
    return "\n".join(definitions), body


def format_coordinate(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def nice_axis_max(value: int) -> int:
    """Round the vertical scale up to a compact 1/2/5-based value."""
    if value <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(value))
    normalized = value / magnitude
    if normalized <= 1:
        multiplier = 1
    elif normalized <= 2:
        multiplier = 2
    elif normalized <= 5:
        multiplier = 5
    else:
        multiplier = 10
    return multiplier * magnitude


def normalize_contribution_points(
    contribution_weeks: Sequence[ContributionWeek],
) -> tuple[list[tuple[float, float]], int]:
    """Map weekly values into the chart's fixed plot box without clipping."""
    plot_x = GRAPH_X + GRAPH_PADDING_LEFT
    plot_y = GRAPH_Y + GRAPH_PADDING_TOP
    plot_width = GRAPH_WIDTH - GRAPH_PADDING_LEFT - GRAPH_PADDING_RIGHT
    plot_height = GRAPH_HEIGHT - GRAPH_PADDING_TOP - GRAPH_PADDING_BOTTOM
    plot_bottom = plot_y + plot_height
    counts = [week.count for week in contribution_weeks]
    axis_max = nice_axis_max(max(counts, default=0))
    if not counts:
        return [(plot_x, plot_bottom), (plot_x + plot_width, plot_bottom)], axis_max
    if len(counts) == 1:
        return [(plot_x, plot_bottom - (counts[0] / axis_max) * plot_height)], axis_max

    points = [
        (
            plot_x + index * plot_width / (len(counts) - 1),
            plot_bottom - (count / axis_max) * plot_height,
        )
        for index, count in enumerate(counts)
    ]
    return points, axis_max


def build_smooth_line_path(points: Sequence[tuple[float, float]]) -> str:
    """Create a bounded cubic path with horizontal tangents at each point."""
    first_x, first_y = points[0]
    commands = [f"M {format_coordinate(first_x)} {format_coordinate(first_y)}"]
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        midpoint = (left_x + right_x) / 2
        commands.append(
            "C "
            f"{format_coordinate(midpoint)} {format_coordinate(left_y)} "
            f"{format_coordinate(midpoint)} {format_coordinate(right_y)} "
            f"{format_coordinate(right_x)} {format_coordinate(right_y)}"
        )
    return " ".join(commands)


def chart_marker_indexes(length: int, maximum: int = 5) -> tuple[int, ...]:
    if length <= 0:
        return ()
    if length <= maximum:
        return tuple(range(length))
    return tuple(
        dict.fromkeys(
            round(index * (length - 1) / (maximum - 1))
            for index in range(maximum)
        )
    )


def build_contribution_chart_svg(
    contribution_weeks: Sequence[ContributionWeek], colors: Mapping[str, str]
) -> tuple[str, str]:
    """Return the chart definitions and body as deterministic native SVG."""
    weeks = tuple(contribution_weeks[-GRAPH_MAX_WEEKS:])
    points, axis_max = normalize_contribution_points(weeks)
    plot_x = GRAPH_X + GRAPH_PADDING_LEFT
    plot_y = GRAPH_Y + GRAPH_PADDING_TOP
    plot_width = GRAPH_WIDTH - GRAPH_PADDING_LEFT - GRAPH_PADDING_RIGHT
    plot_height = GRAPH_HEIGHT - GRAPH_PADDING_TOP - GRAPH_PADDING_BOTTOM
    plot_bottom = plot_y + plot_height
    plot_right = plot_x + plot_width

    line_path = build_smooth_line_path(points)
    first_x, _ = points[0]
    last_x, _ = points[-1]
    area_path = (
        f"M {format_coordinate(first_x)} {format_coordinate(plot_bottom)} "
        f"L {line_path[2:]} "
        f"L {format_coordinate(last_x)} {format_coordinate(plot_bottom)} Z"
    )
    counts = ",".join(str(week.count) for week in weeks)
    period_start = weeks[0].start.isoformat() if weeks else ""

    y_tick_values = sorted({0, axis_max // 2, axis_max})
    grid_lines = []
    for value in y_tick_values:
        y = plot_bottom - (value / axis_max) * plot_height
        grid_lines.append(
            f'<line class="contrib-grid" x1="{format_coordinate(plot_x)}" '
            f'y1="{format_coordinate(y)}" x2="{format_coordinate(plot_right)}" '
            f'y2="{format_coordinate(y)}"/>'
            f'<text class="contrib-axis-label" x="{format_coordinate(plot_x - 5)}" '
            f'y="{format_coordinate(y + 2.5)}" text-anchor="end">{value}</text>'
        )

    x_labels = []
    for index in chart_marker_indexes(len(weeks)):
        x, _ = points[index]
        if index == 0:
            anchor = "start"
        elif index == len(weeks) - 1:
            anchor = "end"
        else:
            anchor = "middle"
        x_labels.append(
            f'<text class="contrib-axis-label" x="{format_coordinate(x)}" '
            f'y="{format_coordinate(GRAPH_Y + GRAPH_HEIGHT - 3)}" '
            f'text-anchor="{anchor}">{weeks[index].start.strftime("%b")}</text>'
        )

    empty_label = ""
    status = "ready" if weeks else "unavailable"
    if not weeks:
        empty_label = (
            f'<text class="contrib-empty" x="{format_coordinate(plot_x + plot_width / 2)}" '
            f'y="{format_coordinate(plot_y + plot_height / 2)}" '
            'text-anchor="middle">data unavailable</text>'
        )

    definitions = f'''<linearGradient id="{GRAPH_GRADIENT_ID}" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="{colors["chart"]}" stop-opacity="0.58"/>
  <stop offset="1" stop-color="{colors["chart"]}" stop-opacity="0.08"/>
</linearGradient>
<clipPath id="{GRAPH_CLIP_ID}">
  <rect x="{format_coordinate(plot_x)}" y="{format_coordinate(plot_y)}" width="{format_coordinate(plot_width)}" height="{format_coordinate(plot_height)}"/>
</clipPath>'''
    body = f'''<g id="{GRAPH_ID}" role="img" aria-labelledby="{GRAPH_TITLE_ID}" data-status="{status}" data-period-start="{period_start}" data-week-counts="{counts}">
<title id="{GRAPH_TITLE_ID}">Weekly GitHub contributions over the last 12 months</title>
<text class="contrib-title" x="{GRAPH_X + GRAPH_PADDING_LEFT}" y="{GRAPH_Y + 9}">contributions · last 12 months</text>
{''.join(grid_lines)}
<g clip-path="url(#{GRAPH_CLIP_ID})">
  <path id="github-contrib-area" class="contrib-area" d="{area_path}"/>
  <path id="github-contrib-line" class="contrib-line" d="{line_path}"/>
</g>
{''.join(x_labels)}
{empty_label}
</g>'''
    return definitions, body


def render(
    theme: str,
    stats: Mapping[str, int],
    ascii_frames: list[list[str]],
    rendered_on: dt.date,
    contribution_weeks: Sequence[ContributionWeek] = (),
    quality: str | QualityPreset = DEFAULT_QUALITY,
    profile_views: int = PROFILE_VIEWS_BASELINE,
) -> str:
    quality = get_quality(quality)
    if theme not in THEMES:
        raise ValueError(f"Unsupported theme: {theme}")
    stats = validate_stats(stats)
    profile_views = resolve_profile_views(profile_views)
    dark = theme == "dark"
    colors = {
        "bg": "#161b22" if dark else "#f6f8fa",
        "text": "#c9d1d9" if dark else "#24292f",
        "key": "#ffa657" if dark else "#bc4c00",
        "value": "#a5d6ff" if dark else "#0969da",
        "muted": "#6e7681" if dark else "#57606a",
        "cursor": "#3fb950" if dark else "#1a7f37",
        "chart": "#3fb950" if dark else "#1a7f37",
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
    motion_duration = quality.animation_duration
    frame_interval = motion_duration / frame_count
    frame_step = 100 / frame_count
    fade_step = frame_step * quality.transition_ratio
    ascii_layers = "\n".join(
        f'<text class="ascii ascii-frame ascii-frame-{frame_index}" '
        f'style="animation-delay:'
        f'{frame_index * frame_interval - motion_duration:.3f}s" '
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
        section_heading(300, "Contact"),
        tspan(320, "Email", "pedrovyg.dev@gmail.com"),
        tspan(340, "LinkedIn", "linkedin.com/in/pedrovygotsky"),
        tspan(360, "Instagram", "instagram.com/pedrovyg"),
        tspan(380, "Discord", "discord.com/users/pedrovyg"),
        section_heading(410, "GitHub Stats"),
    ]
    typing_definitions, header = build_typing_svg()
    chart_definitions, chart_body = build_contribution_chart_svg(
        contribution_weeks, colors
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" role="img" aria-labelledby="{TITLE_ID} {DESCRIPTION_ID}" focusable="false" data-rendered-on="{rendered_on.isoformat()}" data-repositories="{stats['repos']}" data-contributions="{stats['contributions']}" data-public-commits="{stats['commits']}" data-code-lines="{stats['code_lines']}" data-profile-views="{profile_views}" data-ascii-quality="{quality.name}" data-ascii-frame-count="{frame_count}">
<title id="{TITLE_ID}">Pedro Vygotsky Neofetch profile</title>
<desc id="{DESCRIPTION_ID}">Animated fluid diamond ASCII art and terminal typing with the phrases Pedro Vygotsky, Full-Stack &amp; AI Developer, and Building real projects for businesses; Profile Views, development tools, contact details, current public GitHub statistics including Code Lines, and a weekly contribution chart.</desc>
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
  animation: ascii-frame-motion {motion_duration:.1f}s linear infinite;
}}
.ascii-frame-0 {{ opacity: 1; }}
.ascii-stop-top {{ animation: ascii-top-color 9s ease-in-out infinite; }}
.ascii-stop-middle {{ animation: ascii-middle-color 9s ease-in-out infinite; }}
.ascii-stop-bottom {{ animation: ascii-bottom-color 9s ease-in-out infinite; }}
.typing-animation {{ visibility: visible; }}
.typing-static {{ display: none; }}
.typing-phrase {{ letter-spacing: 0; }}
.typing-cursor {{ fill: {colors["cursor"]}; animation: cursor-blink 1.1s step-end infinite; }}
@media (prefers-reduced-motion: reduce) {{
  .ascii-frame {{ animation: none; opacity: 0; }}
  .ascii-frame-0 {{ opacity: 1; }}
  .ascii-stop-top, .ascii-stop-middle, .ascii-stop-bottom {{ animation: none; }}
  .typing-animation {{ display: none; }}
  .typing-static {{ display: inline; }}
  .typing-cursor {{ animation: none; opacity: 1; }}
}}
text {{ font: 14px Consolas, "Liberation Mono", monospace; white-space: pre; }}
.ascii {{
  font-size: {ASCII_FONT_SIZE}px;
  font-family: Consolas, "DejaVu Sans Mono", "Liberation Mono", monospace;
  text-rendering: geometricPrecision;
}}
.text {{ fill: {colors["text"]}; }} .key {{ fill: {colors["key"]}; }}
.value {{ fill: {colors["value"]}; }} .muted {{ fill: {colors["muted"]}; }}
.metric-value {{ font-size: 22px; font-weight: bold; }}
.metric-label {{ font-size: 10px; }}
.metric-divider {{ stroke: {colors["muted"]}; stroke-width: 0.6; opacity: 0.4; }}
.profile-views-label {{ fill: {colors["key"]}; font-size: 9px; }}
.profile-views-value {{ fill: {colors["value"]}; font-size: 18px; font-weight: bold; }}
.contrib-title {{ fill: {colors["text"]}; font-size: 8px; }}
.contrib-axis-label, .contrib-empty {{ fill: {colors["muted"]}; font-size: 7px; }}
.contrib-grid {{ stroke: {colors["muted"]}; stroke-width: 0.6; opacity: 0.32; }}
.contrib-area {{ fill: url(#{GRAPH_GRADIENT_ID}); }}
.contrib-line {{ fill: none; stroke: {colors["chart"]}; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }}
</style>
<defs>
<linearGradient id="ascii-color" x1="0" y1="0" x2="0" y2="1">
  <stop class="ascii-stop-top" offset="0" stop-color="{ascii_green[0]}"/>
  <stop class="ascii-stop-middle" offset="0.5" stop-color="{ascii_green[1]}"/>
  <stop class="ascii-stop-bottom" offset="1" stop-color="{ascii_green[2]}"/>
</linearGradient>
{chart_definitions}
{typing_definitions}
</defs>
<rect id="card-background" x="0.5" y="0.5" width="{CARD_WIDTH - 1}" height="{CARD_HEIGHT - 1}" rx="15" fill="{colors["bg"]}"/>
{ascii_layers}
{header}
{build_profile_views_svg(profile_views)}
<text>{''.join(lines)}</text>
{build_metrics_dashboard(stats)}
{chart_body}
</svg>
'''


def write_assets(
    output_dir: Path,
    ascii_art_path: Path,
    stats: Mapping[str, int],
    rendered_on: dt.date,
    contribution_weeks: Sequence[ContributionWeek] = (),
    quality: str | QualityPreset = DEFAULT_QUALITY,
    profile_views: int = PROFILE_VIEWS_BASELINE,
) -> list[Path]:
    """Render both themes with explicit inputs and stable LF line endings."""
    quality = get_quality(quality)
    frames = read_ascii_frames(ascii_art_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for theme in THEMES:
        output_path = output_dir / f"neofetch-{theme}.svg"
        with output_path.open("w", encoding="utf-8", newline="\n") as output:
            output.write(
                render(
                    theme,
                    stats,
                    frames,
                    rendered_on,
                    contribution_weeks,
                    quality,
                    profile_views,
                )
            )
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
        "--quality",
        choices=tuple(QUALITY_PRESETS),
        default=DEFAULT_QUALITY,
        help="Playback preset matching the generated ASCII source.",
    )
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
        profile_data = profile_data_from_mapping(raw_stats)
    else:
        profile_data = load_stats(os.environ.get("GITHUB_TOKEN", ""))
    write_assets(
        args.output_dir,
        args.ascii_art,
        profile_data.stats,
        args.date,
        profile_data.contribution_weeks,
        args.quality,
        profile_data.profile_views,
    )


if __name__ == "__main__":
    main()
