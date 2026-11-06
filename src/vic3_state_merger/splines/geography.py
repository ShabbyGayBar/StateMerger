# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sparse province boundaries and state adjacency, independent of spline roads."""

import csv
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image


def atomic_write(path: Path, data: bytes):
    """Replace one prepared output without leaving a truncated destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".spline-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def file_hash(path: Path) -> str:
    """Hash large inputs without reading an entire raster into a Python buffer."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def color_code(value):
    """Normalize Vic3 province colors; ignore non-color synthetic sea labels."""
    try:
        if not isinstance(value, str) or not value.lower().startswith("x"):
            return None
        result = int(value[1:], 16)
        return result if 0 <= result <= 0xFFFFFF else None
    except ValueError:
        return None


def sequence(value):
    """Normalize optional Clausewitz scalar/list values."""
    return (
        value if isinstance(value, (list, tuple)) else [] if value is None else [value]
    )


@dataclass
class Geography:
    """Adjacency evidence and sparse, filesystem-independent placement samples."""

    required: dict[tuple[str, str], list[dict]] = field(default_factory=dict)
    blocked: list[dict] = field(default_factory=list)
    naval: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    inputs: dict[str, str] = field(default_factory=dict)
    province_owners: dict[int, str] = field(default_factory=dict)
    size: tuple[int, int] = (0, 0)
    wrap_x: bool = False
    province_samples: dict[tuple[int, int], int] = field(default_factory=dict)
    placement_available: bool = False
    sea_provinces: set[int] = field(default_factory=set)
    lake_provinces: set[int] = field(default_factory=set)
    coastal_provinces: set[int] = field(default_factory=set)
    # Explicitly supplied adjacency tables are authoritative by default. File
    # readers mark missing/unsupported evidence instead of inferring nonadjacency.
    adjacency_available: bool = True
    uncertain: dict[tuple[str, str], list[dict]] = field(default_factory=dict)
    straits: dict[tuple[str, str], list[dict]] = field(default_factory=dict)

    def __post_init__(self):
        # Accept older manually supplied tables without making their straits
        # mandatory. Copy containers so normalization never edits caller data.
        required = {}
        straits = {pair: list(evidence) for pair, evidence in self.straits.items()}
        for pair, evidence in self.required.items():
            land = []
            for entry in evidence:
                if entry.get("kind") in ("sea", "strait"):
                    straits.setdefault(pair, []).append({**entry, "kind": "strait"})
                else:
                    land.append(entry)
            if land or not evidence:
                required[pair] = land
        self.required = required
        self.straits = straits

    def land_connections_required(self, state: str) -> bool | None:
        """Land connectivity is required only where passable land adjacency exists."""
        if any(a != b and state in (a, b) for a, b in self.required):
            return True
        if not self.adjacency_available or any(
            a != b and state in (a, b) for a, b in self.uncertain
        ):
            return None
        return False

    def adjacent(self, a: str, b: str) -> bool | None:
        """Return passable adjacency, confirmed absence, or unavailable evidence."""
        pair = tuple(sorted((a, b)))
        if a == b or pair in self.required or pair in self.straits:
            return True
        if not self.adjacency_available or pair in self.uncertain:
            return None
        return False

    def pixel_at(self, x: float, z: float) -> tuple[int, int] | None:
        """Convert world coordinates to a raster pixel without clamping edges."""
        width, height = self.size
        if width <= 0 or height <= 0 or not all(map(math.isfinite, (x, z))):
            return None
        px, py = math.floor(x), math.floor(height - z)
        if self.wrap_x:
            px %= width
        return (px, py) if 0 <= px < width and 0 <= py < height else None

    def province_at(self, x: float, z: float) -> int | None:
        """Return a sampled province, or None for unsampled/out-of-range points."""
        pixel = self.pixel_at(x, z)
        return self.province_samples.get(pixel) if pixel is not None else None


def _scan_boundaries(path, wrap):
    """Keep one representative pixel per province pair; corner contact is excluded."""
    boundaries = {}
    with Image.open(path) as source:
        width, height = source.size
        previous = None
        for y in range(height):
            raw = source.crop((0, y, width, y + 1)).convert("RGB").tobytes()
            row = [
                (raw[i] << 16) | (raw[i + 1] << 8) | raw[i + 2]
                for i in range(0, len(raw), 3)
            ]
            for x in range(width):
                current = row[x]
                if x or wrap:
                    neighbor = row[x - 1]
                    if current != neighbor:
                        pair = tuple(sorted((current, neighbor)))
                        boundaries.setdefault(pair, (x, y))
                if previous is not None and current != previous[x]:
                    pair = tuple(sorted((current, previous[x])))
                    boundaries.setdefault(pair, (x, y))
            previous = row
    return (width, height), [
        (*pair, *point) for pair, point in sorted(boundaries.items())
    ]


def build_geography(
    provinces: Path,
    default_map: Path,
    adjacencies: Path,
    states: dict,
    cache_dir: Path,
    sample_points: Iterable[tuple[float, float]] = (),
) -> Geography:
    """Resolve physical borders, explicit crossings and province-level blockers."""
    import pyradox

    parsed = pyradox.parse_file(
        str(default_map), game="HoI4", path_relative_to_game=False
    )
    if not isinstance(parsed, pyradox.Tree):
        raise TypeError("default.map did not parse as a tree")
    config = parsed.to_python()
    wrap = config.get("wrap_x", False) in (True, "yes")
    inputs = {
        str(path.resolve()): file_hash(path)
        for path in (provinces, default_map, adjacencies)
    }
    key = hashlib.sha256(
        json.dumps(
            ["province-boundaries-v1", list(inputs.values()), wrap], sort_keys=True
        ).encode()
    ).hexdigest()
    cache = cache_dir / f"spline-boundaries-{key}.json"
    try:
        cached = json.loads(cache.read_text())
        size, boundaries = tuple(cached["size"]), cached["boundaries"]
    except OSError, ValueError, KeyError, TypeError:
        size, boundaries = _scan_boundaries(provinces, wrap)
        atomic_write(
            cache,
            json.dumps(
                {"size": size, "boundaries": boundaries}, separators=(",", ":")
            ).encode(),
        )
    result = Geography(inputs=inputs, size=size, wrap_x=wrap, placement_available=True)
    result.lake_provinces = {
        c for p in sequence(config.get("lakes")) if (c := color_code(p)) is not None
    }
    result.sea_provinces = {
        c
        for p in sequence(config.get("sea_starts"))
        if (c := color_code(p)) is not None
    } - result.lake_provinces
    water = result.sea_provinces | result.lake_provinces
    impassable = set()
    for name, state in states.items():
        land = bool(state.get("subsistence_building")) or any(
            state.get(hub) for hub in ("city", "farm", "mine", "port", "wood")
        )
        for province in sequence(state.get("provinces")):
            color = color_code(province)
            if color is None:
                continue
            if color in result.province_owners:
                raise ValueError(
                    f"Province {province} belongs to multiple state regions"
                )
            result.province_owners[color] = name
            if not land:
                water.add(color)
                if color not in result.lake_provinces:
                    result.sea_provinces.add(color)
        members = {color_code(p) for p in sequence(state.get("provinces"))}
        for province in sequence(state.get("impassable")):
            color = color_code(province)
            if color not in members:
                result.adjacency_available = False
                result.issues.append(
                    {
                        "kind": "out_of_state_impassable",
                        "state": name,
                        "province": province,
                    }
                )
            else:
                impassable.add(color)

    for a, b, *_ in boundaries:
        if a in result.sea_provinces and b not in water:
            result.coastal_provinces.add(b)
        if b in result.sea_provinces and a not in water:
            result.coastal_provinces.add(a)
    pixels = {
        pixel for x, z in sample_points if (pixel := result.pixel_at(x, z)) is not None
    }
    if pixels:
        with Image.open(provinces) as image:
            # Retain only requested samples, including when boundaries were cached.
            for pixel in sorted(pixels):
                rgb = (
                    image.crop((*pixel, pixel[0] + 1, pixel[1] + 1))
                    .convert("RGB")
                    .tobytes()
                )
                result.province_samples[pixel] = (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]

    explicit = {}
    with adjacencies.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            a, b = color_code(row.get("From")), color_code(row.get("To"))
            if a is None or b is None:
                continue
            pair = tuple(sorted((a, b)))
            kind = row.get("Type", "").strip().lower()
            explicit[pair] = {
                "kind": kind,
                "through": row.get("Through"),
                "comment": row.get("Comment", ""),
            }

    def add(a, b, evidence):
        if a in water or b in water:
            return
        left, right = result.province_owners.get(a), result.province_owners.get(b)
        if left is None or right is None:
            result.adjacency_available = False
            result.issues.append(
                {"kind": "unassigned_border", "provinces": [a, b], "crossing": evidence}
            )
            return
        if left == right:
            return
        lo, hi = sorted((left, right))
        edge = (lo, hi)
        entry = {"provinces": [a, b], **evidence}
        override = explicit.get(tuple(sorted((a, b))), {})
        if override and override["kind"] not in (
            "sea",
            "land",
            "river",
            "canal",
            "impassable",
        ):
            result.uncertain.setdefault(edge, []).append(entry)
            return
        if a in impassable or b in impassable or override.get("kind") == "impassable":
            result.blocked.append({"states": list(edge), **entry})
            return
        if override.get("kind") == "sea" or evidence["kind"] == "strait":
            # An explicit strait is optional even if its pixels touch. Another
            # province pair may still establish a required land border here.
            result.straits.setdefault(edge, []).append(
                {**entry, **override, "kind": "strait"}
            )
        else:
            result.required.setdefault(edge, []).append(entry)

    for a, b, x, y in boundaries:
        add(a, b, {"kind": "land", "pixel": [x, y]})
    for (a, b), evidence in sorted(explicit.items()):
        if a in water and b in water:
            result.naval.append({"provinces": [a, b], **evidence})
        elif evidence["kind"] in ("sea", "land", "river", "canal"):
            add(
                a,
                b,
                {
                    **evidence,
                    "kind": "strait" if evidence["kind"] == "sea" else evidence["kind"],
                },
            )
        elif evidence["kind"] != "impassable":
            left, right = result.province_owners.get(a), result.province_owners.get(b)
            if left is not None and right is not None and left != right:
                lo, hi = sorted((left, right))
                pair = (lo, hi)
                result.uncertain.setdefault(pair, []).append(
                    {"provinces": [a, b], **evidence}
                )
            elif left is None or right is None:
                result.adjacency_available = False
            result.issues.append(
                {
                    "kind": "unknown_adjacency_type",
                    "provinces": [a, b],
                    "type": evidence["kind"],
                }
            )
    return result
