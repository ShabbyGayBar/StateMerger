# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reconstruct merged spline topology using authored routes, never guessed paths."""

import heapq
import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from .geography import Geography, sequence
from .network import (
    HUB_TYPES,
    INTERMEDIATE,
    NAVAL,
    Anchor,
    Connection,
    SplineNetwork,
    Strip,
    anchor_id,
    connection_id,
    endpoints,
)
from .validation import (
    UNPLACED_POSITION,
    is_land,
    port_issues,
    validate_final_network,
)
from .validation import Components as _Components

logger = logging.getLogger(__name__)


@dataclass
class SplineMergeResult:
    """Structurally valid bytes and explicit static completeness evidence."""

    network: SplineNetwork
    status: Literal["complete", "draft"]

    @property
    def data(self) -> bytes:
        """Serialize the prepared network."""
        return self.network.to_bytes()


@dataclass(frozen=True)
class _Edge:
    identity: int
    a: int
    b: int
    kind: int
    path: tuple[int, ...]
    length: float


def locator_positions(tables: dict) -> dict[str, dict[int, tuple[float, float]]]:
    """Read parsed locator trees; accept x/z pairs used by synthetic fixtures."""
    result = {}
    for hub in HUB_TYPES:
        table = tables.get(hub, {})
        if hasattr(table, "to_python"):
            table = table.to_python()
        instances = sequence(table.get("game_object_locator", {}).get("instances"))
        positions = {}
        for item in instances:
            identity = item["id"]
            # pyradox tokenizes engine-written `0.` as the pair `0`, `.`.
            # A standalone dot contributes no extra coordinate.
            raw = [value for value in item.get("position", []) if value != "."]
            if not isinstance(identity, int) or identity < 0 or identity in positions:
                raise ValueError(f"Invalid or duplicate {hub} locator ID: {identity}")
            if len(raw) not in (2, 3):
                raise ValueError(f"Invalid {hub} locator position: {identity}")
            point = (float(raw[0]), float(raw[-1]))
            if not all(math.isfinite(v) for v in point):
                raise ValueError(f"Nonfinite {hub} locator: {identity}")
            positions[identity] = point
        result[hub] = positions
    return result


def merge_spline_network(
    original: SplineNetwork,
    original_states: dict,
    final_states: dict,
    original_locators: dict,
    final_locators: dict,
    merge_plan: dict,
    geography: Geography,
) -> SplineMergeResult:
    """Project hubs, reconnect via shortest original paths, and diagnose all gaps.

    State values are plain dictionaries, e.g. ``StateRegion.to_python()``.
    Locator arguments are parsed trees keyed by city/farm/mine/port/wood.
    No input model or source file is modified.
    """
    return _Merger(
        original,
        original_states,
        final_states,
        original_locators,
        final_locators,
        merge_plan,
        geography,
    ).run()


class _Merger:
    def __init__(
        self, original, states, final, old_locators, locators, plan, geography
    ):
        self.original = original
        self.states = states
        self.final = dict(final)
        self.geo = geography
        self.old_positions = locator_positions(old_locators)
        self.positions = locator_positions(locators)
        self.plan = plan
        consumed = set()
        for target, sources in plan.items():
            if not isinstance(sources, list) or any(
                not isinstance(name, str) or name == target for name in sources
            ):
                raise ValueError("Invalid spline merge plan")
            if consumed.intersection(sources) or len(set(sources)) != len(sources):
                raise ValueError("Spline merge sources must be unique")
            consumed.update(sources)
        if consumed.intersection(final) or consumed.intersection(
            name for name, sources in plan.items() if sources
        ):
            raise ValueError(
                "Absorbed states cannot survive or be active merge targets"
            )
        self.destination = {name: name for name in states}
        for target, sources in plan.items():
            for source in sources:
                self.destination[source] = target
        self.state_ids = {}
        for name, state in states.items():
            identity = int(state["id"])
            if identity in self.state_ids:
                raise ValueError(f"Duplicate original state ID {identity}")
            self.state_ids[identity] = name
            if not self.land(state):
                self.final.setdefault(name, state)
        final_ids = [int(s["id"]) for s in self.final.values()]
        if len(set(final_ids)) != len(final_ids):
            raise ValueError("Duplicate final state IDs")
        for target, sources in plan.items():
            if target not in self.final or any(
                s not in states for s in [target, *sources]
            ):
                raise ValueError(
                    f"Spline merge plan does not match source/final map: {target}"
                )
        logger.debug(
            "Adjacency: required=%s straits=%s blocked=%s naval=%s",
            geography.required,
            geography.straits,
            geography.blocked,
            geography.naval,
        )
        self.out = SplineNetwork()
        self.remap = {}
        self.selected = {}  # original donor anchor -> final required land anchor
        self.hubs = defaultdict(list)  # final state -> final anchor IDs
        self.donors = {}  # final anchor ID -> original donor anchor
        self.unusable_anchors = set()
        self.routing_edges = set()
        self.routable_output = set()
        self.edges = {}
        self.graph = defaultdict(list)
        self.searches = {}
        self.reserved_anchors = set(original.anchors)
        self.reserved_strips = set(original.strips)
        self.next_anchor = 0
        self.next_strip = 0

    land = staticmethod(is_land)

    def warn(self, kind, **details):
        logger.warning("%s (%s): %s", kind, "reconstruction", details)

    def owner(self, identity):
        if identity & INTERMEDIATE:
            return None
        name = self.state_ids.get((identity & (NAVAL - 1)) // 100)
        return self.destination.get(name)

    def allocate_anchor(self, kind):
        while True:
            identity = anchor_id(self.next_anchor, kind, True)
            self.next_anchor += 1
            if identity not in self.reserved_anchors:
                self.reserved_anchors.add(identity)
                return identity

    def mapped(self, old):
        if old in self.remap:
            return self.remap[old]
        point = self.original.anchors[old]
        if old & INTERMEDIATE:
            new = old
        else:
            new = self.allocate_anchor((old >> 23) & 31)
            logger.debug(
                "node_change: %s", {"action": "demote", "from": old, "to": new}
            )
        self.remap[old] = new
        self.out.anchors[new] = Anchor(new, point.x, point.z)
        return new

    def reconcile(self):
        # Sea hubs are not represented by settlement locator files.
        for old, point in self.original.anchors.items():
            state = self.states.get(self.state_ids.get((old & (NAVAL - 1)) // 100), {})
            if (
                not old & INTERMEDIATE
                and (old >> 23) & 31 == 1
                and state
                and not self.land(state)
            ):
                self.remap[old] = old
                self.out.anchors[old] = point
        self.reserved_anchors.update(
            anchor_id(int(s["id"]) * 100 + suffix)
            for s in self.final.values()
            for suffix, hub in enumerate(HUB_TYPES)
            if s.get(hub)
        )
        for name, state in sorted(self.final.items()):
            if not self.land(state):
                continue
            members = [name, *self.plan.get(name, [])]
            for suffix, hub in enumerate(HUB_TYPES):
                if not state.get(hub):
                    continue
                identity = anchor_id(int(state["id"]) * 100 + suffix)
                position = self.positions[hub].get(int(state["id"]))
                donor = next(
                    (
                        m
                        for m in members
                        if str(self.states.get(m, {}).get(hub, "")).lower()
                        == str(state[hub]).lower()
                    ),
                    None,
                )
                action = "create"
                old = (
                    anchor_id(int(self.states[donor]["id"]) * 100 + suffix)
                    if donor is not None
                    else None
                )
                if position is None or position == UNPLACED_POSITION:
                    if position is None:
                        self.warn(
                            "missing_final_locator",
                            state=name,
                            hub=hub,
                            anchor=identity,
                        )
                    else:
                        logger.info(
                            "%s (%s): %s",
                            "unplaced_final_locator",
                            "reconstruction",
                            {"state": name, "hub": hub, "anchor": identity},
                        )
                    original_point = (
                        self.original.anchors.get(old) if old is not None else None
                    )
                    if original_point is None:
                        # Never create geometry at a missing or unplaced locator.
                        if hub == "port":
                            self.reconcile_harbor(
                                name, state, donor, retain_without_port=True
                            )
                        continue
                    point = Anchor(identity, original_point.x, original_point.z)
                    action = "retain" if identity == old else "rename"
                elif donor is not None:
                    point = Anchor(identity, *position)
                    donor_position = self.old_positions[hub].get(
                        int(self.states[donor]["id"])
                    )
                    moved = (
                        donor_position is None
                        or math.dist(position, donor_position) > 0.01
                    )
                    if old in self.original.anchors and not moved:
                        original_point = self.original.anchors[old]
                        point = Anchor(identity, original_point.x, original_point.z)
                        action = "retain" if identity == old else "rename"
                    else:
                        self.warn(
                            "moved_locator" if moved else "missing_source_hub",
                            state=name,
                            hub=hub,
                            anchor=identity,
                            donor=old,
                            position=list(position),
                        )
                else:
                    point = Anchor(identity, *position)
                    self.warn(
                        "missing_hub_donor",
                        state=name,
                        hub=hub,
                        anchor=identity,
                        position=list(position),
                    )
                if (
                    hub == "port"
                    and port_issues(name, state, point, self.geo)
                    and old is not None
                ):
                    self.unusable_anchors.add(old)
                self.out.anchors[identity] = point
                self.hubs[name].append(identity)
                if action != "create":
                    self.selected[old] = identity
                    self.donors[identity] = old
                    self.remap[old] = identity
                logger.debug(
                    "node_change: %s",
                    {
                        "action": action,
                        "anchor": identity,
                        "state": name,
                        "hub": hub,
                        "position": [point.x, point.z],
                        "locator_position": list(position)
                        if position is not None
                        else None,
                        "donor": old,
                        "coordinate_source": "locator"
                        if action == "create"
                        else "donor_spline",
                    },
                )
                if hub == "port":
                    self.reconcile_harbor(name, state, donor)

    def reconcile_harbor(self, name, state, donor, *, retain_without_port=False):
        harbor = anchor_id(int(state["id"]) * 100, 1)
        self.reserved_anchors.add(harbor)
        port = anchor_id(int(state["id"]) * 100 + 3)
        old = (
            anchor_id(int(self.states[donor]["id"]) * 100, 1)
            if donor is not None
            else None
        )
        if donor is not None and (port in self.donors or retain_without_port):
            point = self.original.anchors.get(old)
            if point is not None:
                candidate = Anchor(harbor, point.x, point.z)
                self.remap[old] = harbor
                self.out.anchors[harbor] = candidate
                logger.debug(
                    "node_change: %s",
                    {
                        "action": "retain_harbor" if old == harbor else "rename_harbor",
                        "from": old,
                        "to": harbor,
                        "state": name,
                        "donor": old,
                        "position": [point.x, point.z],
                        "coordinate_source": "donor_spline",
                    },
                )
                return
        self.warn(
            "missing_harbor_geometry",
            state=name,
            harbor=harbor,
            donor=old,
            position=None,
        )

    def load_edges(self):
        for strip in self.original.strips.values():
            if len(strip.anchors) < 2 or any(
                n not in self.original.anchors for n in strip.anchors
            ):
                self.warn("quarantined_strip", strip=strip.id)
        for identity, conn in sorted(self.original.connections.items()):
            try:
                path = self.original.connection_path(conn)
            except ValueError as exc:
                self.warn(
                    "quarantined_connection", connection=identity, reason=str(exc)
                )
                continue
            a, b, kind = endpoints(identity)
            length = 0.0
            for u, v in pairwise(path):
                left, right = self.original.anchors[u], self.original.anchors[v]
                dx = abs(left.x - right.x)
                # Wrapped coordinates also occur around the dateline.
                width = self.geo.size[0]
                if width and self.geo.wrap_x:
                    dx %= width
                    dx = min(dx, width - dx)
                length += math.hypot(dx, left.z - right.z)
            edge = _Edge(identity, a, b, kind, path, length)
            self.edges[identity] = edge
            if kind >= 2:
                if kind not in (2, 3):
                    self.warn(
                        "unsupported_spline_type", connection=identity, spline_type=kind
                    )
                elif any(((node >> 23) & 31) != 1 for node in path):
                    self.warn(
                        "source_connection_not_routable",
                        connection=identity,
                        reason="anchor_type",
                    )
                continue
            oa, ob = self.owner(a), self.owner(b)
            reason = None
            if self.unusable_anchors.intersection(path):
                reason = "port_validation_failed_or_unavailable"
            elif any(((node >> 23) & 31) != 0 for node in path):
                reason = "incompatible_anchor_type"
            elif oa not in self.final or ob not in self.final:
                reason = "unknown_land_endpoint"
            elif oa != ob:
                adjacent = self.geo.adjacent(oa, ob)
                if adjacent is not True:
                    reason = (
                        "adjacency_unverified"
                        if adjacent is None
                        else "nonadjacent_states"
                    )
            if reason is not None:
                self.warn(
                    "source_connection_not_routable", connection=identity, reason=reason
                )
                continue
            self.routing_edges.add(identity)
            self.graph[a].append((b, edge))
            self.graph[b].append((a, edge))
        for adjacent in self.graph.values():
            adjacent.sort(key=lambda item: (item[0], item[1].identity))

    def preserve(self):
        retained = set(self.remap)
        for edge in self.edges.values():
            # Preserve authored routes whose terminals survive normal projection,
            # even if they fail a semantic check. Removed hubs are not resurrected.
            if edge.a in retained and edge.b in retained:
                self.emit(edge.path, edge.kind, [edge.identity], preserve=edge.identity)

    def emit(self, path, kind, provenance, preserve=None):
        # Split at retained settlement terminals before writing endpoint keys.
        cuts = [
            0,
            *[i for i in range(1, len(path) - 1) if path[i] in self.selected],
            len(path) - 1,
        ]
        for start, stop in pairwise(cuts):
            section = path[start : stop + 1]
            mapped = tuple(self.mapped(node) for node in section)
            if mapped[0] == mapped[-1]:
                continue
            identity = connection_id(mapped[0], mapped[-1], kind)
            if identity in self.out.connections:
                continue
            strip_ids = []
            if preserve is not None and len(cuts) == 2:
                for old_id in self.original.connections[preserve].strips:
                    refs = tuple(
                        self.mapped(n) for n in self.original.strips[old_id].anchors
                    )
                    self.out.strips[old_id] = Strip(old_id, refs)
                    strip_ids.append(old_id)
            else:
                while (self.next_strip << 8) | kind in self.reserved_strips:
                    self.next_strip += 1
                strip_id = (self.next_strip << 8) | kind
                self.next_strip += 1
                self.reserved_strips.add(strip_id)
                self.out.strips[strip_id] = Strip(strip_id, mapped)
                strip_ids.append(strip_id)
            self.out.connections[identity] = Connection(identity, tuple(strip_ids))
            if kind < 2 and (preserve is None or preserve in self.routing_edges):
                self.routable_output.add(identity)
            logger.debug(
                "route: %s",
                {
                    "connection": identity,
                    "endpoints": [mapped[0], mapped[-1]],
                    "spline_type": kind,
                    "action": "preserve" if preserve is not None else "assemble",
                    "source_connections": provenance,
                    "type_conversion": preserve is None
                    and any(self.edges[e].kind != kind for e in provenance),
                },
            )

    def search(self, source):
        if source in self.searches:
            return self.searches[source]
        state = self.owner(source)
        distance, previous = {source: 0.0}, {}
        queue = [(0.0, source)]
        while queue:
            cost, node = heapq.heappop(queue)
            if cost != distance[node]:
                continue
            for neighbor, edge in self.graph.get(node, []):
                if self.owner(neighbor) != state:
                    continue
                candidate = cost + edge.length
                if candidate < distance.get(neighbor, math.inf):
                    distance[neighbor] = candidate
                    previous[neighbor] = (node, edge.identity)
                    heapq.heappush(queue, (candidate, neighbor))
        self.searches[source] = distance, previous
        return distance, previous

    def route_to(self, source, target):
        _, previous = self.search(source)
        steps = []
        while target != source:
            node, edge = previous[target]
            steps.append((node, target, edge))
            target = node
        path, provenance = [source], []
        for left, _, identity in reversed(steps):
            edge = self.edges[identity]
            refs = edge.path if edge.a == left else edge.path[::-1]
            path.extend(refs[1:])
            provenance.append(identity)
        return tuple(path), provenance

    def connect_internal(self):
        for state, hubs in sorted(self.hubs.items()):
            components = _Components(hubs)
            for conn in self.out.connections.values():
                a, b, _kind = endpoints(conn.id)
                if (
                    conn.id in self.routable_output
                    and a in components.parent
                    and b in components.parent
                ):
                    components.join(a, b)
            candidates = []
            for i, a in enumerate(hubs):
                if a not in self.donors:
                    continue
                distance, _ = self.search(self.donors[a])
                for b in hubs[i + 1 :]:
                    if b in self.donors and self.donors[b] in distance:
                        candidates.append((distance[self.donors[b]], a, b))
            for _, a, b in sorted(candidates):
                if components.join(a, b):
                    path, provenance = self.route_to(self.donors[a], self.donors[b])
                    self.emit(path, 1, provenance)
            groups = defaultdict(list)
            for hub in hubs:
                groups[components.root(hub)].append(hub)
            if len(groups) > 1:
                if self.geo.land_connections_required(state) is False:
                    logger.info(
                        "%s (%s): %s",
                        "optional_internal_connectivity_gap",
                        "reconstruction",
                        {
                            "state": state,
                            "components": list(groups.values()),
                            "scope": "within_state_reconstruction",
                        },
                    )
                else:
                    self.warn(
                        "disconnected_state_hubs",
                        state=state,
                        components=list(groups.values()),
                        scope="within_state_reconstruction",
                    )

    def nearest(self, state, endpoint):
        candidates = []
        for hub in self.hubs.get(state, []):
            donor = self.donors.get(hub)
            if donor is not None:
                distance, _ = self.search(donor)
                if endpoint in distance:
                    candidates.append((distance[endpoint], donor))
        return min(candidates) if candidates else None

    def connect_borders(self):
        crossings = defaultdict(list)
        existing = set()
        final_owner = {hub: name for name, hubs in self.hubs.items() for hub in hubs}
        for conn in self.out.connections.values():
            a, b, _kind = endpoints(conn.id)
            if conn.id in self.routable_output and final_owner.get(
                a
            ) != final_owner.get(b):
                existing.add(tuple(sorted((final_owner[a], final_owner[b]))))
        for edge in self.edges.values():
            if edge.identity in self.routing_edges:
                a, b = self.owner(edge.a), self.owner(edge.b)
                if a and b and a != b:
                    crossings[tuple(sorted((a, b)))].append(edge)
        for pair, evidence in sorted(self.geo.required.items()):
            if pair in existing:
                continue
            candidates = []
            for edge in crossings[pair]:
                u, v = (
                    (edge.a, edge.b)
                    if self.owner(edge.a) == pair[0]
                    else (edge.b, edge.a)
                )
                left, right = self.nearest(pair[0], u), self.nearest(pair[1], v)
                if left is not None and right is not None:
                    candidates.append(
                        (
                            left[0] + edge.length + right[0],
                            edge.identity,
                            left[1],
                            right[1],
                            u,
                            v,
                        )
                    )
            if not candidates:
                self.warn(
                    "missing_state_connection",
                    states=list(pair),
                    crossing=evidence[0] if evidence else None,
                )
                continue
            _, identity, a, b, u, v = min(candidates)
            left, lp = self.route_to(a, u)
            right, rp = self.route_to(b, v)
            edge = self.edges[identity]
            middle = edge.path if edge.a == u else edge.path[::-1]
            path = (*left, *middle[1:], *right[::-1][1:])
            self.emit(path, 1, [*lp, identity, *reversed(rp)])

    def run(self):
        self.reconcile()
        self.load_edges()
        self.preserve()
        self.connect_internal()
        self.connect_borders()
        for identity in sorted(self.original.anchors):
            if not identity & INTERMEDIATE and identity not in self.remap:
                logger.debug(
                    "node_change: %s", {"action": "remove", "anchor": identity}
                )
        self.out.anchors = dict(sorted(self.out.anchors.items()))
        self.out.strips = dict(sorted(self.out.strips.items()))
        self.out.connections = dict(sorted(self.out.connections.items()))
        # Validate the serialized float32 positions, not just Python floats in
        # the mutable model. Codec failures still abort before output replacement.
        emitted = SplineNetwork.from_bytes(self.out.to_bytes())
        valid = validate_final_network(
            emitted, self.final, self.geo, locators=self.positions
        )
        logger.debug(
            "Network counts: anchors=%s strips=%s connections=%s",
            len(self.out.anchors),
            len(self.out.strips),
            len(self.out.connections),
        )
        return SplineMergeResult(self.out, "complete" if valid else "draft")
