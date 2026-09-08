#!/usr/bin/env python3
"""Build, optimize, validate, and safely promote README profile assets."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from generate_ascii_animation import write_animation
from render_fallbacks import render_fallbacks
from update_neofetch import (
    ContributionWeek,
    GitHubProfileData,
    load_stats,
    parse_date,
    profile_data_from_mapping,
    write_assets,
)
from validate_svg import validate_pair, validate_svg


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILD_DIR = ROOT / ".build" / "neofetch"
PROFILE_DIR = ROOT / "profile"
SVGO_CONFIG = ROOT / "svgo.config.mjs"
THEMES = ("dark", "light")
SVG_NAMESPACE = "http://www.w3.org/2000/svg"


def safe_reset_directory(path: Path) -> None:
    root = ROOT.resolve()
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents:
        raise RuntimeError(f"Refusing to reset unsafe build directory: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def parse_stats(
    stats_json: str | None, current_asset: Path | None = None
) -> GitHubProfileData:
    if stats_json is None:
        try:
            return load_stats(os.environ.get("GITHUB_TOKEN", ""))
        except RuntimeError as error:
            cached = previous_profile_data(current_asset) if current_asset else None
            if cached is None:
                raise
            print(
                f"GitHub API unavailable; using the last valid SVG data: {error}",
                file=sys.stderr,
            )
            return cached
    try:
        raw_stats = json.loads(stats_json)
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid --stats-json: {error}") from error
    if not isinstance(raw_stats, dict):
        raise ValueError("--stats-json must contain a JSON object")
    return profile_data_from_mapping(raw_stats)


def previous_card_values(asset_path: Path) -> dict[str, str]:
    """Read labelled values from the existing card without trusting its layout."""
    if not asset_path.is_file():
        return {}
    try:
        root = ET.fromstring(asset_path.read_bytes())
    except (OSError, ET.ParseError):
        return {}

    values: dict[str, str] = {}
    tspan_tag = f"{{{SVG_NAMESPACE}}}tspan"
    for parent in root.iter():
        children = list(parent)
        for index, child in enumerate(children):
            if child.tag != tspan_tag or "key" not in child.attrib.get("class", "").split():
                continue
            label = child.text or ""
            for candidate in children[index + 1 :]:
                classes = candidate.attrib.get("class", "").split()
                if "key" in classes:
                    break
                if candidate.tag == tspan_tag and "value" in classes:
                    values[label] = candidate.text or ""
                    break
    return values


def previous_contribution_weeks(asset_path: Path) -> tuple[ContributionWeek, ...]:
    """Recover the latest validated weekly series embedded in a generated SVG."""
    if not asset_path.is_file():
        return ()
    try:
        root = ET.fromstring(asset_path.read_bytes())
    except (OSError, ET.ParseError):
        return ()

    chart = next(
        (
            element
            for element in root.iter()
            if element.attrib.get("id") == "github-contrib-chart"
        ),
        None,
    )
    if chart is None:
        return ()
    raw_counts = chart.attrib.get("data-week-counts", "")
    raw_start = chart.attrib.get("data-period-start", "")
    if not raw_counts or not raw_start:
        return ()
    try:
        start = dt.date.fromisoformat(raw_start)
        counts = tuple(int(value) for value in raw_counts.split(","))
    except ValueError:
        return ()
    if len(counts) > 52 or any(value < 0 for value in counts):
        return ()
    return tuple(
        ContributionWeek(start=start + dt.timedelta(days=index * 7), count=count)
        for index, count in enumerate(counts)
    )


def previous_profile_data(asset_path: Path | None) -> GitHubProfileData | None:
    """Load the last public totals and chart data for an API outage fallback."""
    if asset_path is None:
        return None
    values = previous_card_values(asset_path)
    try:
        stats = {
            "repos": int(values["Repositories"].replace(",", "")),
            "commits": int(values["Public commits"].replace(",", "")),
            "contributions": int(values["Contributions (1y)"].replace(",", "")),
        }
    except (KeyError, ValueError):
        return None
    if any(value < 0 for value in stats.values()):
        return None
    return GitHubProfileData(
        stats=stats,
        contribution_weeks=previous_contribution_weeks(asset_path),
    )


def resolve_render_date(
    current_asset: Path,
    stats: dict[str, int],
    requested_date: dt.date | None,
    today: dt.date,
    contribution_weeks: tuple[ContributionWeek, ...] = (),
) -> dt.date:
    """Keep the displayed date stable unless the public statistics changed."""
    if requested_date is not None:
        return requested_date

    values = previous_card_values(current_asset)
    try:
        previous_stats = {
            "repos": int(values["Repositories"].replace(",", "")),
            "commits": int(values["Public commits"].replace(",", "")),
            "contributions": int(values["Contributions (1y)"].replace(",", "")),
        }
        previous_date = dt.date.fromisoformat(values["Updated"])
    except (KeyError, ValueError):
        return today

    previous_weeks = previous_contribution_weeks(current_asset)
    if (
        previous_stats == stats
        and previous_weeks == contribution_weeks
        and previous_date <= today
    ):
        return previous_date
    return today


def svgo_executable() -> Path:
    suffix = ".cmd" if os.name == "nt" else ""
    executable = ROOT / "node_modules" / ".bin" / f"svgo{suffix}"
    if not executable.is_file():
        raise RuntimeError("SVGO is not installed; run `npm ci` first")
    return executable


def optimize_svg(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(svgo_executable()),
            "--config",
            str(SVGO_CONFIG),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--quiet",
        ],
        cwd=ROOT,
        check=True,
    )


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_bytes(source.read_bytes())
    os.replace(temporary, destination)


def build_assets(
    build_dir: Path,
    profile_data: GitHubProfileData,
    rendered_on: dt.date,
    promote: bool,
) -> dict[str, dict[str, int]]:
    safe_reset_directory(build_dir)
    raw_dir = build_dir / "raw"
    optimized_dir = build_dir / "optimized"
    fallback_dir = build_dir / "fallback"
    raw_dir.mkdir(parents=True)
    optimized_dir.mkdir(parents=True)
    fallback_dir.mkdir(parents=True)

    ascii_source = write_animation(raw_dir / "ascii-art.txt")
    raw_svgs = write_assets(
        raw_dir,
        ascii_source,
        profile_data.stats,
        rendered_on,
        profile_data.contribution_weeks,
    )
    for raw_svg in raw_svgs:
        validate_svg(raw_svg, ascii_source)

    optimized_svgs: list[Path] = []
    for theme in THEMES:
        raw_svg = raw_dir / f"neofetch-{theme}.svg"
        optimized_svg = optimized_dir / raw_svg.name
        optimize_svg(raw_svg, optimized_svg)
        validate_pair(raw_svg, optimized_svg, ascii_source)
        optimized_svgs.append(optimized_svg)

    pngs = render_fallbacks(optimized_dir, fallback_dir)

    if promote:
        atomic_copy(ascii_source, PROFILE_DIR / "ascii-art.txt")
        for path in optimized_svgs + pngs:
            atomic_copy(path, PROFILE_DIR / path.name)

    report: dict[str, dict[str, int]] = {}
    for theme in THEMES:
        raw_svg = raw_dir / f"neofetch-{theme}.svg"
        optimized_svg = optimized_dir / raw_svg.name
        png = fallback_dir / f"neofetch-{theme}.png"
        report[theme] = {
            "raw_svg_bytes": raw_svg.stat().st_size,
            "optimized_svg_bytes": optimized_svg.stat().st_size,
            "png_bytes": png.stat().st_size,
        }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    parser.add_argument("--stats-json", help="Inline stats JSON for deterministic tests")
    parser.add_argument(
        "--date",
        type=parse_date,
        help=(
            "Explicit rendering date in YYYY-MM-DD format. By default, the "
            "existing date is retained until public statistics change."
        ),
    )
    parser.add_argument(
        "--no-promote",
        action="store_true",
        help="Validate the pipeline without replacing tracked profile assets.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    current_asset = PROFILE_DIR / "neofetch-dark.svg"
    profile_data = parse_stats(args.stats_json, current_asset)
    today = dt.datetime.now(dt.timezone.utc).date()
    rendered_on = resolve_render_date(
        current_asset,
        profile_data.stats,
        args.date,
        today,
        profile_data.contribution_weeks,
    )
    report = build_assets(
        args.build_dir, profile_data, rendered_on, not args.no_promote
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
