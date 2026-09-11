#!/usr/bin/env python3
"""Generate Pedro's seamless fluid diamond-halftone animation matrix."""

from __future__ import annotations

import argparse
import bisect
import math
from dataclasses import dataclass
from pathlib import Path


SEPARATOR = "===FRAME==="
OUTPUT_PATH = Path("profile/ascii-art.txt")
DEFAULT_QUALITY = "balanced"


@dataclass(frozen=True)
class QualityPreset:
    """Generation and playback tuning for one deterministic motion profile."""

    name: str
    width: int
    height: int
    frame_count: int
    animation_duration: float
    transition_ratio: float
    noise_octaves: int
    noise_speed: float
    noise_scale: float
    stagger_amount: float
    hysteresis: float
    dither_strength: float
    glyphs: tuple[str, ...]
    glyph_thresholds: tuple[float, ...]


# Spatial density stays constant across presets. Lower qualities reduce temporal
# and noise detail while retaining the same silhouette, glyphs, and loop speed.
QUALITY_PRESETS = {
    "high": QualityPreset(
        name="high",
        width=40,
        height=55,
        frame_count=90,
        animation_duration=7.2,
        transition_ratio=1.0,
        noise_octaves=4,
        noise_speed=1.0,
        noise_scale=1.0,
        stagger_amount=0.055,
        hysteresis=0.014,
        dither_strength=0.12,
        glyphs=(" ", "·", "⋄", "◇", "◈", "◆"),
        glyph_thresholds=(0.20, 0.34, 0.48, 0.64, 0.80),
    ),
    "balanced": QualityPreset(
        name="balanced",
        width=40,
        height=55,
        frame_count=72,
        animation_duration=7.2,
        transition_ratio=0.92,
        noise_octaves=4,
        noise_speed=1.0,
        noise_scale=1.0,
        stagger_amount=0.050,
        hysteresis=0.018,
        dither_strength=0.12,
        glyphs=(" ", "·", "⋄", "◇", "◈", "◆"),
        glyph_thresholds=(0.20, 0.34, 0.48, 0.64, 0.80),
    ),
    "low": QualityPreset(
        name="low",
        width=40,
        height=55,
        frame_count=48,
        animation_duration=7.2,
        transition_ratio=0.82,
        noise_octaves=3,
        noise_speed=1.0,
        noise_scale=1.0,
        stagger_amount=0.045,
        hysteresis=0.050,
        dither_strength=0.12,
        glyphs=(" ", "·", "⋄", "◇", "◈", "◆"),
        glyph_thresholds=(0.20, 0.34, 0.48, 0.64, 0.80),
    ),
}

# Ordered dithering remains fixed in space; it never injects per-frame noise.
BAYER_4X4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


def get_quality(value: str | QualityPreset = DEFAULT_QUALITY) -> QualityPreset:
    if isinstance(value, QualityPreset):
        return value
    try:
        return QUALITY_PRESETS[value]
    except KeyError as error:
        choices = ", ".join(QUALITY_PRESETS)
        raise ValueError(f"Unknown quality {value!r}; choose one of: {choices}") from error


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    value = clamp((value - edge0) / (edge1 - edge0))
    return value * value * (3.0 - 2.0 * value)


def loop_noise(
    x: float, y: float, phase: float, seed: float, octaves: int
) -> float:
    """Periodic multi-scale wave noise with an exact 2-pi temporal loop."""
    value = 0.0
    weight = 0.0
    amplitude = 1.0

    for octave in range(octaves):
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


def density_at(
    nx: float, ny: float, phase: float, quality: QualityPreset
) -> float:
    """Build a looped fluid field using noise-driven coordinate warping."""
    scale = quality.noise_scale
    phase *= quality.noise_speed
    warp_x = (
        loop_noise(
            nx * 1.18 * scale,
            ny * 1.06 * scale,
            phase,
            0.8,
            quality.noise_octaves,
        )
        - 0.5
    )
    warp_y = (
        loop_noise(
            nx * 1.04 * scale,
            ny * 1.21 * scale,
            phase,
            4.2,
            quality.noise_octaves,
        )
        - 0.5
    )
    x = nx + warp_x * 0.48 + 0.07 * math.sin(3.4 * ny + phase)
    y = ny + warp_y * 0.38 + 0.05 * math.cos(3.1 * nx - phase)

    broad = loop_noise(x * 1.22, y * 1.08, phase, 8.3, quality.noise_octaves)
    medium = loop_noise(x * 2.12, y * 1.86, -phase, 12.7, quality.noise_octaves)
    detail = loop_noise(x * 3.65, y * 3.10, phase, 17.9, quality.noise_octaves)

    cellular = 1.0 - abs(2.0 * broad - 1.0)
    travelling_wave = 0.5 + 0.5 * math.sin(
        4.8 * x + 3.2 * y + 3.1 * (medium - 0.5) + phase
    )
    density = broad * 0.44 + medium * 0.22 + detail * 0.08
    density += cellular * 0.12 + travelling_wave * 0.24

    void_a_x = 0.46 * math.sin(phase)
    void_a_y = 0.38 * math.cos(phase)
    void_b_x = -0.52 * math.cos(phase)
    void_b_y = 0.44 * math.sin(phase)
    void_a = math.exp(-(((x - void_a_x) / 0.42) ** 2 + ((y - void_a_y) / 0.31) ** 2))
    void_b = math.exp(-(((x - void_b_x) / 0.34) ** 2 + ((y - void_b_y) / 0.40) ** 2))
    density -= 0.18 * void_a + 0.13 * void_b

    edge = smoothstep(1.06, 0.86, abs(nx))
    edge *= smoothstep(1.06, 0.88, abs(ny))
    return clamp(smoothstep(0.18, 0.86, density) * edge)


def dithered_level(
    density: float, col: int, row: int, quality: QualityPreset
) -> float:
    """Apply deterministic ordered dithering without frame-to-frame randomness."""
    threshold = BAYER_4X4[row % 4][col % 4] / 15.0
    return clamp(density + (threshold - 0.5) * quality.dither_strength)


def spatial_phase(nx: float, ny: float, amount: float) -> float:
    """Return a low-frequency, spatially coherent per-cell time offset."""
    return amount * (
        0.58 * math.sin(2.4 * nx + 1.7 * ny)
        + 0.42 * math.sin(-1.1 * nx + 2.8 * ny + 1.2)
    )


def quantize_cycle(values: list[float], quality: QualityPreset) -> list[int]:
    """Quantize a closed density loop with hysteresis and a stable seam."""
    thresholds = quality.glyph_thresholds
    state = bisect.bisect_right(thresholds, values[0])
    result = [state] * len(values)

    # The warm-up lap makes frame zero depend on the loop's final state.
    for lap in range(2):
        for index, value in enumerate(values):
            if (
                state < len(thresholds)
                and value >= thresholds[state] + quality.hysteresis
            ):
                state += 1
            elif (
                state > 0
                and value <= thresholds[state - 1] - quality.hysteresis
            ):
                state -= 1
            if lap == 1:
                result[index] = state
    return result


def generate_frames(
    quality: str | QualityPreset = DEFAULT_QUALITY,
) -> list[list[str]]:
    """Generate a coherent loop, retaining temporal state for every cell."""
    preset = get_quality(quality)
    phases = [
        math.tau * index / preset.frame_count for index in range(preset.frame_count)
    ]
    cells = [[0] * (preset.width * preset.height) for _ in phases]

    for row in range(preset.height):
        ny = (row / (preset.height - 1)) * 2.0 - 1.0
        for col in range(preset.width):
            nx = (col / (preset.width - 1)) * 2.0 - 1.0
            offset = spatial_phase(nx, ny, preset.stagger_amount)
            values = [
                dithered_level(
                    density_at(nx, ny, phase + offset, preset), col, row, preset
                )
                for phase in phases
            ]
            for frame_index, state in enumerate(quantize_cycle(values, preset)):
                cells[frame_index][row * preset.width + col] = state

    frames: list[list[str]] = []
    for frame_cells in cells:
        rows = []
        for row in range(preset.height):
            start = row * preset.width
            line = "".join(
                preset.glyphs[level]
                for level in frame_cells[start : start + preset.width]
            )
            rows.append(line.rstrip().ljust(preset.width))
        frames.append(rows)
    return frames


def diamond_for(
    density: float,
    col: int,
    row: int,
    quality: str | QualityPreset = DEFAULT_QUALITY,
) -> str:
    """Quantize one sample; complete animations use temporal hysteresis."""
    preset = get_quality(quality)
    level = dithered_level(density, col, row, preset)
    return preset.glyphs[bisect.bisect_right(preset.glyph_thresholds, level)]


def frame_at(
    index: int, quality: str | QualityPreset = DEFAULT_QUALITY
) -> list[str]:
    preset = get_quality(quality)
    phase = math.tau * index / preset.frame_count
    rows: list[str] = []

    for row in range(preset.height):
        ny = (row / (preset.height - 1)) * 2.0 - 1.0
        chars: list[str] = []
        for col in range(preset.width):
            nx = (col / (preset.width - 1)) * 2.0 - 1.0
            cell_phase = phase + spatial_phase(nx, ny, preset.stagger_amount)
            chars.append(
                diamond_for(density_at(nx, ny, cell_phase, preset), col, row, preset)
            )
        rows.append("".join(chars).rstrip().ljust(preset.width))

    return rows


def render_animation(quality: str | QualityPreset = DEFAULT_QUALITY) -> str:
    """Return the complete deterministic animation source as UTF-8 text."""
    frames = ["\n".join(frame) for frame in generate_frames(quality)]
    return f"\n{SEPARATOR}\n".join(frames) + "\n"


def write_animation(
    output_path: Path = OUTPUT_PATH,
    quality: str | QualityPreset = DEFAULT_QUALITY,
) -> Path:
    """Write the animation without newline or whitespace normalization."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        output.write(render_animation(quality))
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="UTF-8 destination for the generated animation matrix.",
    )
    parser.add_argument(
        "--quality",
        choices=tuple(QUALITY_PRESETS),
        default=DEFAULT_QUALITY,
        help="Generation preset; balanced is recommended for the README.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    write_animation(args.output, args.quality)


if __name__ == "__main__":
    main()
