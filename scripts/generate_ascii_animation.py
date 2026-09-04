#!/usr/bin/env python3
"""Create Pedro's looping abstract ASCII halftone animation source."""

from __future__ import annotations

import math
from pathlib import Path


WIDTH = 180
HEIGHT = 123
FRAME_COUNT = 24
SEPARATOR = "===FRAME==="
RAMP = " .`':-=+*xX#%@"


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    value = min(1.0, max(0.0, (value - edge0) / (edge1 - edge0)))
    return value * value * (3.0 - 2.0 * value)


def frame_at(index: int) -> list[str]:
    phase = math.tau * index / FRAME_COUNT
    rows: list[str] = []

    for row in range(HEIGHT):
        ny = (row / (HEIGHT - 1)) * 2.0 - 1.0
        chars: list[str] = []

        for col in range(WIDTH):
            nx = (col / (WIDTH - 1)) * 2.0 - 1.0

            # A continuously warped coordinate system creates the fluid motion.
            wx = nx + 0.11 * math.sin(5.2 * ny + phase)
            wx += 0.045 * math.sin(12.0 * ny - phase * 1.7)
            wy = ny + 0.055 * math.sin(5.5 * nx - phase)

            # Three intertwined vertical ribbons, inspired by halftone fabric.
            centers = (
                -0.62 + 0.19 * math.sin(4.3 * wy + phase),
                -0.06 + 0.23 * math.sin(3.6 * wy - phase + 1.4),
                0.55 + 0.20 * math.sin(4.8 * wy + phase + 3.0),
            )
            widths = (
                0.18 + 0.035 * math.sin(3.2 * wy - phase),
                0.22 + 0.040 * math.sin(4.0 * wy + phase + 0.6),
                0.19 + 0.030 * math.sin(3.7 * wy - phase + 2.1),
            )

            ribbon = 0.0
            contour = 0.0
            for ribbon_index, (center, width) in enumerate(zip(centers, widths)):
                distance = abs(wx - center)
                body = math.exp(-((distance / width) ** 4))
                ridge_phase = 38.0 * distance + 6.0 * wy
                ridge_phase += phase * (1.0 if ribbon_index % 2 == 0 else -1.0)
                ridges = 0.38 + 0.62 * (0.5 + 0.5 * math.cos(ridge_phase))
                ribbon = max(ribbon, body * ridges)
                contour = max(contour, body * (0.5 + 0.5 * math.sin(18.0 * wy + ridge_phase)))

            # A soft central membrane connects the ribbons and opens moving voids.
            membrane_shape = math.exp(-((wx / 0.72) ** 6 + (wy / 1.08) ** 8))
            membrane_wave = 0.5 + 0.5 * math.sin(
                17.0 * wx + 8.0 * wy + 2.4 * math.sin(3.2 * wy + phase) - phase
            )
            membrane = membrane_shape * membrane_wave * 0.62

            # Slow elliptical voids prevent the result from becoming a solid block.
            void_x = 0.30 * math.sin(phase + 2.1 * wy)
            void_y = 0.26 * math.cos(phase * 0.5)
            void = math.exp(-(((wx - void_x) / 0.31) ** 2 + ((wy - void_y) / 0.24) ** 2))

            edge_fade = smoothstep(1.02, 0.72, abs(ny))
            edge_fade *= smoothstep(1.04, 0.87, abs(nx))
            density = max(ribbon, membrane, contour * 0.74)
            density *= edge_fade * (1.0 - 0.86 * void)

            # Ordered dithering keeps fine dot texture stable between frames.
            bayer = ((col * 37 + row * 17) % 16) / 15.0
            density = min(1.0, max(0.0, density + (bayer - 0.5) * 0.10))

            if density < 0.16:
                chars.append(" ")
                continue

            normalized = (density - 0.16) / 0.84
            ramp_index = min(len(RAMP) - 1, int(normalized * (len(RAMP) - 1)))
            chars.append(RAMP[ramp_index])

        rows.append("".join(chars).rstrip().ljust(WIDTH))

    return rows


def main() -> None:
    frames = ["\n".join(frame_at(index)) for index in range(FRAME_COUNT)]
    Path("profile/ascii-art.txt").write_text(
        f"\n{SEPARATOR}\n".join(frames) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
