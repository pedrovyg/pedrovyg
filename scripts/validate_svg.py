#!/usr/bin/env python3
"""Validate generated Neofetch SVGs and reject optimization regressions."""

from __future__ import annotations

import argparse
import datetime as dt
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from generate_ascii_animation import QUALITY_PRESETS, get_quality


SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
EXPECTED_WIDTH = "850"
EXPECTED_HEIGHT = "530"
EXPECTED_VIEWBOX = "0 0 850 530"
ASCII_FRAME_SEPARATOR = "\n===FRAME===\n"
URL_REFERENCE_RE = re.compile(r"url\(\s*['\"]?#([^)'\"\s]+)['\"]?\s*\)")
KEYFRAME_RE = re.compile(r"@(?:-webkit-)?keyframes\s+([A-Za-z_][\w-]*)")
CLASS_SELECTOR_RE = re.compile(r"(?<![\w-])\.([A-Za-z_][\w-]*)")
ANIMATION_DECLARATION_RE = re.compile(
    r"(?<![\w-])animation(?:-name)?\s*:\s*([^;}]+)"
)
ANIMATION_ELEMENTS = {"animate", "animateMotion", "animateTransform", "set"}
PROTECTED_ATTRIBUTES = {
    "role",
    "tabindex",
    "begin",
    "end",
    "dur",
    "repeatCount",
    "attributeName",
    "values",
    "keyTimes",
    "keySplines",
    "calcMode",
    "from",
    "to",
    "by",
    "additive",
    "accumulate",
    "fill",
    "stroke",
    "style",
    "filter",
    "mask",
    "clip-path",
    "focusable",
    XML_SPACE,
}
REQUIRED_CHART_IDS = {
    "github-contrib-gradient",
    "github-contrib-clip",
    "github-contrib-chart",
    "github-contrib-title",
    "github-contrib-area",
    "github-contrib-line",
}
TYPING_PHRASES = (
    "Pedro Vygotsky",
    "Full-Stack & AI Developer",
    "Building real projects for businesses",
)
REQUIRED_TYPING_IDS = {
    "readme-typing",
    "typing-static",
    "typing-static-phrase",
    "typing-static-cursor",
}.union(
    {
        f"typing-{kind}-{index}"
        for index in range(len(TYPING_PHRASES))
        for kind in ("clip", "clip-rect", "sequence", "phrase", "cursor")
    },
    {
        f"typing-{kind}-{index}-animation"
        for index in range(len(TYPING_PHRASES))
        for kind in ("width", "cursor", "opacity")
    },
)


class IntegrityError(RuntimeError):
    """Raised when an SVG violates a rendering or accessibility invariant."""


def local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def read_utf8_bytes(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()
    if not data:
        raise IntegrityError(f"Empty generated file: {path}")
    try:
        return data, data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise IntegrityError(f"File is not valid UTF-8: {path}") from error


def parse_svg(path: Path) -> ET.Element:
    data, _ = read_utf8_bytes(path)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise IntegrityError(f"Invalid XML in {path}: {error}") from error
    if local_name(root.tag) != "svg" or not root.tag.startswith(f"{{{SVG_NAMESPACE}}}"):
        raise IntegrityError(f"Root element is not an SVG in {path}")
    return root


def expected_ascii_frames(source_path: Path) -> tuple[tuple[str, ...], ...]:
    _, source = read_utf8_bytes(source_path)
    if "\r" in source:
        raise IntegrityError(f"ASCII source must use LF line endings: {source_path}")
    if not source.endswith("\n"):
        raise IntegrityError(f"ASCII source must end with exactly one LF: {source_path}")
    body = source[:-1]
    if body.endswith("\n"):
        raise IntegrityError(f"ASCII source has an extra trailing LF: {source_path}")
    return tuple(
        tuple(frame.split("\n")) for frame in body.split(ASCII_FRAME_SEPARATOR)
    )


def style_texts(root: ET.Element) -> tuple[str, ...]:
    # XML serializers may remove only the formatting newline immediately inside
    # <style>.  Ignore that non-semantic boundary whitespace while preserving
    # every CSS token, selector, declaration, class, and keyframe verbatim.
    return tuple(
        (element.text or "").strip("\r\n")
        for element in root.iter()
        if local_name(element.tag) == "style"
    )


def collect_references(root: ET.Element, styles: tuple[str, ...]) -> tuple[str, ...]:
    references: list[str] = []
    for element in root.iter():
        for name, value in element.attrib.items():
            references.extend(URL_REFERENCE_RE.findall(value))
            if local_name(name) == "href" and value.startswith("#"):
                references.append(value[1:])
            if local_name(name) in {"aria-labelledby", "aria-describedby"}:
                references.extend(value.split())
    for css in styles:
        references.extend(URL_REFERENCE_RE.findall(css))
    return tuple(references)


def collect_ascii_frames(root: ET.Element) -> tuple[tuple[str, ...], ...]:
    frames: list[tuple[str, ...]] = []
    frame_indexes: list[int] = []
    for element in root.iter():
        if local_name(element.tag) != "text":
            continue
        classes = element.attrib.get("class", "").split()
        if "ascii" not in classes:
            continue
        frame_class = next(
            (name for name in classes if re.fullmatch(r"ascii-frame-\d+", name)),
            None,
        )
        if frame_class is None:
            raise IntegrityError("ASCII frame is missing its numbered CSS class")
        frame_indexes.append(int(frame_class.rsplit("-", 1)[1]))
        frame_lines = tuple(
            child.text if child.text is not None else ""
            for child in element
            if local_name(child.tag) == "tspan"
        )
        if not frame_lines:
            raise IntegrityError(f"ASCII frame {frame_class} is empty")
        frames.append(frame_lines)
    if frame_indexes != list(range(len(frame_indexes))):
        raise IntegrityError("ASCII frame classes are missing, duplicated, or out of order")
    return tuple(frames)


def collect_other_text(root: ET.Element) -> tuple[tuple[object, ...], ...]:
    result: list[tuple[object, ...]] = []
    for element in root.iter():
        if local_name(element.tag) != "text":
            continue
        if "ascii" in element.attrib.get("class", "").split():
            continue
        result.append(
            (
                element.attrib.get("class", ""),
                element.text,
                tuple(
                    child.text if child.text is not None else ""
                    for child in element
                    if local_name(child.tag) == "tspan"
                ),
            )
        )
    return tuple(result)


def collect_accessible_text(root: ET.Element) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (local_name(element.tag), element.attrib.get("id", ""), element.text or "")
        for element in root.iter()
        if local_name(element.tag) in {"title", "desc"}
    )


def collect_protected_attributes(
    root: ET.Element,
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    protected: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for element in root.iter():
        attributes = tuple(
            sorted(
                (name, value)
                for name, value in element.attrib.items()
                if name in PROTECTED_ATTRIBUTES
                or local_name(name).startswith("aria-")
                or local_name(name).startswith("data-")
            )
        )
        if attributes:
            protected.append((local_name(element.tag), attributes))
    return tuple(protected)


@dataclass(frozen=True)
class SvgSnapshot:
    dimensions: tuple[str | None, str | None, str | None]
    ids: tuple[str, ...]
    references: tuple[str, ...]
    styles: tuple[str, ...]
    classes: tuple[tuple[str, str], ...]
    keyframes: tuple[str, ...]
    animation_declarations: tuple[str, ...]
    animation_elements: tuple[str, ...]
    ascii_frames: tuple[tuple[str, ...], ...]
    other_text: tuple[tuple[object, ...], ...]
    accessible_text: tuple[tuple[str, str, str], ...]
    protected_attributes: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


def snapshot(root: ET.Element) -> SvgSnapshot:
    styles = style_texts(root)
    return SvgSnapshot(
        dimensions=(
            root.attrib.get("width"),
            root.attrib.get("height"),
            root.attrib.get("viewBox"),
        ),
        ids=tuple(element.attrib["id"] for element in root.iter() if "id" in element.attrib),
        references=collect_references(root, styles),
        styles=styles,
        classes=tuple(
            (local_name(element.tag), element.attrib["class"])
            for element in root.iter()
            if "class" in element.attrib
        ),
        keyframes=tuple(name for css in styles for name in KEYFRAME_RE.findall(css)),
        animation_declarations=tuple(
            declaration.strip()
            for css in styles
            for declaration in ANIMATION_DECLARATION_RE.findall(css)
        ),
        animation_elements=tuple(
            local_name(element.tag)
            for element in root.iter()
            if local_name(element.tag) in ANIMATION_ELEMENTS
        ),
        ascii_frames=collect_ascii_frames(root),
        other_text=collect_other_text(root),
        accessible_text=collect_accessible_text(root),
        protected_attributes=collect_protected_attributes(root),
    )


def validate_css(snapshot_data: SvgSnapshot) -> None:
    if not snapshot_data.styles:
        raise IntegrityError("SVG is missing its <style> element")
    css = "\n".join(snapshot_data.styles)
    if not re.search(r"white-space\s*:\s*pre(?:\s*[;}])", css):
        raise IntegrityError("ASCII whitespace requires a CSS white-space: pre rule")
    defined_classes = set(CLASS_SELECTOR_RE.findall(css))
    used_classes = {
        class_name
        for _, class_value in snapshot_data.classes
        for class_name in class_value.split()
    }
    missing_classes = sorted(
        name
        for name in used_classes - defined_classes
        if not re.fullmatch(r"ascii-frame-\d+", name)
    )
    if missing_classes:
        raise IntegrityError(f"CSS classes are used but not defined: {missing_classes}")

    defined_keyframes = set(snapshot_data.keyframes)
    ignored_names = {"none", "initial", "inherit", "unset", "revert", "revert-layer"}
    for declaration in snapshot_data.animation_declarations:
        for animation in declaration.split(","):
            match = re.match(r"\s*([A-Za-z_][\w-]*)", animation)
            if match and match.group(1) not in ignored_names:
                name = match.group(1)
                if name not in defined_keyframes:
                    raise IntegrityError(f"Animation references missing keyframe: {name}")


def validate_accessibility(root: ET.Element, ids: tuple[str, ...]) -> None:
    if root.attrib.get("role") != "img":
        raise IntegrityError('SVG root must declare role="img"')
    labelled_by = root.attrib.get("aria-labelledby", "").split()
    if len(labelled_by) < 2 or any(reference not in ids for reference in labelled_by):
        raise IntegrityError("aria-labelledby must resolve to title and description IDs")
    title = next((element for element in root if local_name(element.tag) == "title"), None)
    description = next((element for element in root if local_name(element.tag) == "desc"), None)
    if title is None or not (title.text or "").strip():
        raise IntegrityError("SVG requires a meaningful <title>")
    if description is None or len((description.text or "").strip()) < 20:
        raise IntegrityError("SVG requires a meaningful <desc>")


def validate_contribution_chart(root: ET.Element, ids: tuple[str, ...]) -> None:
    missing = sorted(REQUIRED_CHART_IDS - set(ids))
    if missing:
        raise IntegrityError(f"Contribution chart is missing required IDs: {missing}")
    chart = next(
        element
        for element in root.iter()
        if element.attrib.get("id") == "github-contrib-chart"
    )
    if chart.attrib.get("role") != "img":
        raise IntegrityError('Contribution chart must declare role="img"')
    if chart.attrib.get("aria-labelledby") != "github-contrib-title":
        raise IntegrityError("Contribution chart title reference is invalid")

    raw_counts = chart.attrib.get("data-week-counts")
    if raw_counts is None:
        raise IntegrityError("Contribution chart is missing its cached weekly data")
    try:
        counts = tuple(int(value) for value in raw_counts.split(",") if value)
    except ValueError as error:
        raise IntegrityError(
            "Contribution chart contains an invalid weekly count"
        ) from error
    if len(counts) > 52 or any(value < 0 for value in counts):
        raise IntegrityError("Contribution chart weekly counts are outside valid bounds")

    period_start = chart.attrib.get("data-period-start", "")
    if counts:
        try:
            dt.date.fromisoformat(period_start)
        except ValueError as error:
            raise IntegrityError(
                "Contribution chart period start must use YYYY-MM-DD"
            ) from error
    elif period_start:
        raise IntegrityError("Empty contribution chart cannot declare a period start")

    for element_id in ("github-contrib-area", "github-contrib-line"):
        element = next(
            candidate
            for candidate in root.iter()
            if candidate.attrib.get("id") == element_id
        )
        if local_name(element.tag) != "path" or not element.attrib.get("d"):
            raise IntegrityError(f"Contribution chart path #{element_id} is invalid")

    clip = next(
        element
        for element in root.iter()
        if element.attrib.get("id") == "github-contrib-clip"
    )
    clip_rect = next(
        (element for element in clip if local_name(element.tag) == "rect"), None
    )
    if clip_rect is None:
        raise IntegrityError("Contribution chart clip path is empty")
    try:
        plot_x = float(clip_rect.attrib["x"])
        plot_y = float(clip_rect.attrib["y"])
        plot_width = float(clip_rect.attrib["width"])
        plot_height = float(clip_rect.attrib["height"])
    except (KeyError, ValueError) as error:
        raise IntegrityError("Contribution chart has invalid plot dimensions") from error
    if (
        plot_x < 580
        or plot_y < 400
        or plot_width < 210
        or plot_height < 70
        or plot_x + plot_width > 833
        or plot_y + plot_height > 515
    ):
        raise IntegrityError("Contribution chart does not occupy its safe enlarged box")


def element_by_id(root: ET.Element, element_id: str) -> ET.Element:
    element = next(
        (candidate for candidate in root.iter() if candidate.attrib.get("id") == element_id),
        None,
    )
    if element is None:
        raise IntegrityError(f"Required SVG element #{element_id} is missing")
    return element


def validate_smil_animation(element: ET.Element, attribute_name: str) -> None:
    if local_name(element.tag) != "animate":
        raise IntegrityError(f"#{element.attrib.get('id')} must be an <animate> element")
    if (
        element.attrib.get("attributeName") != attribute_name
        or element.attrib.get("calcMode") != "discrete"
        or element.attrib.get("repeatCount") != "indefinite"
    ):
        raise IntegrityError(
            f"#{element.attrib.get('id')} has invalid typing animation semantics"
        )
    values = element.attrib.get("values", "").split(";")
    raw_times = element.attrib.get("keyTimes", "").split(";")
    if len(values) < 2 or len(values) != len(raw_times):
        raise IntegrityError(f"#{element.attrib.get('id')} has mismatched SMIL values")
    try:
        times = tuple(float(value) for value in raw_times)
    except ValueError as error:
        raise IntegrityError(f"#{element.attrib.get('id')} has invalid keyTimes") from error
    if (
        times[0] != 0
        or times[-1] != 1
        or any(left > right for left, right in zip(times, times[1:]))
    ):
        raise IntegrityError(f"#{element.attrib.get('id')} has non-monotonic keyTimes")
    duration = element.attrib.get("dur", "")
    try:
        duration_seconds = float(duration.removesuffix("s"))
    except ValueError as error:
        raise IntegrityError(f"#{element.attrib.get('id')} has an invalid duration") from error
    if not duration.endswith("s") or duration_seconds <= 0:
        raise IntegrityError(f"#{element.attrib.get('id')} has an invalid duration")


def validate_typing(root: ET.Element, ids: tuple[str, ...]) -> None:
    missing = sorted(REQUIRED_TYPING_IDS - set(ids))
    if missing:
        raise IntegrityError(f"README typing is missing required IDs: {missing}")

    for index, phrase in enumerate(TYPING_PHRASES):
        phrase_element = element_by_id(root, f"typing-phrase-{index}")
        cursor = element_by_id(root, f"typing-cursor-{index}")
        clip_rect = element_by_id(root, f"typing-clip-rect-{index}")
        if phrase_element.text != phrase:
            raise IntegrityError(f"README typing phrase {index} changed")
        if cursor.text != "█":
            raise IntegrityError(f"README typing cursor {index} must use █")
        if "typing-cursor" not in cursor.attrib.get("class", "").split():
            raise IntegrityError(f"README typing cursor {index} lost its CSS class")
        try:
            clip_right = float(clip_rect.attrib["x"]) + float(clip_rect.attrib["width"])
        except (KeyError, ValueError) as error:
            raise IntegrityError(f"README typing clip {index} is invalid") from error
        if clip_right > 832:
            raise IntegrityError(f"README typing phrase {index} exceeds the safe text area")
        validate_smil_animation(
            element_by_id(root, f"typing-width-{index}-animation"), "width"
        )
        validate_smil_animation(
            element_by_id(root, f"typing-cursor-{index}-animation"), "x"
        )
        validate_smil_animation(
            element_by_id(root, f"typing-opacity-{index}-animation"), "opacity"
        )

    if element_by_id(root, "typing-static-phrase").text != TYPING_PHRASES[0]:
        raise IntegrityError("Reduced-motion typing fallback changed")
    if element_by_id(root, "typing-static-cursor").text != "█":
        raise IntegrityError("Reduced-motion cursor must use █")
    css = "\n".join(style_texts(root))
    if "prefers-reduced-motion: reduce" not in css:
        raise IntegrityError("README typing is missing its reduced-motion fallback")


def validate_metrics_dashboard(root: ET.Element) -> None:
    from update_neofetch import format_code_lines

    panel = element_by_id(root, "github-metrics")
    metrics = (
        ("repos", "Repositories", "data-repositories"),
        ("contributions", "Contributions", "data-contributions"),
        ("commits", "Public Commits", "data-public-commits"),
        ("code_lines", "Code Lines", "data-code-lines"),
    )
    cells = [node for node in panel if local_name(node.tag) == "g"]
    if len(cells) != 4:
        raise IntegrityError("Metrics dashboard must contain four cells")
    for key, label, attribute in metrics:
        cell = element_by_id(panel, f"metric-{key}")
        texts = [node for node in cell if local_name(node.tag) == "text"]
        if len(texts) != 2:
            raise IntegrityError(f"Metric {key} must contain a value and label")
        value = int(root.attrib[attribute])
        if (cell.attrib.get("data-value") != str(value)
                or texts[0].text != format_code_lines(value)
                or texts[1].text != label):
            raise IntegrityError(f"Metric {key} does not match its source data")
        for node in texts:
            try:
                x, y = float(node.attrib["x"]), float(node.attrib["y"])
            except (KeyError, ValueError) as error:
                raise IntegrityError(f"Metric {key} has invalid coordinates") from error
            if not 351 < x < 575 or not 420 < y < 520:
                raise IntegrityError(f"Metric {key} is outside the dashboard")
            if node.attrib.get("text-anchor") != "middle":
                raise IntegrityError(f"Metric {key} must be centered")
        if texts[0].attrib["x"] != texts[1].attrib["x"]:
            raise IntegrityError(f"Metric {key} value and label are misaligned")
    if len([node for node in panel if local_name(node.tag) == "line"]) != 2:
        raise IntegrityError("Metrics dashboard must retain its two dividers")


def validate_profile_views_component(root: ET.Element) -> None:
    from update_neofetch import (
        PROFILE_VIEWS_BASELINE,
        PROFILE_VIEWS_LABEL_Y,
        PROFILE_VIEWS_VALUE_Y,
        PROFILE_VIEWS_X,
        format_profile_views,
    )

    try:
        value = int(root.attrib["data-profile-views"])
    except (KeyError, ValueError) as error:
        raise IntegrityError("SVG root is missing valid Profile Views metadata") from error
    if value < PROFILE_VIEWS_BASELINE:
        raise IntegrityError("Profile Views is below its migration baseline")

    component = element_by_id(root, "profile-views")
    texts = [node for node in component if local_name(node.tag) == "text"]
    display_value = format_profile_views(value)
    if (
        component.attrib.get("role") != "group"
        or component.attrib.get("aria-label") != f"Profile Views: {display_value}"
        or component.attrib.get("data-value") != str(value)
        or len(texts) != 2
    ):
        raise IntegrityError("Profile Views metadata or accessibility is inconsistent")
    expected = (
        ("Profile Views", "profile-views-label", PROFILE_VIEWS_LABEL_Y),
        (display_value, "profile-views-value", PROFILE_VIEWS_VALUE_Y),
    )
    for node, (text, css_class, y) in zip(texts, expected):
        if (
            node.text != text
            or node.attrib.get("class") != css_class
            or node.attrib.get("x") != str(PROFILE_VIEWS_X)
            or node.attrib.get("y") != str(y)
            or node.attrib.get("text-anchor") != "end"
        ):
            raise IntegrityError("Profile Views text or position is invalid")
    if not (700 <= PROFILE_VIEWS_X <= 832 and 0 < PROFILE_VIEWS_LABEL_Y < PROFILE_VIEWS_VALUE_Y < 40):
        raise IntegrityError("Profile Views is outside the reserved header area")


def validate_profile_layout(root: ET.Element) -> None:
    background = element_by_id(root, "card-background")
    if local_name(background.tag) != "rect" or "stroke" in background.attrib:
        raise IntegrityError("The profile background must not render an outer border")
    if not background.attrib.get("fill") or background.attrib.get("rx") != "15":
        raise IntegrityError("The profile background lost its fill or rounded corners")

    metadata = (
        "data-repositories",
        "data-contributions",
        "data-public-commits",
        "data-code-lines",
        "data-profile-views",
    )
    for name in metadata:
        try:
            value = int(root.attrib[name])
        except (KeyError, ValueError) as error:
            raise IntegrityError(f"SVG root is missing valid {name} metadata") from error
        if value < 0:
            raise IntegrityError(f"SVG root contains negative {name} metadata")
    try:
        dt.date.fromisoformat(root.attrib["data-rendered-on"])
    except (KeyError, ValueError) as error:
        raise IntegrityError("SVG root is missing a valid internal render date") from error

    tspans = [element for element in root.iter() if local_name(element.tag) == "tspan"]
    visible_text = tuple(element.text or "" for element in tspans)
    if any("Updated" in value for value in visible_text):
        raise IntegrityError("Updated must not be rendered in the profile card")
    if any(value in ("Repositories", "Contributions (1y)", "Public commits", "Code Lines") for value in visible_text):
        raise IntegrityError("Legacy metric rows must not be rendered")
    validate_metrics_dashboard(root)
    validate_profile_views_component(root)
    for label in ("Contact", "GitHub Stats"):
        heading = next(
            (value for value in visible_text if value.startswith(f"- {label} ")), None
        )
        if heading is None or not heading.endswith("─"):
            raise IntegrityError(f"The {label} heading rule is missing")
        heading_end = 335 + len(heading) * 8.4
        if not 825 <= heading_end <= 840:
            raise IntegrityError(f"The {label} heading rule does not reach the inner edge")

    all_text = "".join(
        text for element in root.iter() for text in element.itertext()
    )
    if "pedro@vygotsky" in all_text:
        raise IntegrityError("The previous static title is still rendered")


def validate_ascii_motion(root: ET.Element, data: SvgSnapshot) -> None:
    quality_name = root.attrib.get("data-ascii-quality", "")
    if quality_name not in QUALITY_PRESETS:
        raise IntegrityError("SVG is missing a valid ASCII quality preset")
    quality = get_quality(quality_name)
    try:
        declared_count = int(root.attrib["data-ascii-frame-count"])
    except (KeyError, ValueError) as error:
        raise IntegrityError("SVG is missing a valid ASCII frame count") from error
    if declared_count != len(data.ascii_frames) or declared_count <= 0:
        raise IntegrityError("ASCII frame metadata does not match rendered layers")

    frame_elements = [
        element
        for element in root.iter()
        if local_name(element.tag) == "text"
        and "ascii-frame" in element.attrib.get("class", "").split()
    ]
    interval = quality.animation_duration / declared_count
    for index, element in enumerate(frame_elements):
        style = element.attrib.get("style", "")
        match = re.fullmatch(r"animation-delay:([-+]?[0-9]*\.?[0-9]+)s", style)
        if not match:
            raise IntegrityError(f"ASCII frame {index} has no deterministic delay")
        actual = float(match.group(1))
        expected = index * interval - quality.animation_duration
        if not math.isclose(actual, expected, abs_tol=0.0011):
            raise IntegrityError(f"ASCII frame {index} has an irregular delay")

    css = "\n".join(data.styles)
    duration = f"{quality.animation_duration:.1f}s"
    pattern = rf"animation\s*:\s*ascii-frame-motion\s+{re.escape(duration)}\s+linear\s+infinite"
    if not re.search(pattern, css):
        raise IntegrityError("ASCII crossfade must use a linear, preset-timed cadence")

def validate_svg(path: Path, ascii_source: Path | None = None) -> SvgSnapshot:
    root = parse_svg(path)
    data = snapshot(root)
    expected_dimensions = (EXPECTED_WIDTH, EXPECTED_HEIGHT, EXPECTED_VIEWBOX)
    if data.dimensions != expected_dimensions:
        raise IntegrityError(
            f"Unexpected SVG dimensions in {path}: {data.dimensions}, "
            f"expected {expected_dimensions}"
        )
    if len(data.ids) != len(set(data.ids)):
        raise IntegrityError(f"Duplicate IDs found in {path}")
    unresolved = sorted(set(data.references) - set(data.ids))
    if unresolved:
        raise IntegrityError(f"Broken internal references in {path}: {unresolved}")
    if "ascii-color" not in data.ids:
        raise IntegrityError(f"Required gradient #ascii-color is missing from {path}")
    if not data.ascii_frames:
        raise IntegrityError(f"ASCII animation is missing from {path}")
    validate_css(data)
    validate_ascii_motion(root, data)
    validate_accessibility(root, data.ids)
    validate_contribution_chart(root, data.ids)
    validate_typing(root, data.ids)
    validate_profile_layout(root)
    if ascii_source is not None:
        expected = expected_ascii_frames(ascii_source)
        if data.ascii_frames != expected:
            raise IntegrityError(
                f"ASCII text differs from its immutable source in {path}"
            )
    return data


def first_difference(before: tuple, after: tuple) -> str:
    limit = min(len(before), len(after))
    for index in range(limit):
        if before[index] != after[index]:
            return f"first difference at index {index}"
    if len(before) != len(after):
        return f"length changed from {len(before)} to {len(after)}"
    return "values differ"


def compare_snapshots(before: SvgSnapshot, after: SvgSnapshot) -> None:
    fields = (
        "dimensions",
        "ids",
        "references",
        "styles",
        "classes",
        "keyframes",
        "animation_declarations",
        "animation_elements",
        "ascii_frames",
        "other_text",
        "accessible_text",
        "protected_attributes",
    )
    for field in fields:
        old_value = getattr(before, field)
        new_value = getattr(after, field)
        if old_value != new_value:
            detail = (
                first_difference(old_value, new_value)
                if isinstance(old_value, tuple) and isinstance(new_value, tuple)
                else "values differ"
            )
            raise IntegrityError(f"Optimization changed {field}: {detail}")


def validate_pair(before_path: Path, after_path: Path, ascii_source: Path) -> None:
    before = validate_svg(before_path, ascii_source)
    after = validate_svg(after_path, ascii_source)
    compare_snapshots(before, after)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="SVG files to validate")
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--ascii-source", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.before or args.after:
        if not (args.before and args.after and args.ascii_source):
            raise SystemExit("--before, --after, and --ascii-source must be used together")
        validate_pair(args.before, args.after, args.ascii_source)
        print(f"Validated optimization integrity: {args.after}")
        return
    if not args.paths:
        raise SystemExit("Provide SVG paths or a before/after pair")
    for path in args.paths:
        validate_svg(path, args.ascii_source)
        print(f"Validated SVG: {path}")


if __name__ == "__main__":
    try:
        main()
    except IntegrityError as error:
        raise SystemExit(f"SVG integrity validation failed: {error}") from error
