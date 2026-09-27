#!/usr/bin/env python3
"""Generate the independent About, technology, and network profile cards."""

from __future__ import annotations

import argparse
import copy
import html
import re
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "assets" / "about-icons"
DEFAULT_OUTPUT_DIR = ROOT / "profile"
DEFAULT_README = ROOT / "README.md"
CARD_WIDTH = 850
PADDING = 33
TILE_WIDTH = 100
TILE_HEIGHT = 80
TILE_GAP = 14
TILE_COLUMNS = 7
ICON_SIZE = 44
SECTION_GAP = 38
NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)


@dataclass(frozen=True)
class Item:
    name: str
    asset: str
    href: str


@dataclass(frozen=True)
class Category:
    name: str
    items: tuple[Item, ...]


ABOUT_TEXT = (
    "Hello, my name is Pedro. I'm a software developer with over three years "
    "of experience, focusing on front-end development while continuously "
    "expanding my skills across the full-stack ecosystem through back-end "
    "technologies.",
    "I am currently pursuing a bachelor's degree in Computer Science and "
    "dedicate much of my time to programming, studying, and building new projects.",
    "I am passionate about technology and education; outside of development, "
    "I also have a keen interest in fitness, cinema, and music.",
)

TECHNOLOGIES = (
    Category(
        "Front-End",
        (
            Item("HTML5", "html.svg", "https://developer.mozilla.org/en-US/docs/Web/HTML"),
            Item("CSS3", "css.svg", "https://developer.mozilla.org/en-US/docs/Web/CSS"),
            Item("JavaScript", "javascript.svg", "https://developer.mozilla.org/en-US/docs/Web/JavaScript"),
            Item("TypeScript", "typescript.svg", "https://www.typescriptlang.org/download/"),
            Item("React", "react.svg", "https://react.dev/"),
        ),
    ),
    Category(
        "Design",
        (
            Item("Figma", "figma.svg", "https://www.figma.com/downloads/"),
            Item("Framer", "framer.svg", "https://www.framer.com/"),
        ),
    ),
    Category(
        "Back-End & Programming",
        (
            Item("Java", "java.svg", "https://www.oracle.com/java/technologies/downloads/"),
            Item("Python", "python.svg", "https://www.python.org/downloads/"),
            Item("Spring Boot", "spring-boot.svg", "https://spring.io/projects/spring-boot"),
            Item("Node.js", "nodejs.svg", "https://nodejs.org/en/download"),
            Item("Apache Maven", "apache-maven.svg", "https://maven.apache.org/download.cgi"),
            Item("Gradle", "gradle.svg", "https://gradle.org/install/"),
            Item("REST API (OpenAPI and Swagger)", "swagger.svg", "https://swagger.io/"),
        ),
    ),
    Category(
        "Development Tools",
        (
            Item("Git", "git.svg", "https://git-scm.com/downloads"),
            Item("GitHub", "github.svg", "https://github.com/"),
            Item("Docker", "docker.svg", "https://www.docker.com/products/docker-desktop/"),
            Item("n8n", "n8n.svg", "https://n8n.io/"),
            Item("Bash", "bash.svg", "https://www.gnu.org/software/bash/"),
            Item("Hostinger", "hostinger.svg", "https://www.hostinger.com/"),
            Item("Vercel", "vercel.svg", "https://vercel.com/"),
            Item("Visual Studio Code", "vscode.svg", "https://code.visualstudio.com/download"),
            Item("IntelliJ IDEA", "intellij-idea.svg", "https://www.jetbrains.com/idea/download/"),
            Item("Codex", "codex.svg", "https://openai.com/codex/"),
            Item("Claude Code", "claude-code.svg", "https://claude.com/product/claude-code"),
            Item("Google AI Studio", "google-ai-studio.svg", "https://aistudio.google.com/"),
        ),
    ),
)

NETWORK = (
    Item(
        "Gmail",
        "gmail-badge.svg",
        "https://mail.google.com/mail/?view=cm&fs=1&to=pedrovyg.dev%40gmail.com",
    ),
    Item("LinkedIn", "linkedin-badge.svg", "https://www.linkedin.com/in/pedrovygotsky"),
    Item("Instagram", "instagram-badge.svg", "https://www.instagram.com/pedrovyg/"),
    Item("WhatsApp", "whatsapp-badge.svg", "https://wa.me/5581999367665"),
    Item("Discord", "discord-badge.svg", "https://discord.com/users/1472784954671890453"),
)

THEMES = {
    "dark": {
        "background": "#0d1117",
        "surface": "#161b22",
        "border": "#30363d",
        "title": "#f0f6fc",
        "text": "#c9d1d9",
        "muted": "#8b949e",
        "accent": "#58a6ff",
        "key": "#f0883e",
        "rule": "#30363d",
    },
    "light": {
        "background": "#ffffff",
        "surface": "#f6f8fa",
        "border": "#d0d7de",
        "title": "#24292f",
        "text": "#57606a",
        "muted": "#6e7781",
        "accent": "#0969da",
        "key": "#bc4c00",
        "rule": "#d0d7de",
    },
}


def local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def asset_path(item: Item) -> Path:
    return ASSET_DIR / item.asset


def asset_view_box(root: ET.Element) -> tuple[float, float, float, float]:
    raw = root.attrib.get("viewBox")
    if raw:
        parts = raw.replace(",", " ").split()
        if len(parts) == 4:
            try:
                return tuple(float(part) for part in parts)  # type: ignore[return-value]
            except ValueError:
                pass
    width = float(re.sub(r"[^0-9.]", "", root.attrib.get("width", "0")) or 0)
    height = float(re.sub(r"[^0-9.]", "", root.attrib.get("height", "0")) or 0)
    if width > 0 and height > 0:
        return (0.0, 0.0, width, height)
    raise ValueError("Asset is missing a usable viewBox")


def prefix_ids(root: ET.Element, prefix: str) -> None:
    ids: dict[str, str] = {}
    seen: dict[str, int] = {}
    for element in root.iter():
        if "id" in element.attrib:
            original = element.attrib["id"]
            occurrence = seen.get(original, 0)
            renamed = f"{prefix}-{original}-{occurrence}"
            seen[original] = occurrence + 1
            ids.setdefault(original, renamed)
            element.attrib["id"] = renamed
    for element in root.iter():
        for name, value in tuple(element.attrib.items()):
            for original, renamed in ids.items():
                value = value.replace(f"url(#{original})", f"url(#{renamed})")
                if value == f"#{original}":
                    value = f"#{renamed}"
            element.attrib[name] = value


def embedded_asset(item: Item, x: float, y: float, width: float, height: float, prefix: str) -> str:
    path = asset_path(item)
    if not path.is_file():
        raise FileNotFoundError(f"Missing vendored icon: {path}")
    root = copy.deepcopy(ET.fromstring(path.read_bytes()))
    asset_view_box(root)
    prefix_ids(root, prefix)
    if item.asset == "figma.svg":
        # The source clipPath renders inconsistently in nested SVGs on light backgrounds.
        # Its bounds contain every Figma path, so dropping it preserves the original mark.
        for element in root.iter():
            element.attrib.pop("clip-path", None)
    root.attrib.update(
        {
            "x": f"{x:.1f}",
            "y": f"{y:.1f}",
            "width": f"{width:.1f}",
            "height": f"{height:.1f}",
            "preserveAspectRatio": "xMidYMid meet",
            "data-asset": item.asset,
        }
    )
    return ET.tostring(root, encoding="unicode", short_empty_elements=True)


def compact_label(value: str) -> str:
    return {
        "REST API (OpenAPI and Swagger)": "REST API",
        "Visual Studio Code": "VS Code",
        "Google AI Studio": "Google AI",
    }.get(value, value)


def wrap_about_text() -> tuple[str, ...]:
    lines: list[str] = []
    for paragraph in ABOUT_TEXT:
        lines.extend(textwrap.wrap(paragraph, width=93, break_long_words=False))
    return tuple(lines)


def section_header(title: str, y: float, colors: dict[str, str]) -> str:
    line_x = PADDING + 180
    return f'''<g class="section-header">
  <text x="{PADDING}" y="{y:.1f}" class="section-title">{html.escape(title)}</text>
  <line x1="{line_x}" y1="{y - 5:.1f}" x2="{CARD_WIDTH - PADDING}" y2="{y - 5:.1f}" class="section-rule"/>
</g>'''


def technology_tile(item: Item, x: float, y: float, colors: dict[str, str], index: int) -> str:
    label = compact_label(item.name)
    font_size = 8 if len(label) > 13 else 9
    icon_x = x + (TILE_WIDTH - ICON_SIZE) / 2
    return f'''<g class="technology-item" data-icon="{html.escape(item.name)}">
  <rect x="{x:.1f}" y="{y:.1f}" width="{TILE_WIDTH}" height="{TILE_HEIGHT}" rx="6" class="tech-tile"/>
  {embedded_asset(item, icon_x, y + 9, ICON_SIZE, ICON_SIZE, f"technology-{index}")}
  <text x="{x + TILE_WIDTH / 2:.1f}" y="{y + 69:.1f}" class="tech-label" font-size="{font_size}" text-anchor="middle">{html.escape(label)}</text>
</g>'''


def network_badges(y: float) -> str:
    dimensions: list[tuple[Item, float, float]] = []
    for item in NETWORK:
        root = ET.fromstring(asset_path(item).read_bytes())
        _, _, width, height = asset_view_box(root)
        dimensions.append((item, width, height))
    gap = 11
    total = sum(width for _, width, _ in dimensions) + gap * (len(dimensions) - 1)
    x = (CARD_WIDTH - total) / 2
    parts = ['<g id="network-badges" aria-label="Pedro Vygotsky network links">']
    for index, (item, width, height) in enumerate(dimensions):
        parts.append(
            f'<g data-network="{html.escape(item.name)}">'
            + embedded_asset(item, x, y, width, height, f"network-{index}")
            + "</g>"
        )
        x += width + gap
    parts.append("</g>")
    return "\n".join(parts)


def render(theme: str) -> str:
    if theme not in THEMES:
        raise ValueError(f"Unsupported theme: {theme}")
    colors = THEMES[theme]
    about_lines = wrap_about_text()
    y = 48.0
    body_y = 86.0
    about_body = "\n".join(
        f'<text x="{PADDING}" y="{body_y + index * 22:.1f}" class="about-copy">{html.escape(line)}</text>'
        for index, line in enumerate(about_lines)
    )
    y = body_y + len(about_lines) * 22 + SECTION_GAP
    technology_header = section_header("Technologies & Tools", y, colors)
    y += 42
    categories: list[str] = []
    icon_index = 0
    for category in TECHNOLOGIES:
        categories.append(
            f'<text x="{PADDING}" y="{y:.1f}" class="category-title">{html.escape(category.name)}</text>'
        )
        y += 14
        rows = (len(category.items) + TILE_COLUMNS - 1) // TILE_COLUMNS
        for item_index, item in enumerate(category.items):
            row, column = divmod(item_index, TILE_COLUMNS)
            x = PADDING + column * (TILE_WIDTH + TILE_GAP)
            tile_y = y + row * (TILE_HEIGHT + 10)
            categories.append(technology_tile(item, x, tile_y, colors, icon_index))
            icon_index += 1
        y += rows * TILE_HEIGHT + (rows - 1) * 10 + 38

    network_header = section_header("Network", y, colors)
    network_y = y + 23
    card_height = int(network_y + 58)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="{NS}" width="{CARD_WIDTH}" height="{card_height}" viewBox="0 0 {CARD_WIDTH} {card_height}" role="img" aria-labelledby="about-card-title about-card-description" focusable="false" data-card="developer-profile" data-theme="{theme}">
<title id="about-card-title">Pedro Vygotsky developer profile</title>
<desc id="about-card-description">About Pedro Vygotsky, selected technologies and tools, and network channels. Interactive destinations are provided in the README link index because this SVG is rendered as an image on GitHub.</desc>
<style>
  text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; letter-spacing: 0; }}
  .section-title {{ fill: {colors["title"]}; font-size: 19px; font-weight: 700; }}
  .section-rule {{ stroke: {colors["rule"]}; stroke-width: 1; }}
  .about-copy {{ fill: {colors["text"]}; font-size: 14px; }}
  .category-title {{ fill: {colors["key"]}; font-size: 13px; font-weight: 700; }}
  .tech-tile {{ fill: {colors["surface"]}; stroke: {colors["border"]}; stroke-width: 1; }}
  .tech-label {{ fill: {colors["muted"]}; font-weight: 600; }}
</style>
<rect id="about-card-background" x="0.5" y="0.5" width="{CARD_WIDTH - 1}" height="{card_height - 1}" rx="8" fill="{colors["background"]}" stroke="{colors["border"]}"/>
<rect x="1" y="1" width="{CARD_WIDTH - 2}" height="4" rx="2" fill="{colors["accent"]}"/>
{section_header("About Me", 48, colors)}
{about_body}
{technology_header}
{''.join(categories)}
{network_header}
{network_badges(network_y)}
</svg>
'''


def link_index_markdown() -> str:
    rows = ["<!-- about-card-links:start -->", "<details>", "<summary>Technology &amp; Network links</summary>", ""]
    for category in TECHNOLOGIES:
        links = " · ".join(f'[{item.name}]({item.href})' for item in category.items)
        rows.extend((f"**{category.name}:** {links}", ""))
    rows.append("**Network:** " + " · ".join(f'[{item.name}]({item.href})' for item in NETWORK))
    rows.extend(("", "</details>", "<!-- about-card-links:end -->"))
    return "\n".join(rows)


def update_readme(readme_path: Path) -> None:
    source = readme_path.read_text(encoding="utf-8")
    start = "<!-- about-card-links:start -->"
    end = "<!-- about-card-links:end -->"
    replacement = link_index_markdown()
    if start in source and end in source:
        before, rest = source.split(start, 1)
        _, after = rest.split(end, 1)
        source = before.rstrip() + "\n\n" + replacement + after
    else:
        source = source.rstrip() + "\n\n" + replacement + "\n"
    readme_path.write_text(source, encoding="utf-8", newline="\n")


def write_assets(output_dir: Path, include_png: bool = True) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for theme in THEMES:
        svg = render(theme)
        svg_path = output_dir / f"about-{theme}.svg"
        svg_path.write_text(svg, encoding="utf-8", newline="\n")
        outputs.append(svg_path)
        if include_png:
            from cairosvg import svg2png

            png_path = output_dir / f"about-{theme}.png"
            svg2png(bytestring=svg.encode("utf-8"), write_to=str(png_path))
            outputs.append(png_path)
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-png", action="store_true", help="Generate SVG assets only.")
    parser.add_argument("--write-readme", action="store_true", help="Refresh the generated link index.")
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for output in write_assets(args.output_dir, include_png=not args.no_png):
        print(output)
    if args.write_readme:
        update_readme(args.readme)


if __name__ == "__main__":
    main()
