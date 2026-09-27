#!/usr/bin/env python3
"""Validate the static About profile card before it is committed."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

from generate_about_card import (
    CARD_WIDTH,
    NETWORK,
    TECHNOLOGIES,
    THEMES,
    local_name,
)


class AboutCardIntegrityError(RuntimeError):
    """Raised when a generated About card breaks a layout or asset invariant."""


def element_by_id(root: ET.Element, element_id: str) -> ET.Element:
    try:
        return next(node for node in root.iter() if node.attrib.get("id") == element_id)
    except StopIteration as error:
        raise AboutCardIntegrityError(f"Missing element: {element_id}") from error


def validate_about_card(path: Path) -> None:
    try:
        root = ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError) as error:
        raise AboutCardIntegrityError(f"Invalid SVG: {path}") from error
    if local_name(root.tag) != "svg":
        raise AboutCardIntegrityError("Root element is not SVG")
    if root.attrib.get("width") != str(CARD_WIDTH):
        raise AboutCardIntegrityError("Unexpected card width")
    try:
        height = int(root.attrib["height"])
    except (KeyError, ValueError) as error:
        raise AboutCardIntegrityError("Missing card height") from error
    if root.attrib.get("viewBox") != f"0 0 {CARD_WIDTH} {height}":
        raise AboutCardIntegrityError("viewBox must match dimensions")
    if root.attrib.get("data-card") != "developer-profile":
        raise AboutCardIntegrityError("Missing card metadata")
    if root.attrib.get("data-theme") not in THEMES:
        raise AboutCardIntegrityError("Unsupported card theme")

    ids = [node.attrib["id"] for node in root.iter() if "id" in node.attrib]
    if len(ids) != len(set(ids)):
        raise AboutCardIntegrityError("Duplicate SVG IDs")
    element_by_id(root, "about-card-title")
    element_by_id(root, "about-card-description")
    element_by_id(root, "about-card-background")

    text_content = {node.text for node in root.iter() if local_name(node.tag) == "text"}
    required_sections = {"About Me", "Technologies & Tools", "Network"}
    required_sections.update(category.name for category in TECHNOLOGIES)
    if not required_sections.issubset(text_content):
        raise AboutCardIntegrityError("Missing section labels")

    expected_technologies = [item.name for category in TECHNOLOGIES for item in category.items]
    technology_nodes = [node for node in root.iter() if "data-icon" in node.attrib]
    if [node.attrib["data-icon"] for node in technology_nodes] != expected_technologies:
        raise AboutCardIntegrityError("Technology assets are missing or out of order")
    for node in technology_nodes:
        tile = next((child for child in node if local_name(child.tag) == "rect"), None)
        if tile is None:
            raise AboutCardIntegrityError("Technology tile is missing a frame")
        x = float(tile.attrib["x"])
        y = float(tile.attrib["y"])
        width = float(tile.attrib["width"])
        tile_height = float(tile.attrib["height"])
        if x < 0 or y < 0 or x + width > CARD_WIDTH or y + tile_height > height:
            raise AboutCardIntegrityError("Technology tile overflows the card")
        if not any("data-asset" in child.attrib for child in node.iter()):
            raise AboutCardIntegrityError("Technology tile is missing its vector asset")

    expected_network = [item.name for item in NETWORK]
    network_nodes = [node for node in root.iter() if "data-network" in node.attrib]
    if [node.attrib["data-network"] for node in network_nodes] != expected_network:
        raise AboutCardIntegrityError("Network badges are missing or out of order")
    for node in network_nodes:
        asset = next((child for child in node.iter() if "data-asset" in child.attrib), None)
        if asset is None:
            raise AboutCardIntegrityError("Network badge is missing its vector asset")
        x = float(asset.attrib["x"])
        y = float(asset.attrib["y"])
        width = float(asset.attrib["width"])
        asset_height = float(asset.attrib["height"])
        if x < 0 or y < 0 or x + width > CARD_WIDTH or y + asset_height > height:
            raise AboutCardIntegrityError("Network badge overflows the card")

    for node in root.iter():
        for name, value in node.attrib.items():
            if local_name(name) == "href" and value.startswith(("http:", "https:")):
                raise AboutCardIntegrityError("The card must not depend on remote SVG assets")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    return parser.parse_args()


def main() -> None:
    for path in parse_args().paths:
        validate_about_card(path)
        print(f"Validated About card: {path}")


if __name__ == "__main__":
    main()
