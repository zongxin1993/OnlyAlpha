"""Read-only publication exclusion; neither a closed cut nor absence proof."""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path

import pytest

from onlyalpha.research.source_cut import OnlySourceCutError, OnlySourcePublicationBarrier

pytestmark = pytest.mark.contract


def _provision(root):
    root.mkdir()
    (root / ".source-cut.lock").touch()
    return OnlySourcePublicationBarrier(root)


def test_readonly_inspection_never_creates_syncs_or_publishes_cut(tmp_path, monkeypatch):
    root = tmp_path / "owner"
    barrier = _provision(root)
    before = (root / ".source-cut.lock").stat()
    actual_open = os.open
    opens = []

    def readonly_open(path, flags, *args, **kwargs):
        assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_RDWR)
        opens.append((path, flags))
        return actual_open(path, flags, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("read-only inspection wrote or synchronized")

    with monkeypatch.context() as scope:
        scope.setattr(os, "open", readonly_open)
        scope.setattr(os, "fsync", forbidden)
        scope.setattr(Path, "mkdir", forbidden)
        with barrier.inspect_readonly():
            assert {entry.name for entry in root.iterdir()} == {".source-cut.lock"}
    after = (root / ".source-cut.lock").stat()
    assert opens
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (before.st_ino, before.st_size, before.st_mtime_ns)
    assert {entry.name for entry in root.iterdir()} == {".source-cut.lock"}


@pytest.mark.parametrize("missing", ["owner", "lock"])
def test_readonly_inspection_missing_anchor_is_unavailable_without_provision(tmp_path, missing):
    root = tmp_path / "owner"
    if missing == "lock":
        root.mkdir()
    with pytest.raises(OnlySourceCutError, match="SOURCE_PUBLICATION_UNAVAILABLE"):
        with OnlySourcePublicationBarrier(root).inspect_readonly():
            pytest.fail("missing owning anchor authorized inspection")
    assert root.exists() == (missing == "lock")
    assert not (root / ".source-cut.lock").exists()


@pytest.mark.parametrize("leaf", ["symlink", "directory", "fifo"])
def test_readonly_inspection_rejects_nonregular_lock_without_blocking(tmp_path, leaf):
    root = tmp_path / "owner"
    root.mkdir()
    lock = root / ".source-cut.lock"
    if leaf == "symlink":
        target = tmp_path / "elsewhere"
        target.touch()
        lock.symlink_to(target)
    elif leaf == "directory":
        lock.mkdir()
    else:
        os.mkfifo(lock)
    with pytest.raises(OnlySourceCutError, match="SOURCE_PUBLICATION_BARRIER_INVALID"):
        with OnlySourcePublicationBarrier(root).inspect_readonly():
            pytest.fail("nonregular lock authorized inspection")


@pytest.mark.parametrize("mutation", ["lock", "owner", "ancestor"])
def test_readonly_inspection_rechecks_complete_binding_before_return(tmp_path, mutation):
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "owner"
    barrier = _provision(root)
    with pytest.raises(OnlySourceCutError, match="SOURCE_PUBLICATION_BARRIER_INVALID"):
        with barrier.inspect_readonly():
            target = {"lock": root / ".source-cut.lock", "owner": root, "ancestor": parent}[mutation]
            target.rename(tmp_path / "original")
            if mutation == "lock":
                target.touch()
            else:
                target.mkdir()
                root.mkdir(exist_ok=True)
                (root / ".source-cut.lock").touch()


def test_readonly_inspection_holds_real_exclusive_lock_and_releases_on_error(tmp_path):
    root = tmp_path / "owner"
    barrier = _provision(root)
    descriptor = os.open(root / ".source-cut.lock", os.O_RDONLY)
    try:
        with pytest.raises(RuntimeError, match="consumer stopped"):
            with barrier.inspect_readonly():
                with pytest.raises(BlockingIOError):
                    fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                raise RuntimeError("consumer stopped")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@pytest.mark.parametrize("fault", [errno.EACCES, errno.EIO])
def test_readonly_inspection_io_error_is_not_absence(tmp_path, monkeypatch, fault):
    root = tmp_path / "owner"
    barrier = _provision(root)
    actual_open = os.open

    def unavailable(path, *args, **kwargs):
        if str(path) == ".source-cut.lock":
            raise OSError(fault, "controlled reader failure")
        return actual_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", unavailable)
    with pytest.raises(OnlySourceCutError, match="SOURCE_PUBLICATION_UNAVAILABLE"):
        with barrier.inspect_readonly():
            pytest.fail("IO error authorized inspection")
