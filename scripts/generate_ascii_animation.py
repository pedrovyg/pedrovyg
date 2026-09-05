#!/usr/bin/env python3
"""Generate Pedro's seamless fluid diamond-halftone animation matrix."""

from __future__ import annotations

import math
from pathlib import Path


WIDTH = 40
HEIGHT = 55
FRAME_COUNT = 72
SEPARATOR = "===FRAME==="
OUTPUT_PATH = Path("profile/ascii-art.txt")

# Ordered 4x4 Bayer matrix. It keeps the bitmap texture spatially stable while
# the continuous density field moves through it.
BAYER_4X4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    value = clamp((value - edge0) / (edge1 - edge0))
    return value * value * (3.0 - 2.0 * value)


def loop_noise(x: float, y: float, phase: float, seed: float) -> float:
    """Periodic multi-scale wave noise with an exact 2π temporal loop."""
    value = 0.0
    weight = 0.0
    amplitude = 1.0

    for octave in range(4):
        frequency = 1.0 + octave * 0.82
        temporal = float((octave % 3) + 1)
        first = math.sin(
            frequency * (2.17 * x + 1.31 * y)
            + temporal * phase
            + seed
            + octave * 0.73
        )
        second = math.cos(
            frequency * (-1.43 * x + 2.61 * y)
            - temporal * phase
            + seed * 1.71
            - octave * 0.41
        )
        value += amplitude * first * second
        weight += amplitude
        amplitude *= 0.52

    return 0.5 + 0.5 * value / weight


def density_at(nx: float, ny: float, phase: float) -> float:
    """Build a looped fluid field using noise-driven coordinate warping."""
    warp_x = loop_noise(nx * 1.18, ny * 1.06, phase, 0.8) - 0.5
    warp_y = loop_noise(nx * 1.04, ny * 1.21, phase, 4.2) - 0.5
    x = nx + warp_x * 0.48 + 0.07 * math.sin(3.4 * ny + phase)
    y = ny + warp_y * 0.38 + 0.05 * math.cos(3.1 * nx - phase)

    broad = loop_noise(x * 1.22, y * 1.08, phase, 8.3)
    medium = loop_noise(x * 2.12, y * 1.86, -phase, 12.7)
    detail = loop_noise(x * 3.65, y * 3.10, phase, 17.9)

    # Folded noise produces cellular ridges; the travelling sine term forms
    # the broad bright/dark waves visible in the reference.
    cellular = 1.0 - abs(2.0 * broad - 1.0)
    travelling_wave = 0.5 + 0.5 * math.sin(
        4.8 * x + 3.2 * y + 3.1 * (medium - 0.5) + phase
    )
    density = broad * 0.44 + medium * 0.22 + detail * 0.08
    density += cellular * 0.12 + travelling_wave * 0.24

    # Two orbiting depressions make regions contract and disperse while still
    # returning exactly to their starting positions at the end of the cycle.
    void_a_x = 0.46 * math.sin(phase)
    void_a_y = 0.38 * math.cos(phase)
    void_b_x = -0.52 * math.cos(phase)
    void_b_y = 0.44 * math.sin(phase)
    void_a = math.exp(-(((x - void_a_x) / 0.42) ** 2 + ((y - void_a_y) / 0.31) ** 2))
    void_b = math.exp(-(((x - void_b_x) / 0.34) ** 2 + ((y - void_b_y) / 0.40) ** 2))
    density -= 0.18 * void_a + 0.13 * void_b

    # Fade the matrix softly at its bounds, leaving the animation layer itself
    # transparent instead of drawing a rectangular background.
    edge = smoothstep(1.06, 0.86, abs(nx))
    edge *= smoothstep(1.06, 0.88, abs(ny))
    return clamp(smoothstep(0.18, 0.86, density) * edge)


def diamond_for(density: float, col: int, row: int) -> str:
    """Quantize density into bitmap-like geometric glyph sizes."""
    threshold = BAYER_4X4[row % 4][col % 4] / 15.0
    level = clamp(density + (threshold - 0.5) * 0.13)

    if level < 0.22:
        return " "
    if level < 0.36:
        return "·"
    if level < 0.52:
        return "⋄"
    if level < 0.76:
        return "◇"
    return "◆"


def frame_at(index: int) -> list[str]:
    phase = math.tau * index / FRAME_COUNT
    rows: list[str] = []

    for row in range(HEIGHT):
        ny = (row / (HEIGHT - 1)) * 2.0 - 1.0
        chars: list[str] = []
        for col in range(WIDTH):
            nx = (col / (WIDTH - 1)) * 2.0 - 1.0
            chars.append(diamond_for(density_at(nx, ny, phase), col, row))
        rows.append("".join(chars).rstrip().ljust(WIDTH))

    return rows


def main() -> None:
    frames = ["\n".join(frame_at(index)) for index in range(FRAME_COUNT)]
    OUTPUT_PATH.write_text(
        f"\n{SEPARATOR}\n".join(frames) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
