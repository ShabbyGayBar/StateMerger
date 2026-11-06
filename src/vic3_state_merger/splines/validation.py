# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Validate emitted networks against documented rules, not routing preferences.

Evidence and version limitations are recorded in docs/SPLINE_NETWORK.md.
No check infers a harbor's validity from the pixel under its coordinates.
"""

import logging
import struct
from collections import defaultdict

from .geography import Geography, color_code
from .network import HUB_TYPES, INTERMEDIATE, NAVAL, Anchor, anchor_id, endpoints

logger = logging.getLogger(__name__)
UNPLACED_POSITION = (-1.0, -1.0)


def is_land(state):
    return bool(state.get("subsistence_building")) or any(
        state.get(hub) for hub in HUB_TYPES
    )


class Components:
    def __init__(self, nodes):
        self.parent = {node: node for node in nodes}

    def root(self, node):
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def join(self, a, b):
        a, b = self.root(a), self.root(b)
        if a == b:
            return False
        self.parent[max(a, b)] = min(a, b)
        return True


def serialized_position(x, z):
    """Return the horizontal float32 coordinates stored by the spline codec."""
    return struct.unpack("<ff", struct.pack("<ff", x, z))


def connection_issue(identity, path, states, geo, *, by_id=None):
    """Classify route semantics identically for repairs and final validation."""
    a, b, kind = endpoints(identity)
    if kind not in (0, 1, 2, 3):
        return {
            "kind": "unsupported_spline_type",
            "category": "unverified",
            "rule": "route_semantics",
            "spline_type": kind,
        }
    if any(((node >> 23) & 31) != (0 if kind < 2 else 1) for node in path):
        return {"kind": "incompatible_anchor_type"}
    if kind >= 2:
        return None
    if by_id is None:
        by_id = {int(state["id"]): name for name, state in states.items()}
    owners = [
        None if node & INTERMEDIATE else by_id.get((node & (NAVAL - 1)) // 100)
        for node in (a, b)
    ]
    if any(name is None or not is_land(states[name]) for name in owners):
        return {"kind": "unknown_land_endpoint", "category": "implementation"}
    adjacent = geo.adjacent(*owners)
    if adjacent is not True:
        return {
            "kind": "nonadjacent_state_connection"
            if adjacent is False
            else "unverified_state_connection",
            "category": "game_rule" if adjacent is False else "unverified",
            "rule": "land_adjacency",
            "states": owners,
        }
    return None


def port_issues(
    name: str, state: dict, point: Anchor | None, geo: Geography
) -> list[dict]:
    """Check the land-port rules logged at travel_network_definition.cpp:371/1171.

    This pure helper is also used to exclude failed/unverified projected ports
    from reconstruction. Only the final validation pass reports its findings.
    """
    # Validate the float32 coordinates that will actually be emitted, including
    # when direct API callers supply higher-precision Python floats.
    position = None
    pixel = None
    province = None
    checks = ["coastal_port_province"]
    if point is not None:
        x, z = serialized_position(point.x, point.z)
        position = [x, z]
        pixel = geo.pixel_at(x, z)
        province = geo.province_at(x, z)
        checks.insert(0, "port_province")
    expected = color_code(state.get("port"))
    details = {
        "state": name,
        "anchor": point.id if point else anchor_id(int(state["id"]) * 100 + 3),
        "hub": "port",
        "position": position,
        "sampled_province": province,
        "expected_province": expected,
    }
    if not geo.placement_available or expected is None:
        return [
            {
                "kind": "port_validation_unavailable",
                "category": "unverified",
                "checks": checks,
                **details,
            }
        ]
    issues = []
    if point is not None and pixel is not None and province is None:
        issues.append(
            {
                "kind": "port_validation_unavailable",
                "category": "unverified",
                "checks": ["port_province"],
                **details,
            }
        )
    elif point is not None and province != expected:
        issues.append(
            {
                "kind": "invalid_port_placement",
                "category": "game_rule",
                "rule": "port_province",
                "reason": "out_of_bounds" if pixel is None else "wrong_port_province",
                **details,
            }
        )
    if expected not in geo.coastal_provinces:
        issues.append(
            {
                "kind": "noncoastal_port_province",
                "category": "game_rule",
                "rule": "coastal_port_province",
                "reason": "not_coastal_land",
                **details,
            }
        )
    return issues


def validate_final_network(
    network,
    states: dict,
    geo: Geography,
    *,
    locators: dict[str, dict[int, tuple[float, float]]] | None = None,
) -> bool:
    """Validate using normalized final locator positions; never mutate inputs.

    An explicitly unplaced locator exempts an absent hub, not an existing anchor.
    Missing locator data leaves hub activity unverified rather than implying that
    the hub is unused. Port/harbor/naval-exit rules remain independent.
    """
    # Binary/model failures remain fatal, protecting the previous output file.
    network.validate_references()

    failures = 0

    def issue(kind, *, category="game_rule", rule=None, **details):
        nonlocal failures
        failures += 1
        logger.log(
            logging.WARNING if category == "unverified" else logging.ERROR,
            "%s (%s): %s",
            kind,
            category,
            {"rule": rule or kind, **details},
        )

    by_id = {int(state["id"]): name for name, state in states.items()}

    def owner(identity):
        if identity & INTERMEDIATE:
            return None
        return by_id.get((identity & (NAVAL - 1)) // 100)

    hubs = defaultdict(list)
    invalid_ports, unverified_ports = set(), set()
    for name, state in sorted(states.items()):
        if not is_land(state):
            continue
        for suffix, hub in enumerate(HUB_TYPES):
            if not state.get(hub):
                continue
            identity = anchor_id(int(state["id"]) * 100 + suffix)
            point = network.anchors.get(identity)
            position = (locators or {}).get(hub, {}).get(int(state["id"]))
            if position is None:
                issue(
                    "locator_validation_unavailable",
                    category="unverified",
                    rule="hub_activity",
                    checks=["hub_activity", "required_hub"],
                    state=name,
                    hub=hub,
                    anchor=identity,
                )
            if point is None:
                if position == UNPLACED_POSITION:
                    logger.info(
                        "%s (%s): %s",
                        "unplaced_hub_skipped",
                        "not_applicable",
                        {
                            "state": name,
                            "hub": hub,
                            "anchor": identity,
                            "checks": ["required_hub", "hub_connectivity"],
                        },
                    )
                elif position is not None:
                    issue("missing_required_hub", state=name, hub=hub, anchor=identity)
                if hub == "port":
                    # Declared port-province requirements do not depend on a
                    # visual locator or land-port spline anchor being present.
                    for failure in port_issues(name, state, None, geo):
                        issue(**failure)
                continue
            hubs[name].append(identity)
            if hub == "port":
                port_failures = port_issues(name, state, point, geo)
                for failure in port_failures:
                    issue(**failure)
                    target = (
                        unverified_ports
                        if failure["category"] == "unverified"
                        else invalid_ports
                    )
                    target.add(identity)

    # Geography was built from the final map. Unknown crossing rules are missing
    # validation evidence, not proof of nonadjacency or a source spline defect.
    for diagnostic in geo.issues:
        if "state" in diagnostic and diagnostic["state"] not in states:
            continue
        owners = [geo.province_owners.get(p) for p in diagnostic.get("provinces", [])]
        if (
            diagnostic["kind"] == "unknown_adjacency_type"
            and len(owners) == 2
            and all(o in states for o in owners)
        ):
            a, b = owners
            if (
                a is not None
                and b is not None
                and (
                    not is_land(states[a])
                    or not is_land(states[b])
                    or a == b
                    or tuple(sorted((a, b))) in geo.required
                )
            ):
                logger.warning(
                    "%s (%s): %s",
                    diagnostic["kind"],
                    "reconstruction",
                    {k: v for k, v in diagnostic.items() if k != "kind"},
                )
                continue
        issue(
            diagnostic["kind"],
            category="unverified",
            rule="land_adjacency",
            checks=["land_adjacency", "direct_state_connections"],
            details={k: v for k, v in diagnostic.items() if k != "kind"},
        )
    if not geo.adjacency_available and not geo.issues:
        issue("adjacency_unavailable", category="unverified", rule="land_adjacency")
    for pair, evidence in sorted(geo.uncertain.items()):
        if set(pair) <= states.keys() and pair not in geo.required:
            issue(
                "unverified_state_adjacency",
                category="unverified",
                rule="land_adjacency",
                states=list(pair),
                evidence=evidence,
            )

    known = Components(network.anchors)
    possible = Components(network.anchors)
    connected, possibly_connected = set(), set()
    borders, possible_borders = set(), set()
    sea_hubs = {
        anchor_id(int(state["id"]) * 100, 1)
        for state in states.values()
        if not is_land(state)
    }
    naval_routes, possible_naval_routes = defaultdict(set), defaultdict(set)

    for identity, connection in sorted(network.connections.items()):
        a, b, kind = endpoints(identity)
        path = network.connection_path(connection)
        failure = connection_issue(identity, path, states, geo, by_id=by_id)
        if failure is not None:
            issue(**failure, connection=identity)
        if kind not in (0, 1, 2, 3):
            # Over-approximate possibilities instead of guessing this type's
            # traffic rules. This graph can only make a check unverified; it
            # cannot establish validity or seed reconstruction.
            if invalid_ports.intersection(path):
                continue
            possible.join(a, b)
            possibly_connected.update((a, b))
            oa, ob = owner(a), owner(b)
            if oa is not None and ob is not None and oa != ob:
                possible_borders.add(tuple(sorted((oa, ob))))
            for harbor, other in ((a, b), (b, a)):
                if other in sea_hubs:
                    possible_naval_routes[harbor].add(other)
            continue
        if failure is not None and failure["kind"] == "incompatible_anchor_type":
            continue
        if kind >= 2:
            for harbor, other in ((a, b), (b, a)):
                if other in sea_hubs:
                    naval_routes[harbor].add(other)
            continue
        oa, ob = owner(a), owner(b)
        if (
            oa is None
            or ob is None
            or not is_land(states[oa])
            or not is_land(states[ob])
        ):
            continue
        adjacent = True if oa == ob else geo.adjacent(oa, ob)
        if adjacent is False:
            continue
        if invalid_ports.intersection(path):
            continue
        possible.join(a, b)
        possibly_connected.update((a, b))
        if oa != ob:
            possible_borders.add(tuple(sorted((oa, ob))))
        if adjacent is None or unverified_ports.intersection(path):
            continue
        known.join(a, b)
        connected.update((a, b))
        if oa != ob:
            borders.add(tuple(sorted((oa, ob))))

    for name, members in sorted(hubs.items()):
        required = geo.land_connections_required(name)
        if required is False:
            logger.info(
                "%s (%s): %s",
                "land_connectivity_not_applicable",
                "not_applicable",
                {
                    "state": name,
                    "checks": ["hub_connectivity", "state_connections"],
                    "reason": "no_passable_land_neighbors",
                },
            )
            continue
        groups = defaultdict(list)
        for hub in members:
            groups[known.root(hub)].append(hub)
        if len(groups) > 1:
            uncertain = (
                required is None or len({possible.root(hub) for hub in members}) == 1
            )
            logger.warning(
                "%s (%s): %s",
                "disconnected_state_hubs",
                "advisory",
                {
                    "rule": "hub_connectivity",
                    "state": name,
                    "components": list(groups.values()),
                    "scope": "global_land_network",
                    "unverified": uncertain,
                },
            )
        if not any(hub in connected for hub in members):
            issue(
                "unconnected_state",
                rule="state_connections",
                category="unverified"
                if required is None or any(h in possibly_connected for h in members)
                else "game_rule",
                state=name,
                anchors=members,
            )
    for pair, evidence in sorted(geo.required.items()):
        if set(pair) <= states.keys() and pair not in borders:
            logger.warning(
                "%s (%s): %s",
                "missing_state_connection",
                "advisory",
                {
                    "rule": "direct_state_connections",
                    "states": list(pair),
                    "crossing": evidence[0] if evidence else None,
                    "unverified": pair in possible_borders,
                },
            )

    for name, state in sorted(states.items()):
        exit_id = state.get("naval_exit_id", -1)
        # -1 is the state model's absent-exit sentinel. A declared port requires
        # an exit; an explicit exit also needs validation without a port field.
        if not is_land(state) or (not state.get("port") and exit_id == -1):
            continue
        region = (
            by_id.get(exit_id) if isinstance(exit_id, int) and exit_id >= 0 else None
        )
        sea = None
        if region is None or is_land(states[region]):
            issue("invalid_naval_exit", state=name, naval_exit_id=exit_id)
        else:
            sea = anchor_id(exit_id * 100, 1)
            if sea not in network.anchors:
                issue("missing_sea_hub", state=name, sea_region=region, anchor=sea)
        if not state.get("port"):
            continue
        harbor = anchor_id(int(state["id"]) * 100, 1)
        point = network.anchors.get(harbor)
        if point is None:
            issue(
                "missing_harbor_geometry",
                rule="port_harbor",
                state=name,
                harbor=harbor,
                position=None,
            )
        if not naval_routes[harbor]:
            issue(
                "missing_harbor_connection",
                rule="harbor_route",
                category="unverified" if possible_naval_routes[harbor] else "game_rule",
                state=name,
                harbor=harbor,
                sea=sea,
                position=[point.x, point.z] if point else None,
            )
        elif sea is not None and sea not in naval_routes[harbor]:
            logger.warning(
                "%s (%s): %s",
                "harbor_naval_exit_mismatch",
                "advisory",
                {
                    "state": name,
                    "harbor": harbor,
                    "sea": sea,
                    "connected_seas": sorted(naval_routes[harbor]),
                },
            )
    logger.log(
        logging.WARNING if failures else logging.INFO,
        "Spline validation %s: %s required check(s) failed or unverified",
        "draft" if failures else "complete",
        failures,
    )
    return failures == 0
