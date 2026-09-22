"""Reviewable code semantics; explicit entries take precedence over range rules."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal[
    "surface", "discontinuity", "ditch", "creek", "structure", "support", "setup", "unknown"
]


class CodeRule(BaseModel):
    code: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)
    role: Role = "unknown"


SURFACES = {
    "604": "Ground Shot",
    "675": "Surface Edge",
    "871": "Pavement Edge Left",
    "872": "Pavement Edge Right",
    "873": "Shoulder Left",
    "874": "Shoulder Right",
    "226": "No Passing Stripe",
    "671": "Street Centerline",
    "694": "Lane Stripe",
    "575": "Gutter Flowline",
    "573": "Gutter Edge",
    "502": "Back of Curb",
    "607": "Breakline",
}
DISCONTINUITIES = {
    "296": "Retaining Wall",
    "294": "Wall",
    "579": "Concrete Barrier",
    "633": "Parapet Wall",
    "634": "Wingwall",
    "311": "Headwall",
    "309": "Flared End Section",
    "305": "Drop Box",
    "306": "Catch Basin",
    "308": "Inlet",
    "351": "Manhole",
}
SUPPORT = {
    "423": "Sign",
    "331": "Water Meter",
    "253": "Power Pole",
    "254": "Pole With Light",
    "255": "Pole With Transformer",
    "280": "Junction Box",
    "281": "Splice Box",
}


def default_rules() -> list[CodeRule]:
    groups: list[tuple[Role, dict[str, str]]] = [
        ("surface", SURFACES),
        ("discontinuity", DISCONTINUITIES),
        ("support", SUPPORT),
        ("ditch", {k: "Ditch" for k in ("363", "877", "878", "879", "880")}),
        ("creek", {k: "Creek" for k in ("364", "365", "366", "367")}),
        ("setup", {k: "Setup / control marker" for k in ("800", "100", "103", "114", "124")}),
    ]
    return [
        CodeRule(code=code, description=desc, role=role)
        for role, entries in groups
        for code, desc in entries.items()
    ]


def parse_code(value: str) -> tuple[str, str, set[str]]:
    text = value.strip().upper()
    first = text.split()[0] if text else ""
    parts = first.split("-")
    base = parts[0]
    markers = {p for p in parts[1:] if p in {"BS", "ES", "PC", "PT"}}
    string_id = "-".join(p for p in parts[1:] if p not in markers)
    return base, string_id, markers


def classify(code: str, rules: dict[str, CodeRule]) -> CodeRule:
    base, _, _ = parse_code(code)
    if base in rules:
        return rules[base]
    if base.isdigit() and 600 <= int(base) <= 639:
        return CodeRule(
            code=base, description="Unclassified structure-range code", role="structure"
        )
    return CodeRule(code=base or "?", description="Review code classification", role="unknown")


def suggest_role(description: str) -> Role:
    """Conservative, explainable suggestions; the UI requires classification review."""
    d = description.lower()
    if re.search(r"wall|barrier|headwall|wingwall|inlet|manhole|catch basin|drop box|curb", d):
        return "discontinuity"
    if "ditch" in d:
        return "ditch"
    if re.search(r"creek|stream|channel", d):
        return "creek"
    if re.search(r"backsight|setup|control point", d):
        return "setup"
    if re.search(
        r"ground shot|pavement|shoulder|stripe|centerline|surface edge|breakline|gutter", d
    ):
        return "surface"
    if re.search(r"pole|sign|meter|junction|splice", d):
        return "support"
    return "unknown"
