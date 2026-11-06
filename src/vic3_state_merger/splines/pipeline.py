# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Filesystem adapter for the reusable spline transformation."""

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pyradox

from .geography import atomic_write, build_geography, color_code, file_hash
from .merge import SplineMergeResult, locator_positions, merge_spline_network
from .network import HUB_TYPES, INTERMEDIATE, NETWORK_PATH, SplineNetwork
from .validation import serialized_position

logger = logging.getLogger(__name__)


@dataclass
class _PreparedSplineMerge:
    """Merge result and internal source-integrity bookkeeping."""

    result: SplineMergeResult
    inputs: dict[str, str]

    def verify_inputs(self) -> None:
        for filename, digest in self.inputs.items():
            if file_hash(Path(filename)) != digest:
                raise ValueError(
                    f"Spline input changed during reconstruction: {filename}"
                )

    def log_inputs(self) -> None:
        for filename, digest in sorted(self.inputs.items()):
            logger.debug("Spline input: path=%s sha256=%s", filename, digest)


def _tree(path):
    parsed = pyradox.parse_file(str(path), game="HoI4", path_relative_to_game=False)
    if not isinstance(parsed, pyradox.Tree):
        raise TypeError(f"Expected a script tree: {path}")
    return parsed.to_python()


def _resolve(resolver, stage, relative):
    relative = PurePosixPath(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe spline input path: {relative}")
    path = resolver.files(
        stage, str(relative.parent), suffix=relative.suffix, include_dlc=False
    ).get(relative.name)
    if path is None:
        raise ValueError(
            f"spline_network: missing {relative}; searched {resolver.describe(stage)}"
        )
    return path


def prepare_spline_merge(
    resolver,
    original_states,
    final_states,
    final_locator_outputs,
    merge_plan,
    cache_dir,
    *,
    repair_splines: bool = True,
) -> _PreparedSplineMerge:
    """Resolve independent source stacks and prepare bytes before output cleanup."""
    source = _resolve(resolver, "spline_network", NETWORK_PATH)
    # StateMerger-generated maps identify a merged root unambiguously. Refuse to
    # reconstruct from such an asset even when the caller supplied vanilla states.
    relative_parts = len(PurePosixPath(NETWORK_PATH).parts)
    root = source.parents[relative_parts - 1]
    generated_map = root / "map_data/state_regions/state_merging.txt"
    if generated_map.is_file():
        defined = _tree(generated_map)
        consumed = {name for names in merge_plan.values() for name in names}
        if consumed and set(merge_plan) & set(defined) and not consumed & set(defined):
            raise ValueError(
                "spline_network: source is an already-merged output; use original unmerged inputs"
            )
    original_bytes = source.read_bytes()
    original = SplineNetwork.from_bytes(original_bytes)
    if original.to_bytes() != original_bytes:
        raise ValueError("Spline codec failed byte-identical input round trip")
    old_locators, final_locators = {}, {}
    inputs = {str(source.resolve()): hashlib.sha256(original_bytes).hexdigest()}
    for hub in HUB_TYPES:
        relative = f"gfx/map/map_object_data/generated_map_object_locators_{hub}.txt"
        path = _resolve(resolver, "map_objects", relative)
        old_locators[hub] = _tree(path)
        text = final_locator_outputs.get(relative, "")
        parsed = pyradox.parse(text) if text.strip() else pyradox.Tree()
        if not isinstance(parsed, pyradox.Tree):
            raise TypeError(f"Expected a final {hub} locator tree")
        final_locators[hub] = parsed.to_python()
        inputs[str(path.resolve())] = file_hash(path)
    default = _resolve(resolver, "spline_network", "map_data/default.map")
    config = _tree(default)
    raster = _resolve(
        resolver,
        "spline_network",
        "map_data/" + config.get("provinces", "provinces.png"),
    )
    adjacency = _resolve(
        resolver,
        "spline_network",
        "map_data/" + config.get("adjacencies", "adjacencies.csv"),
    )
    states = {
        name: state
        for name, state in original_states.items()
        if not any(state.get(h) for h in HUB_TYPES)
    }
    states.update(final_states)
    samples = [
        (point.x, point.z)
        for identity, point in original.anchors.items()
        if not identity & INTERMEDIATE
        and (identity >> 23) & 31 == 0
        and identity % 100 == 3
    ]
    samples.extend(
        serialized_position(x, z)
        for x, z in locator_positions(final_locators)["port"].values()
    )
    geography = build_geography(
        raster,
        default,
        adjacency,
        states,
        Path(cache_dir),
        sample_points=samples,
        relocation_provinces=(
            [
                color
                for state in states.values()
                if (color := color_code(state.get("port"))) is not None
            ]
            if repair_splines
            else ()
        ),
    )
    result = merge_spline_network(
        original,
        original_states,
        states,
        old_locators,
        final_locators,
        merge_plan,
        geography,
        repair_splines=repair_splines,
    )
    for path in resolver.files(
        "map_data", "map_data/state_regions", include_dlc=False
    ).values():
        inputs[str(path.resolve())] = file_hash(path)
    inputs.update(geography.inputs)
    for name, snapshot in (
        ("merge_plan", merge_plan),
        ("final_states", states),
        ("final_locators", final_locators),
    ):
        logger.debug(
            "Spline snapshot: %s_sha256=%s",
            name,
            hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
        )
    prepared = _PreparedSplineMerge(result, inputs)
    prepared.log_inputs()
    return prepared


def export_spline_review(
    game_root, final_mod, merge_plan, output, data_dir, *, repair_splines: bool = True
):
    """Export only a review network using an existing mod's exact final locators.

    ``output`` and ``data_dir`` must be outside both inputs and one another.
    The existing mod remains untouched; diagnostics use application logging.
    """
    from ..sources import SourceResolver
    from ..state_merger import StateMerger

    game_root, final_mod, output, data_dir = (
        Path(p).resolve() for p in (game_root, final_mod, output, data_dir)
    )
    for left, right in (
        (output, data_dir),
        (output, game_root),
        (output, final_mod),
        (data_dir, game_root),
        (data_dir, final_mod),
    ):
        if left.is_relative_to(right) or right.is_relative_to(left):
            raise ValueError(
                "Spline review output/data overlap an input or one another"
            )
    source = StateMerger(game_root, output, merge_plan, data_dir)
    source._validate_plan()
    original_states = source.map_data.to_python()
    final = StateMerger(
        game_root, output, {}, data_dir, sources={"map_data": [game_root, final_mod]}
    )
    final_states = final.map_data.to_python()
    consumed = {name for names in merge_plan.values() for name in names}
    if consumed & set(final_states):
        raise ValueError("Review mod still contains absorbed state definitions")
    locator_outputs, final_inputs = {}, {}
    for hub in HUB_TYPES:
        relative = f"gfx/map/map_object_data/generated_map_object_locators_{hub}.txt"
        path = final_mod / relative
        locator_outputs[relative] = path.read_text(encoding="utf-8-sig")
        final_inputs[str(path)] = file_hash(path)
    for path in (final_mod / "map_data/state_regions").glob("*.txt"):
        final_inputs[str(path.resolve())] = file_hash(path)
    prepared = prepare_spline_merge(
        SourceResolver(game_root),
        original_states,
        final_states,
        locator_outputs,
        merge_plan,
        data_dir,
        repair_splines=repair_splines,
    )
    prepared.inputs.update(final_inputs)
    for filename, digest in sorted(final_inputs.items()):
        logger.debug("Spline review input: path=%s sha256=%s", filename, digest)
    prepared.verify_inputs()
    result = prepared.result
    atomic_write(output / NETWORK_PATH, result.data)
    logger.log(
        logging.WARNING if result.status == "draft" else logging.INFO,
        "Spline %s exported: %s",
        result.status,
        output / NETWORK_PATH,
    )
    return result
