#!/usr/bin/env python3
"""Render and validate static PNG fallbacks for the animated profile SVGs."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import cairosvg


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EXPECTED_WIDTH = 850
EXPECTED_HEIGHT = 530
THEMES = ("dark", "light")


class PngValidationError(RuntimeError):
    """Raised when a generated PNG fallback is invalid."""


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 33 or not data.startswith(PNG_SIGNATURE):
        raise PngValidationError(f"Invalid or empty PNG: {path}")
    if data[12:16] != b"IHDR":
        raise PngValidationError(f"PNG is missing IHDR: {path}")
    return struct.unpack(">II", data[16:24])


def validate_png(path: Path) -> None:
    dimensions = png_dimensions(path)
    expected = (EXPECTED_WIDTH, EXPECTED_HEIGHT)
    if dimensions != expected:
        raise PngValidationError(
            f"Unexpected PNG dimensions for {path}: {dimensions}, expected {expected}"
        )


def render_png(svg_path: Path, png_path: Path) -> Path:
    """Render the SVG's deterministic first frame as a same-size PNG."""
    svg_bytes = svg_path.read_bytes()
    if not svg_bytes:
        raise PngValidationError(f"Cannot render an empty SVG: {svg_path}")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    png_bytes = cairosvg.svg2png(
        bytestring=svg_bytes,
        output_width=EXPECTED_WIDTH,
        output_height=EXPECTED_HEIGHT,
    )
    png_path.write_bytes(png_bytes)
    validate_png(png_path)
    return png_path


def render_fallbacks(input_dir: Path, output_dir: Path) -> list[Path]:
    outputs: list[Path] = []
    for theme in THEMES:
        outputs.append(
            render_png(
                input_dir / f"neofetch-{theme}.svg",
                output_dir / f"neofetch-{theme}.png",
            )
        )
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in render_fallbacks(args.input_dir, args.output_dir):
        print(f"Rendered PNG fallback: {path}")


if __name__ == "__main__":
    try:
        main()
    except PngValidationError as error:
        raise SystemExit(f"PNG fallback validation failed: {error}") from error
