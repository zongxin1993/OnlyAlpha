"""Source-owned, immutable closed cuts of verified historical facts.

The owning store supplies its publication barrier, inventory and exact reader.  This
module neither discovers source roots nor grants completeness to a caller or Memory.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json


class OnlySourceCutError(ValueError):
    """A source cannot certify or verify the requested closed cut."""


def only_source_publication[**P, T](method: Callable[P, T]) -> Callable[P, T]:
    """Wrap the complete owner write path, before any owner-local coordination lock."""

    @wraps(method)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        with args[0]._source_cuts.publication():  # type: ignore[attr-defined]
            return method(*args, **kwargs)

    return wrapped


@dataclass(frozen=True, slots=True)
class OnlySourceCutEntryV1:
    locator: str
    identity: str
    content_fingerprint: str

    def __post_init__(self) -> None:
        if not self.locator or not isinstance(self.locator, str):
            raise OnlySourceCutError("SOURCE_CUT_LOCATOR_INVALID")
        for value in (self.identity, self.content_fingerprint):
            if not _sha(value):
                raise OnlySourceCutError("SOURCE_CUT_IDENTITY_INVALID")

    def to_dict(self) -> dict[str, str]:
        return {"locator": self.locator, "identity": self.identity, "content_fingerprint": self.content_fingerprint}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlySourceCutEntryV1:
        if set(value) != {"locator", "identity", "content_fingerprint"}:
            raise OnlySourceCutError("SOURCE_CUT_ENTRY_SCHEMA_INVALID")
        return cls(value["locator"], value["identity"], value["content_fingerprint"])  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class OnlySourceClosedCutV1:
    source_family: str
    source_schema_version: int
    entries: tuple[OnlySourceCutEntryV1, ...]
    cut_boundary: str = "FILE_PUBLICATION_BARRIER_V1"
    completeness_proof: str = "SOURCE_OWNED_EXCLUSIVE_INVENTORY_V1"
    cut_fingerprint: str = ""
    schema_version: int = 1
    enumeration_contract_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or self.enumeration_contract_version != 1
            or not self.source_family
            or not isinstance(self.source_family, str)
            or type(self.source_schema_version) is not int
            or self.source_schema_version < 1
            or not isinstance(self.cut_boundary, str)
            or not self.cut_boundary
            or not isinstance(self.completeness_proof, str)
            or not self.completeness_proof
        ):
            raise OnlySourceCutError("SOURCE_CUT_SCHEMA_INVALID")
        if tuple(sorted(self.entries, key=lambda entry: entry.locator)) != self.entries:
            raise OnlySourceCutError("SOURCE_CUT_ORDER_INVALID")
        if len({entry.locator for entry in self.entries}) != len(self.entries):
            raise OnlySourceCutError("SOURCE_CUT_LOCATOR_CONFLICT")
        expected = only_canonical_fingerprint(self._identity_payload())
        if not self.cut_fingerprint:
            object.__setattr__(self, "cut_fingerprint", expected)
        elif self.cut_fingerprint != expected:
            raise OnlySourceCutError("SOURCE_CUT_FINGERPRINT_MISMATCH")

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_family": self.source_family,
            "source_schema_version": self.source_schema_version,
            "enumeration_contract_version": self.enumeration_contract_version,
            "cut_boundary": self.cut_boundary,
            "completeness_proof": self.completeness_proof,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_payload(), "cut_fingerprint": self.cut_fingerprint}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlySourceClosedCutV1:
        if set(value) != {
            "schema_version",
            "source_family",
            "source_schema_version",
            "enumeration_contract_version",
            "entries",
            "cut_fingerprint",
            "cut_boundary",
            "completeness_proof",
        } or not isinstance(value["entries"], list):
            raise OnlySourceCutError("SOURCE_CUT_SCHEMA_INVALID")
        return cls(
            value["source_family"],  # type: ignore[arg-type]
            value["source_schema_version"],  # type: ignore[arg-type]
            tuple(OnlySourceCutEntryV1.from_dict(item) for item in value["entries"]),
            value["cut_boundary"],  # type: ignore[arg-type]
            value["completeness_proof"],  # type: ignore[arg-type]
            value["cut_fingerprint"],  # type: ignore[arg-type]
            value["schema_version"],  # type: ignore[arg-type]
            value["enumeration_contract_version"],  # type: ignore[arg-type]
        )


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def only_sha256_source_inventory(root: Path) -> tuple[str, ...]:
    """Owner-invoked strict inventory for a flat `sha256/<prefix>/<locator>` store."""
    if not root.exists():
        return ()
    if root.is_symlink() or not root.is_dir():
        raise OnlySourceCutError("SOURCE_CUT_UNSAFE_PATH")
    if {path.name for path in root.iterdir()} - {"sha256", "closed-cuts", ".source-cut.lock"}:
        raise OnlySourceCutError("SOURCE_CUT_UNKNOWN_ENTRY")
    hashed = root / "sha256"
    if not hashed.exists():
        return ()
    if hashed.is_symlink() or not hashed.is_dir():
        raise OnlySourceCutError("SOURCE_CUT_UNSAFE_PATH")
    locators: list[str] = []
    for prefix in hashed.iterdir():
        if (
            prefix.is_symlink()
            or not prefix.is_dir()
            or len(prefix.name) != 2
            or any(char not in "0123456789abcdef" for char in prefix.name)
        ):
            raise OnlySourceCutError("SOURCE_CUT_UNKNOWN_ENTRY")
        for path in prefix.iterdir():
            if path.name.startswith(".stage-"):
                continue
            if not _sha(path.name) or path.name[:2] != prefix.name:
                raise OnlySourceCutError("SOURCE_CUT_UNKNOWN_ENTRY")
            locators.append(path.name)
    return tuple(locators)


class _OnlyFileSourceCutAuthority:
    """Private helper composed by exactly one immutable source owner.

    `inventory` must reject unknown files and ordinal gaps; `read` must use the
    original verified source reader, not a copied cut row. All official writers must
    hold `publication()` for the whole atomic publication, including fsync.
    """

    def __init__(
        self,
        owner_root: Path,
        source_family: str,
        source_schema_version: int,
        inventory: Callable[[], tuple[str, ...]],
        read: Callable[[str], tuple[str, Mapping[str, object]]],
    ) -> None:
        self._root = owner_root
        self._family = source_family
        self._source_schema_version = source_schema_version
        self._inventory = inventory
        self._read = read
        self._publication_barrier = OnlySourcePublicationBarrier(owner_root)

    @contextmanager
    def publication(self) -> Iterator[None]:
        with self._publication_barrier.publication():
            yield

    def capture_closed_cut(self) -> OnlySourceClosedCutV1:
        with self._publication_barrier.capture():
            locators = self._inventory()
            if len(locators) != len(set(locators)):
                raise OnlySourceCutError("SOURCE_CUT_DUPLICATE_LOCATOR")
            entries = tuple(self._entry(locator) for locator in sorted(locators))
            cut = OnlySourceClosedCutV1(self._family, self._source_schema_version, entries)
            self._publish(cut)
            return self.load_closed_cut_verified(cut.cut_fingerprint)

    def load_closed_cut_verified(self, fingerprint: str) -> OnlySourceClosedCutV1:
        if not _sha(fingerprint):
            raise OnlySourceCutError("SOURCE_CUT_FINGERPRINT_INVALID")
        target = self._root / "closed-cuts" / "sha256" / fingerprint[:2] / fingerprint
        self._require_safe(target)
        try:
            manifest = target / "manifest.json"
            if target.is_symlink() or not target.is_dir() or manifest.is_symlink():
                raise ValueError("missing/unsafe cut")
            if {item.name for item in target.iterdir()} != {"manifest.json"}:
                raise ValueError("unexpected cut entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or raw != only_canonical_json(payload):
                raise ValueError("non-canonical cut")
            cut = OnlySourceClosedCutV1.from_dict(payload)
            if (
                cut.cut_fingerprint != fingerprint
                or cut.source_family != self._family
                or cut.source_schema_version != self._source_schema_version
            ):
                raise ValueError("wrong source/cut identity")
            if tuple(self._entry(entry.locator) for entry in cut.entries) != cut.entries:
                raise ValueError("source member changed")
            return cut
        except Exception as exc:
            raise OnlySourceCutError("SOURCE_CUT_CORRUPT") from exc

    def _entry(self, locator: str) -> OnlySourceCutEntryV1:
        identity, payload = self._read(locator)
        return OnlySourceCutEntryV1(locator, identity, only_canonical_fingerprint(payload))

    def _publish(self, cut: OnlySourceClosedCutV1) -> None:
        target = self._root / "closed-cuts" / "sha256" / cut.cut_fingerprint[:2] / cut.cut_fingerprint
        self._require_safe(target)
        if target.exists() or target.is_symlink():
            self.load_closed_cut_verified(cut.cut_fingerprint)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        try:
            stage.mkdir(mode=0o700)
            manifest = stage / "manifest.json"
            with manifest.open("x", encoding="utf-8") as stream:
                stream.write(only_canonical_json(cut.to_dict()))
                stream.flush()
                os.fsync(stream.fileno())
            os.rename(stage, target)
            descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def _require_safe(self, target: Path) -> None:
        self._publication_barrier._require_safe(target)


class OnlySourcePublicationBarrier:
    """One source-root publication/capture lock shared by all owner write paths."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @contextmanager
    def publication(self) -> Iterator[None]:
        with self._locked(fcntl.LOCK_SH):
            yield

    @contextmanager
    def capture(self) -> Iterator[None]:
        with self._locked(fcntl.LOCK_EX):
            yield

    @contextmanager
    def _locked(self, mode: int) -> Iterator[None]:
        self._require_safe(self._root)
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / ".source-cut.lock"
        self._require_safe(path)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            fcntl.flock(descriptor, mode)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _require_safe(self, target: Path) -> None:
        current = target
        while current != self._root.parent:
            if current.is_symlink():
                raise OnlySourceCutError("SOURCE_CUT_UNSAFE_PATH")
            if current == current.parent:
                raise OnlySourceCutError("SOURCE_CUT_UNSAFE_PATH")
            current = current.parent
