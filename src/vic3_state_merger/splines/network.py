# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Strict version-4 spline-network codec. Coordinates are horizontal x/z."""

import math
import struct
from dataclasses import dataclass, field

NETWORK_PATH = "gfx/map/spline_network/spline_network.splnet"
HUB_TYPES = ("city", "farm", "mine", "port", "wood")
INTERMEDIATE = 1 << 28
NAVAL = 1 << 23
MASK29 = (1 << 29) - 1


def anchor_id(index: int, anchor_type: int = 0, intermediate: bool = False) -> int:
    """Pack an anchor without allowing overflowing identity/type fields."""
    if not 0 <= index < NAVAL or not 0 <= anchor_type < 32:
        raise ValueError("Anchor identity/type exceeds its packed field")
    return index | (anchor_type << 23) | (INTERMEDIATE if intermediate else 0)


def connection_id(a: int, b: int, spline_type: int) -> int:
    """Pack canonical endpoint order; preserve the full anchor identities."""
    if not 0 <= a <= MASK29 or not 0 <= b <= MASK29 or not 0 <= spline_type < 64:
        raise ValueError("Connection endpoint/type exceeds its packed field")
    a, b = sorted((a, b))
    return (b << 35) | (a << 6) | spline_type


def endpoints(identity: int) -> tuple[int, int, int]:
    """Decode a connection key into two packed anchor IDs and its type."""
    return (identity >> 6) & MASK29, (identity >> 35) & MASK29, identity & 63


@dataclass(frozen=True)
class Anchor:
    """A hub or intermediate geometry point."""

    id: int
    x: float
    z: float


@dataclass(frozen=True)
class Strip:
    """An ordered path of anchor references; low ID byte is spline type."""

    id: int
    anchors: tuple[int, ...]


@dataclass(frozen=True)
class Connection:
    """A logical endpoint pair referencing one or more geometry strips."""

    id: int
    strips: tuple[int, ...]


class _Reader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def read(self, fmt):
        size = struct.calcsize("<" + fmt)
        if self.offset + size > len(self.data):
            raise ValueError(f"Truncated spline network at byte {self.offset}")
        value = struct.unpack_from("<" + fmt, self.data, self.offset)[0]
        self.offset += size
        return value

    def token(self, expected):
        offset = self.offset
        actual = self.read("H")
        if actual != expected:
            raise ValueError(
                f"Unsupported spline schema at byte {offset}: "
                f"expected {expected:#06x}, got {actual:#06x}"
            )

    def value(self, token, fmt):
        self.token(token)
        return self.read(fmt)

    def key(self, token):
        self.token(token)
        self.token(1)

    def sequence(self, token, fmt):
        self.token(3)
        values = []
        while True:
            marker = self.read("H")
            if marker == 4:
                return tuple(values)
            if marker != token:
                raise ValueError(f"Unsupported spline list token {marker:#06x}")
            values.append(self.read(fmt))


@dataclass
class SplineNetwork:
    """Parsed tables in original record order, enabling lossless no-op output."""

    anchors: dict[int, Anchor] = field(default_factory=dict)
    strips: dict[int, Strip] = field(default_factory=dict)
    connections: dict[int, Connection] = field(default_factory=dict)

    @classmethod
    def from_bytes(cls, data: bytes | bytearray | memoryview) -> SplineNetwork:
        """Decode the known schema; semantic broken references remain inspectable."""
        reader = _Reader(data)
        reader.key(0xEE)
        if reader.value(12, "i") != 4:
            raise ValueError("Unsupported spline network version (expected 4)")
        reader.key(0x45A)
        reader.token(3)
        counts = [reader.value(12, "i") for _ in range(3)]
        if any(n < 0 or n > len(data) // 4 for n in counts):
            raise ValueError("Invalid spline table counts")
        reader.token(4)
        network = cls()
        for section, count, table in zip(
            (0x5F4, 0x5F5, 0x5F6),
            counts,
            (network.anchors, network.strips, network.connections),
            strict=True,
        ):
            reader.key(section)
            reader.token(3)
            for _ in range(count):
                reader.token(3)
                reader.key(11)
                if section == 0x5F4:
                    identity = reader.value(20, "I")
                    reader.key(76)
                    coordinates = reader.sequence(13, "f")
                    if len(coordinates) != 2:
                        raise ValueError("Spline anchor needs exactly two coordinates")
                    item = Anchor(identity, *coordinates)
                else:
                    identity = reader.value(0x29C, "Q")
                    reader.key(0x5F7 if section == 0x5F5 else 0x5F5)
                    refs = (
                        reader.sequence(20, "I")
                        if section == 0x5F5
                        else reader.sequence(0x29C, "Q")
                    )
                    item = (
                        Strip(identity, refs)
                        if section == 0x5F5
                        else Connection(identity, refs)
                    )
                reader.token(4)
                if identity in table:
                    raise ValueError(
                        f"Duplicate spline ID {identity} in table {section:#x}"
                    )
                if isinstance(item, Anchor):
                    network.anchors[identity] = item
                elif isinstance(item, Strip):
                    network.strips[identity] = item
                else:
                    network.connections[identity] = item
            reader.token(4)
        if reader.offset != len(data):
            raise ValueError("Unexpected trailing spline data")
        network._validate_values()
        return network

    def _validate_values(self):
        for identity, point in self.anchors.items():
            if identity != point.id or not 0 <= identity <= MASK29:
                raise ValueError("Invalid spline anchor ID")
            if not all(
                math.isfinite(v) and abs(v) <= 3.402823466e38
                for v in (point.x, point.z)
            ):
                raise ValueError("Invalid spline coordinate")
        for table in (self.strips, self.connections):
            for identity, record in table.items():
                if identity != record.id or not 0 <= identity < 1 << 64:
                    raise ValueError("Invalid spline record ID")
        for strip in self.strips.values():
            if any(not 0 <= ref <= MASK29 for ref in strip.anchors):
                raise ValueError("Invalid strip anchor ID")
        for conn in self.connections.values():
            if any(not 0 <= ref < 1 << 64 for ref in conn.strips):
                raise ValueError("Invalid connection strip ID")

    def to_bytes(self) -> bytes:
        """Serialize without sorting: unchanged input retains byte ordering."""
        self._validate_values()
        out = bytearray()

        def token(value):
            out.extend(struct.pack("<H", value))

        def key(value):
            token(value)
            token(1)

        def value(marker, fmt, data):
            token(marker)
            out.extend(struct.pack("<" + fmt, data))

        key(0xEE)
        value(12, "i", 4)
        key(0x45A)
        token(3)
        for table in (self.anchors, self.strips, self.connections):
            value(12, "i", len(table))
        token(4)
        for section, table in (
            (0x5F4, self.anchors),
            (0x5F5, self.strips),
            (0x5F6, self.connections),
        ):
            key(section)
            token(3)
            for identity, item in table.items():
                token(3)
                key(11)
                value(
                    20 if section == 0x5F4 else 0x29C,
                    "I" if section == 0x5F4 else "Q",
                    identity,
                )
                key(76 if section == 0x5F4 else 0x5F7 if section == 0x5F5 else 0x5F5)
                token(3)
                if isinstance(item, Anchor):
                    for component in (item.x, item.z):
                        value(13, "f", component)
                elif isinstance(item, Strip):
                    for ref in item.anchors:
                        value(20, "I", ref)
                else:
                    for ref in item.strips:
                        value(0x29C, "Q", ref)
                token(4)
                token(4)
            token(4)
        return bytes(out)

    def connection_path(self, connection: Connection) -> tuple[int, ...]:
        """Join chains supported by the tool's routing model.

        Unsupported representations are implementation limits, not additional
        documented rules of the game's validator.
        """
        a, b, kind = endpoints(connection.id)
        if (
            a == b
            or a > b
            or not connection.strips
            or len(set(connection.strips)) != len(connection.strips)
        ):
            raise ValueError("Invalid connection endpoints/strip chain")
        remaining = []
        for identity in connection.strips:
            strip = self.strips.get(identity)
            if strip is None or identity & 255 != kind or len(strip.anchors) < 2:
                raise ValueError("Missing strip, incompatible type, or empty geometry")
            if any(ref not in self.anchors for ref in strip.anchors):
                raise ValueError("Strip references a missing anchor")
            remaining.append(strip.anchors)
        path = [a]
        while remaining:
            candidates = [
                i for i, refs in enumerate(remaining) if path[-1] in (refs[0], refs[-1])
            ]
            if len(candidates) != 1:
                raise ValueError("Disconnected or ambiguous strip chain")
            refs = remaining.pop(candidates[0])
            if refs[0] != path[-1]:
                refs = refs[::-1]
            path.extend(refs[1:])
        if path[-1] != b:
            raise ValueError("Connection key disagrees with strip endpoints")
        return tuple(path)

    def validate_references(self) -> None:
        """Require all output references and logical endpoint chains to resolve."""
        self._validate_values()
        for strip in self.strips.values():
            if len(strip.anchors) < 2 or any(
                ref not in self.anchors for ref in strip.anchors
            ):
                raise ValueError(f"Invalid output strip {strip.id}")
        for conn in self.connections.values():
            self.connection_path(conn)
