"""Descriptor-bound immutable publication acknowledgement; no semantic Authority."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path


class _OnlyBoundPublicationTree:
    def __init__(self, target: Path, anchor: Path) -> None:
        self.target, self.anchor = target.absolute(), anchor.absolute()
        if self.target != self.anchor and self.anchor not in self.target.parents:
            raise ValueError("publication target must be beneath its preprovisioned anchor")
        self._directories: dict[Path, int] = {}
        self._files: dict[Path, int] = {}
        self._bindings: list[tuple[int, str, int]] = []
        self._expected: set[Path] | None = None

    def _directory(self, path: Path) -> int:
        if path in self._directories:
            return self._directories[path]
        if path.parent == path:
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        else:
            parent = self._directory(path.parent)
            descriptor = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            self._bindings.append((parent, path.name, descriptor))
        self._directories[path] = descriptor
        return descriptor

    def bind_file(self, path: Path, *, descriptor: int | None = None) -> int:
        path = path.absolute()
        if path != self.anchor and self.anchor not in path.parents:
            raise ValueError("publication file is outside its owning anchor")
        if path in self._files:
            return self._files[path]
        parent = self._directory(path.parent)
        descriptor = (
            os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            if descriptor is None
            else os.dup(descriptor)
        )
        self._files[path] = descriptor
        self._bindings.append((parent, path.name, descriptor))
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("publication leaf must be a regular file")
        return descriptor

    def bind_directory(self, path: Path) -> None:
        path = path.absolute()
        if path != self.anchor and self.anchor not in path.parents:
            raise ValueError("publication directory is outside its owning anchor")
        self._directory(path)

    def bind_existing_target(self) -> bool:
        """Prove a local target lookup beneath an available, no-follow anchor.

        Missing anchor/IO errors propagate, never become local absence. A missing
        optional namespace link proves only this local lookup, not historical or
        scientific absence. Already-open ancestors are rechecked on either outcome.
        """
        self.bind_directory(self.anchor)
        path = self.anchor
        for part in self.target.relative_to(self.anchor).parts:
            path = path / part
            try:
                self.bind_directory(path)
            except FileNotFoundError:
                self.require_namespace()
                return False
        self.require_namespace()
        return True

    def directory_entries(self, path: Path) -> tuple[str, ...]:
        """Enumerate the bound directory, never a subsequently replaced pathname."""
        self.bind_directory(path)
        self.require_namespace()
        entries = tuple(sorted(os.listdir(self._directory(path.absolute()))))
        self.require_namespace()
        return entries

    def read_bytes(self, relative: str, limit: int | None = None) -> bytes:
        path = Path(relative)
        if path.is_absolute() or any(part in {"..", "."} for part in path.parts) or str(path) != relative:
            raise ValueError("publication file requires a canonical relative path")
        descriptor = self.bind_file(self.target / path)
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            stream.seek(0)
            raw = stream.read() if limit is None else stream.read(limit + 1)
        if limit is not None and len(raw) > limit:
            raise ValueError("publication leaf exceeds exact physical bound")
        return raw

    def require_exact(self, files: set[str]) -> None:
        self._directory(self.target)
        self._expected = {self.target / relative for relative in files}
        for relative in sorted(files):
            # Validate paths using the same narrow read boundary before opening.
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or str(path) != relative:
                raise ValueError("publication requires canonical relative paths")
            self.bind_file(self.target / path)
        self.require_namespace()

    def require_namespace(self) -> None:
        for parent, name, descriptor in self._bindings:
            actual, expected = os.stat(name, dir_fd=parent, follow_symlinks=False), os.fstat(descriptor)
            if (actual.st_dev, actual.st_ino, stat.S_IFMT(actual.st_mode)) != (
                expected.st_dev,
                expected.st_ino,
                stat.S_IFMT(expected.st_mode),
            ):
                raise ValueError("publication namespace changed during acknowledgement")
        if self._expected is None:
            return
        directories = {self.target}
        for path in self._expected:
            directories.update(
                parent for parent in path.parents if parent == self.target or self.target in parent.parents
            )
        for path in directories:
            expected_names = {entry.name for entry in (*self._expected, *directories) if entry.parent == path}
            if set(os.listdir(self._directories[path])) != expected_names:
                raise ValueError("publication exact file/directory set differs")

    def synchronize(self, sync_directory: Callable[..., None]) -> None:
        self.require_namespace()
        for path in sorted(self._files):
            os.fsync(self._files[path])
        for path in sorted(self._directories, key=lambda value: (len(value.parts), str(value)), reverse=True):
            if path == self.anchor or self.anchor in path.parents:
                sync_directory(path, descriptor=self._directories[path])
        self.require_namespace()

    def close(self) -> None:
        for descriptor in (*self._files.values(), *reversed(tuple(self._directories.values()))):
            os.close(descriptor)


@contextmanager
def _only_bind_publication_tree(target: Path, anchor: Path) -> Iterator[_OnlyBoundPublicationTree]:
    tree = _OnlyBoundPublicationTree(target, anchor)
    try:
        tree.bind_directory(target)
        yield tree
    finally:
        tree.close()
