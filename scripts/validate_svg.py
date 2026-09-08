#!/usr/bin/env python3
"""Validate generated Neofetch SVGs and reject optimization regressions."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


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
    "fill",
    "stroke",
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
    missing_classes = sorted(used_classes - defined_classes)
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
    validate_accessibility(root, data.ids)
    validate_contribution_chart(root, data.ids)
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
