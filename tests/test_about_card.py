from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_about_card import (
    DEFAULT_README,
    NETWORK,
    TECHNOLOGIES,
    link_index_markdown,
    render,
    write_assets,
)
from validate_about_card import AboutCardIntegrityError, validate_about_card


class AboutCardTests(unittest.TestCase):
    def test_both_themes_are_valid_and_self_contained(self) -> None:
        for theme in ("dark", "light"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / f"about-{theme}.svg"
                path.write_text(render(theme), encoding="utf-8")
                validate_about_card(path)
                root = ET.fromstring(path.read_bytes())
                self.assertEqual(root.attrib["data-theme"], theme)
                self.assertNotIn("https://", path.read_text(encoding="utf-8"))

    def test_every_existing_technology_and_network_link_has_a_link_index_entry(self) -> None:
        index = link_index_markdown()
        for category in TECHNOLOGIES:
            self.assertIn(f"**{category.name}:**", index)
            for item in category.items:
                self.assertIn(f"[{item.name}]({item.href})", index)
        for item in NETWORK:
            self.assertIn(f"[{item.name}]({item.href})", index)

    def test_readme_embeds_the_card_and_exact_link_index_without_legacy_sections(self) -> None:
        readme = DEFAULT_README.read_text(encoding="utf-8")
        self.assertIn("profile/about-dark.svg", readme)
        self.assertIn("profile/about-light.svg", readme)
        self.assertIn(link_index_markdown(), readme)
        self.assertNotIn("## About Me", readme)
        self.assertNotIn("## Technologies & Tools", readme)
        self.assertNotIn("## Network", readme)
        self.assertNotIn("skillicons.dev", readme)
        self.assertNotIn("go-skill-icons", readme)

    def test_generator_writes_svg_and_png_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = write_assets(Path(directory))
            self.assertEqual(len(paths), 4)
            self.assertTrue(all(path.is_file() and path.stat().st_size > 0 for path in paths))
            validate_about_card(Path(directory) / "about-dark.svg")
            validate_about_card(Path(directory) / "about-light.svg")

    def test_validator_rejects_overflow(self) -> None:
        broken = render("dark").replace('width="100" height="80"', 'width="900" height="80"', 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.svg"
            path.write_text(broken, encoding="utf-8")
            with self.assertRaises(AboutCardIntegrityError):
                validate_about_card(path)


if __name__ == "__main__":
    unittest.main()
