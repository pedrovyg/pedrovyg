from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_assets import (  # noqa: E402
    parse_stats,
    previous_profile_data,
    resolve_render_date,
)
from generate_ascii_animation import render_animation  # noqa: E402
from update_neofetch import (  # noqa: E402
    GRAPH_HEIGHT,
    GRAPH_PADDING_BOTTOM,
    GRAPH_PADDING_LEFT,
    GRAPH_PADDING_RIGHT,
    GRAPH_PADDING_TOP,
    GRAPH_WIDTH,
    GRAPH_X,
    GRAPH_Y,
    ContributionWeek,
    aggregate_contributions,
    normalize_contribution_points,
    render,
    validate_stats,
)
from validate_svg import IntegrityError, validate_pair, validate_svg  # noqa: E402


VALID_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="850" height="530" viewBox="0 0 850 530" role="img" aria-labelledby="svg-title svg-description" focusable="false">
<title id="svg-title">Test profile card</title>
<desc id="svg-description">Animated ASCII profile card used for integrity tests.</desc>
<style>
@keyframes pulse { 0%, 100% { opacity: 1; } }
.ascii { animation: pulse 1s linear infinite; white-space: pre; }
.ascii-frame-0 { opacity: 1; }
.contrib-area { fill: url(#github-contrib-gradient); }
</style>
<defs>
<linearGradient id="ascii-color"><stop offset="0" stop-color="#fff"/></linearGradient>
<linearGradient id="github-contrib-gradient"><stop offset="0" stop-color="#3fb950"/></linearGradient>
<clipPath id="github-contrib-clip"><rect x="644" y="438" width="184" height="62"/></clipPath>
</defs>
<text class="ascii ascii-frame-0" fill="url(#ascii-color)" xml:space="preserve"><tspan x="0" y="10">  ◆ </tspan></text>
<g id="github-contrib-chart" role="img" aria-labelledby="github-contrib-title" data-status="unavailable" data-period-start="" data-week-counts="">
<title id="github-contrib-title">Weekly GitHub contributions over the last 12 months</title>
<g clip-path="url(#github-contrib-clip)">
<path id="github-contrib-area" class="contrib-area" d="M 644 500 L 828 500 Z"/>
<path id="github-contrib-line" d="M 644 500 L 828 500"/>
</g>
</g>
</svg>
"""


class AssetIntegrityTests(unittest.TestCase):
    def write_fixture(self, directory: Path, name: str, content: str) -> Path:
        path = directory / name
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def test_ascii_generator_is_deterministic(self) -> None:
        first = render_animation()
        second = render_animation()
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))
        self.assertNotIn("\r", first)

    def test_contribution_days_are_aggregated_into_recent_52_weeks(self) -> None:
        first_day = dt.date(2025, 8, 31)
        raw_weeks = []
        for week_index in range(53):
            week_start = first_day + dt.timedelta(days=week_index * 7)
            raw_weeks.append(
                {
                    "firstDay": week_start.isoformat(),
                    "contributionDays": [
                        {
                            "date": (week_start + dt.timedelta(days=day)).isoformat(),
                            "contributionCount": week_index if day == 0 else 0,
                        }
                        for day in range(7)
                    ],
                }
            )

        weeks = aggregate_contributions(raw_weeks)
        self.assertEqual(len(weeks), 52)
        self.assertEqual(
            weeks[0], ContributionWeek(first_day + dt.timedelta(days=7), 1)
        )
        self.assertEqual(weeks[-1].count, 52)

    def test_contribution_points_stay_inside_the_plot_box(self) -> None:
        start = dt.date(2025, 9, 7)
        weeks = tuple(
            ContributionWeek(start + dt.timedelta(days=index * 7), count)
            for index, count in enumerate((0, 3, 11, 2, 7))
        )
        points, axis_max = normalize_contribution_points(weeks)
        plot_left = GRAPH_X + GRAPH_PADDING_LEFT
        plot_right = GRAPH_X + GRAPH_WIDTH - GRAPH_PADDING_RIGHT
        plot_top = GRAPH_Y + GRAPH_PADDING_TOP
        plot_bottom = GRAPH_Y + GRAPH_HEIGHT - GRAPH_PADDING_BOTTOM

        self.assertGreaterEqual(axis_max, 11)
        self.assertTrue(all(plot_left <= x <= plot_right for x, _ in points))
        self.assertTrue(all(plot_top <= y <= plot_bottom for _, y in points))

    def test_render_includes_native_accessible_contribution_chart(self) -> None:
        start = dt.date(2025, 9, 7)
        weeks = tuple(
            ContributionWeek(start + dt.timedelta(days=index * 7), index % 8)
            for index in range(52)
        )
        svg = render(
            "dark",
            {"repos": 19, "commits": 153, "contributions": 159},
            [[" ◆ "]],
            dt.date(2026, 9, 8),
            weeks,
        )
        root = ET.fromstring(svg)
        elements = {element.attrib.get("id"): element for element in root.iter()}

        self.assertEqual(elements["github-contrib-chart"].attrib["role"], "img")
        self.assertEqual(
            elements["github-contrib-chart"].attrib["data-period-start"],
            start.isoformat(),
        )
        self.assertEqual(
            len(elements["github-contrib-chart"].attrib["data-week-counts"].split(",")),
            52,
        )
        self.assertTrue(elements["github-contrib-area"].attrib["d"])
        self.assertTrue(elements["github-contrib-line"].attrib["d"])

    def test_empty_contribution_series_uses_safe_chart_fallback(self) -> None:
        svg = render(
            "dark",
            {"repos": 19, "commits": 153, "contributions": 159},
            [[" ◆ "]],
            dt.date(2026, 9, 8),
        )
        root = ET.fromstring(svg)
        chart = next(
            element
            for element in root.iter()
            if element.attrib.get("id") == "github-contrib-chart"
        )
        self.assertEqual(chart.attrib["data-status"], "unavailable")
        self.assertEqual(chart.attrib["data-week-counts"], "")

    def test_valid_svg_and_exact_ascii_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            svg = self.write_fixture(directory, "valid.svg", VALID_SVG)
            source = self.write_fixture(directory, "ascii.txt", "  ◆ \n")
            validate_svg(svg, source)

    def test_broken_url_reference_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            broken = VALID_SVG.replace('id="ascii-color"', 'id="renamed-color"')
            svg = self.write_fixture(directory, "broken.svg", broken)
            with self.assertRaises(IntegrityError):
                validate_svg(svg)

    def test_changed_ascii_character_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            svg = self.write_fixture(directory, "valid.svg", VALID_SVG)
            changed_source = self.write_fixture(directory, "ascii.txt", "  ◇ \n")
            with self.assertRaises(IntegrityError):
                validate_svg(svg, changed_source)

    def test_missing_animation_keyframe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            broken = VALID_SVG.replace("@keyframes pulse", "@keyframes renamed")
            svg = self.write_fixture(directory, "broken.svg", broken)
            with self.assertRaises(IntegrityError):
                validate_svg(svg)

    def test_before_after_animation_change_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            before = self.write_fixture(directory, "before.svg", VALID_SVG)
            after = self.write_fixture(
                directory, "after.svg", VALID_SVG.replace("pulse 1s", "pulse 2s")
            )
            source = self.write_fixture(directory, "ascii.txt", "  ◆ \n")
            with self.assertRaises(IntegrityError):
                validate_pair(before, after, source)

    def test_before_after_accessible_description_change_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            before = self.write_fixture(directory, "before.svg", VALID_SVG)
            after = self.write_fixture(
                directory,
                "after.svg",
                VALID_SVG.replace("integrity tests", "changed integrity tests"),
            )
            source = self.write_fixture(directory, "ascii.txt", "  ◆ \n")
            with self.assertRaises(IntegrityError):
                validate_pair(before, after, source)

    def test_stats_reject_boolean_and_negative_values(self) -> None:
        with self.assertRaises(ValueError):
            validate_stats({"repos": True, "commits": 1, "contributions": 1})
        with self.assertRaises(ValueError):
            validate_stats({"repos": 1, "commits": -1, "contributions": 1})

    def test_api_failure_reuses_last_embedded_profile_data(self) -> None:
        stats = {"repos": 19, "commits": 153, "contributions": 159}
        weeks = (
            ContributionWeek(dt.date(2026, 8, 23), 4),
            ContributionWeek(dt.date(2026, 8, 30), 7),
        )
        with tempfile.TemporaryDirectory() as temporary:
            card = Path(temporary) / "card.svg"
            card.write_text(
                render("dark", stats, [[" ◆ "]], dt.date(2026, 9, 8), weeks),
                encoding="utf-8",
                newline="\n",
            )
            cached = previous_profile_data(card)
            self.assertIsNotNone(cached)
            self.assertEqual(cached.stats, stats)
            self.assertEqual(cached.contribution_weeks, weeks)
            with patch("build_assets.load_stats", side_effect=RuntimeError("offline")):
                self.assertEqual(parse_stats(None, card), cached)

    def test_render_date_changes_only_with_public_stats(self) -> None:
        stats = {"repos": 19, "commits": 148, "contributions": 154}
        previous_date = dt.date(2026, 9, 6)
        today = dt.date(2026, 9, 7)
        with tempfile.TemporaryDirectory() as temporary:
            card = Path(temporary) / "card.svg"
            card.write_text(
                render("dark", stats, [[" ◆ "]], previous_date),
                encoding="utf-8",
                newline="\n",
            )
            self.assertEqual(
                resolve_render_date(card, stats, None, today), previous_date
            )
            changed = {**stats, "repos": stats["repos"] + 1}
            self.assertEqual(resolve_render_date(card, changed, None, today), today)
            explicit = dt.date(2026, 1, 2)
            self.assertEqual(
                resolve_render_date(card, stats, explicit, today), explicit
            )


if __name__ == "__main__":
    unittest.main()
