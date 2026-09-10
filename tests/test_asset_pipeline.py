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
from count_code_lines import (  # noqa: E402
    Repository,
    cached_count,
    calculate_code_lines,
    parse_cloc_json,
    repository_from_api,
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
    format_code_lines,
    normalize_contribution_points,
    render,
    section_heading,
    typing_schedule,
    validate_stats,
)
from validate_svg import IntegrityError, validate_pair, validate_svg  # noqa: E402


FIXTURE_STATS = {
    "repos": 19,
    "commits": 157,
    "contributions": 162,
    "code_lines": 24_680,
}
VALID_SVG = render(
    "dark", FIXTURE_STATS, [["  ◆ "]], dt.date(2026, 9, 8)
)


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
            FIXTURE_STATS,
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
            FIXTURE_STATS,
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
            broken = VALID_SVG.replace(
                "@keyframes ascii-frame-motion", "@keyframes renamed"
            )
            svg = self.write_fixture(directory, "broken.svg", broken)
            with self.assertRaises(IntegrityError):
                validate_svg(svg)

    def test_before_after_animation_change_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            before = self.write_fixture(directory, "before.svg", VALID_SVG)
            after = self.write_fixture(
                directory,
                "after.svg",
                VALID_SVG.replace("cursor-blink 1.1s", "cursor-blink 2.2s"),
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
                VALID_SVG.replace(
                    "development tools, contact details",
                    "changed development tools, contact details",
                ),
            )
            source = self.write_fixture(directory, "ascii.txt", "  ◆ \n")
            with self.assertRaises(IntegrityError):
                validate_pair(before, after, source)

    def test_stats_reject_boolean_and_negative_values(self) -> None:
        with self.assertRaises(ValueError):
            validate_stats(
                {"repos": True, "commits": 1, "contributions": 1, "code_lines": 1}
            )
        with self.assertRaises(ValueError):
            validate_stats(
                {"repos": 1, "commits": -1, "contributions": 1, "code_lines": 1}
            )

    def test_embedded_profile_data_is_recoverable_but_live_failure_is_explicit(self) -> None:
        stats = FIXTURE_STATS.copy()
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
                with self.assertRaises(RuntimeError):
                    parse_stats(None)

    def test_render_date_changes_only_with_public_stats(self) -> None:
        stats = {
            "repos": 19,
            "commits": 148,
            "contributions": 154,
            "code_lines": 24_680,
        }
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

    def test_typing_has_exact_phrases_cursor_and_continuous_schedule(self) -> None:
        root = ET.fromstring(VALID_SVG)
        elements = {element.attrib.get("id"): element for element in root.iter()}
        expected = (
            "Pedro Vygotsky",
            "Full-Stack & AI Developer",
            "Building real projects for businesses",
        )
        for index, phrase in enumerate(expected):
            self.assertEqual(elements[f"typing-phrase-{index}"].text, phrase)
            self.assertEqual(elements[f"typing-cursor-{index}"].text, "█")
        schedule = typing_schedule()
        self.assertEqual(len(schedule), 3)
        self.assertEqual(schedule[0][0], 0)
        self.assertTrue(
            all(left[1] < right[0] for left, right in zip(schedule, schedule[1:]))
        )
        self.assertNotIn("pedro@vygotsky", VALID_SVG)

    def test_requested_layout_removes_border_and_updated(self) -> None:
        root = ET.fromstring(VALID_SVG)
        elements = {element.attrib.get("id"): element for element in root.iter()}
        self.assertNotIn("stroke", elements["card-background"].attrib)
        self.assertNotIn("Updated", VALID_SVG)
        self.assertIn("Code Lines", VALID_SVG)
        self.assertGreaterEqual(GRAPH_WIDTH, 247)
        self.assertGreaterEqual(GRAPH_HEIGHT, 112)
        self.assertGreaterEqual(len(section_heading(300, "Contact")), 60)

    def test_code_lines_format_only_compacts_when_space_requires_it(self) -> None:
        self.assertEqual(format_code_lines(1_247), "1,247")
        self.assertEqual(format_code_lines(12_485), "12.5k")
        self.assertEqual(format_code_lines(1_249_351), "1.25M")
        self.assertEqual(format_code_lines(100_000), "100k")
        self.assertEqual(format_code_lines(150_000), "150k")

    def test_dashboard_uses_existing_totals_and_handles_growth(self) -> None:
        for value in (0, 125, 1_247, 100_000, 1_500_000):
            stats = dict.fromkeys(FIXTURE_STATS, value)
            svg = render("dark", stats, [["  ◆ "]], dt.date(2026, 9, 8))
            with tempfile.TemporaryDirectory() as directory:
                validate_svg(self.write_fixture(Path(directory), "card.svg", svg))
            root = ET.fromstring(svg)
            for key in stats:
                cell = next(node for node in root.iter() if node.get("id") == f"metric-{key}")
                self.assertEqual(cell.get("data-value"), str(value))
                self.assertEqual(cell[0].text, format_code_lines(value))
                self.assertEqual(cell[0].get("x"), cell[1].get("x"))
                self.assertLess(float(cell[0].get("y")), float(cell[1].get("y")))

    def test_dashboard_rejects_wrong_values_and_overlap(self) -> None:
        for broken in (
            VALID_SVG.replace('data-value="19"', 'data-value="20"'),
            VALID_SVG.replace('x="407"', 'x="700"'),
            VALID_SVG.replace('>Repositories</text>', '>Wrong label</text>'),
        ):
            self.assertNotEqual(broken, VALID_SVG)
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(IntegrityError):
                    validate_svg(self.write_fixture(Path(directory), "broken.svg", broken))

    def test_repository_filter_accepts_only_owned_public_non_forks(self) -> None:
        base = {
            "full_name": "pedrovyg/project",
            "default_branch": "main",
            "pushed_at": "2026-09-08T12:00:00Z",
            "size": 42,
            "private": False,
            "fork": False,
            "owner": {"login": "pedrovyg"},
        }
        self.assertEqual(
            repository_from_api(base),
            Repository("pedrovyg/project", "main", "2026-09-08T12:00:00Z", 42),
        )
        self.assertIsNone(repository_from_api({**base, "fork": True}))
        self.assertIsNone(repository_from_api({**base, "private": True}))
        self.assertIsNone(
            repository_from_api({**base, "owner": {"login": "someone-else"}})
        )

    def test_cloc_report_and_repository_cache_are_strict(self) -> None:
        repository = Repository(
            "pedrovyg/project", "main", "2026-09-08T12:00:00Z", 42
        )
        report = '{"SUM":{"blank":3,"comment":4,"code":125}}'
        self.assertEqual(parse_cloc_json(report, repository.full_name), 125)
        cached = {
            repository.full_name: {
                "code_lines": 125,
                "default_branch": "main",
                "pushed_at": "2026-09-08T12:00:00Z",
            }
        }
        self.assertEqual(cached_count(repository, cached, "2.10", "2.10"), 125)
        self.assertIsNone(cached_count(repository, cached, "2.08", "2.10"))

    def test_code_lines_cache_avoids_recounting_unchanged_repositories(self) -> None:
        repository = Repository(
            "pedrovyg/project", "main", "2026-09-08T12:00:00Z", 42
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "code-lines.json"
            work = root / "work"
            with (
                patch("count_code_lines.cloc_version", return_value="2.10"),
                patch("count_code_lines.count_repository", return_value=321) as counter,
            ):
                self.assertEqual(
                    calculate_code_lines((repository,), cache, work), 321
                )
                self.assertEqual(
                    calculate_code_lines((repository,), cache, work), 321
                )
            counter.assert_called_once()

    def test_invalid_cloc_report_fails(self) -> None:
        with self.assertRaises(RuntimeError):
            parse_cloc_json('{"SUM":{"code":true}}', "pedrovyg/project")


if __name__ == "__main__":
    unittest.main()
