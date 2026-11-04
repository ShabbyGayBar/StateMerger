# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deterministic file-level overlays of game-layout input roots."""

import logging
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

STAGES = (
    "map_data",
    "state",
    "pops",
    "buildings",
    "trade",
    "map_objects",
    "misc",
    "localization",
)
ASSETS = ("state_traits", "usa_flag", "usa_state_counter")


def validate_names(values, choices, label):
    """Accept an iterable of distinct names, rejecting strings and unknown names."""
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{label} must be a collection of names, not a string")
    names = tuple(values)
    if any(not isinstance(name, str) or name not in choices for name in names):
        raise ValueError(f"Unknown {label}: {names!r}; choose from {choices}")
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate {label}: {names!r}")
    return names


class SourceResolver:
    """Later roots override matching filenames; contents are never field-merged."""

    def __init__(
        self,
        game_root: str | os.PathLike,
        sources: Mapping[str, Sequence[str | os.PathLike]] | None = None,
    ):
        if sources is not None and not isinstance(sources, Mapping):
            raise ValueError("sources must map stage names to ordered root lists")
        sources = {} if sources is None else sources
        validate_names(sources, STAGES, "source stages")
        self.roots: dict[str, tuple[Path, ...]] = {}
        for stage in STAGES:
            roots = sources.get(stage, [game_root])
            if isinstance(roots, (str, bytes, os.PathLike)) or not isinstance(
                roots, Sequence
            ):
                raise TypeError(f"{stage}: sources must be an ordered root list")
            if not roots or any(
                not isinstance(root, (str, os.PathLike)) or not os.fspath(root)
                for root in roots
            ):
                raise ValueError(f"{stage}: sources must contain nonempty root paths")
            self.roots[stage] = tuple(Path(root).resolve() for root in roots)

    def validate(self, stages):
        for stage in stages:
            logger.info("Sources for %s: %s", stage, self.describe(stage))
            for root in self.roots[stage]:
                if not root.is_dir():
                    raise ValueError(
                        f"{stage}: input root is not a directory: {root}; "
                        f"searched roots: {self.describe(stage)}"
                    )

    def describe(self, stage):
        return " -> ".join(map(str, self.roots[stage]))

    def files(
        self, stage, relative_dir, suffix=".txt", *, by_layer=False
    ) -> dict[str, Path]:
        """Resolve immediate files in a known data directory, sorted by filename."""
        result = {}
        layers = {}
        for layer, root in enumerate(self.roots[stage]):
            directory = root / relative_dir
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if not path.is_file() or path.suffix != suffix:
                    continue
                if path.name in result:
                    logger.debug("Override %s with %s", result[path.name], path)
                result[path.name] = path
                layers[path.name] = layer
        names = sorted(
            result, key=lambda name: (layers[name], name) if by_layer else name
        )
        return {name: result[name] for name in names}

    def check_destination(self, destination, stages):
        """Reject overlapping trees so cleanup and cache copies cannot alter inputs."""
        destination = Path(destination).resolve()
        for stage in stages:
            for root in self.roots[stage]:
                if destination.is_relative_to(root) or root.is_relative_to(destination):
                    raise ValueError(
                        f"{stage}: destination {destination} overlaps input root {root}"
                    )
