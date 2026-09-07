from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_assets import resolve_render_date  # noqa: E402
from generate_ascii_animation import render_animation  # noqa: E402
from update_neofetch import render, validate_stats  # noqa: E402
from validate_svg import IntegrityError, validate_pair, validate_svg  # noqa: E402


VALID_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="850" height="530" viewBox="0 0 850 530" role="img" aria-labelledby="svg-title svg-description" focusable="false">
<title id="svg-title">Test profile card</title>
<desc id="svg-description">Animated ASCII profile card used for integrity tests.</desc>
<style>
@keyframes pulse { 0%, 100% { opacity: 1; } }
.ascii { animation: pulse 1s linear infinite; white-space: pre; }
.ascii-frame-0 { opacity: 1; }
</style>
<defs><linearGradient id="ascii-color"><stop offset="0" stop-color="#fff"/></linearGradient></defs>
<text class="ascii ascii-frame-0" fill="url(#ascii-color)" xml:space="preserve"><tspan x="0" y="10">  ◆ </tspan></text>
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
