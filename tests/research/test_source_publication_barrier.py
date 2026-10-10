"""Read-only publication exclusion; neither a closed cut nor absence proof."""

from __future__ import annotations

import errno
import fcntl
import os
import select
import subprocess
import sys
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


def test_existing_owner_publication_never_recreates_missing_semantic_root(tmp_path):
    root = tmp_path / "owner"
    with pytest.raises(OnlySourceCutError, match="SOURCE_PUBLICATION_UNAVAILABLE"):
        with OnlySourcePublicationBarrier(root).publication_existing():
            pytest.fail("missing owner authorized publication acknowledgement")
    assert not root.exists()


@pytest.mark.parametrize("method", ["publication", "capture"])
def test_publication_ancestor_symlink_never_creates_directories_before_rejection(tmp_path, method):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    sentinel = unrelated / "retained"
    sentinel.write_bytes(b"original")
    parent = tmp_path / "configured"
    parent.symlink_to(unrelated, target_is_directory=True)
    root = parent / "nested" / "owner"
    with pytest.raises(OnlySourceCutError, match="SOURCE_PUBLICATION_BARRIER_INVALID"):
        with getattr(OnlySourcePublicationBarrier(root), method)():
            pytest.fail("symlink ancestor authorized owner creation")
    assert {entry.name for entry in unrelated.iterdir()} == {"retained"}
    assert sentinel.read_bytes() == b"original"


@pytest.mark.parametrize("method", ["publication", "capture"])
def test_legacy_publication_can_create_only_its_missing_configured_directory_chain(tmp_path, method):
    root = tmp_path / "first" / "second" / "owner"
    with getattr(OnlySourcePublicationBarrier(root), method)():
        assert root.is_dir()
        assert {entry.name for entry in root.iterdir()} == {".source-cut.lock"}
    assert {entry.name for entry in tmp_path.iterdir()} == {"first"}


@pytest.mark.parametrize("method", ["publication", "capture", "inspect_readonly"])
@pytest.mark.parametrize("fault_at", ["acquire", "unlock"])
def test_publication_lock_failures_close_descriptors_and_remain_unavailable(tmp_path, monkeypatch, method, fault_at):
    root = tmp_path / "owner"
    barrier = _provision(root)
    actual_flock, actual_close = fcntl.flock, os.close
    failed, closed = [], []

    def fail_lock(descriptor, operation):
        if (operation == fcntl.LOCK_UN) == (fault_at == "unlock"):
            failed.append(descriptor)
            raise OSError(errno.EIO, "controlled lock failure")
        return actual_flock(descriptor, operation)

    def record_close(descriptor):
        closed.append(descriptor)
        return actual_close(descriptor)

    with monkeypatch.context() as scope:
        scope.setattr(fcntl, "flock", fail_lock)
        scope.setattr(os, "close", record_close)
        with pytest.raises((OnlySourceCutError, OSError)) as error:
            with getattr(barrier, method)():
                assert fault_at == "unlock"
    assert len(failed) == 1
    assert failed[0] in closed
    descriptor = os.open(root / ".source-cut.lock", os.O_RDONLY)
    try:
        actual_flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        actual_close(descriptor)
    assert isinstance(error.value, OnlySourceCutError)
    assert str(error.value) == "SOURCE_PUBLICATION_UNAVAILABLE"


@pytest.mark.parametrize("method", ["publication", "capture", "inspect_readonly"])
@pytest.mark.parametrize("leaf", ["symlink", "directory", "fifo"])
def test_publication_barrier_rejects_nonregular_lock_without_blocking(tmp_path, leaf, method):
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
    expected = OnlySourceCutError if method == "inspect_readonly" else (OnlySourceCutError, OSError)
    error = "SOURCE_PUBLICATION_BARRIER_INVALID"
    if method != "inspect_readonly":
        error += "|UNSAFE_PATH|directory"
    with pytest.raises(expected, match=error):
        with getattr(OnlySourcePublicationBarrier(root), method)():
            pytest.fail("nonregular lock authorized inspection")


@pytest.mark.parametrize("method", ["publication", "capture", "inspect_readonly"])
@pytest.mark.parametrize("mutation", ["lock", "owner", "ancestor"])
def test_publication_barrier_rechecks_complete_binding_before_return(tmp_path, mutation, method):
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "owner"
    barrier = _provision(root)
    with pytest.raises(OnlySourceCutError, match="SOURCE_PUBLICATION_BARRIER_INVALID"):
        with getattr(barrier, method)():
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


@pytest.mark.parametrize("first", ["publication", "inspection"])
def test_publication_and_readonly_inspection_exclude_each_other_across_processes(tmp_path, first):
    root = tmp_path / "owner"
    barrier = _provision(root)
    context = barrier.publication() if first == "publication" else barrier.inspect_readonly()
    second = "inspection" if first == "publication" else "publication"
    process = None
    try:
        with context:
            process = subprocess.Popen(
                [sys.executable, "-m", "tests.runtime_support.source_publication_lock", str(root), second],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert process.stdout is not None
            ready, _, _ = select.select([process.stdout], [], [], 10)
            assert ready, "child did not reach its nonblocking lock probe"
            assert process.stdout.readline().strip() == "blocked"
        output, errors = process.communicate(timeout=10)
        assert process.returncode == 0, errors
        assert output.strip() == "entered"
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)


def test_nested_publication_does_not_deadlock_behind_waiting_inspector(tmp_path):
    root = tmp_path / "owner"
    _provision(root)
    publisher = inspector = None
    try:
        publisher = subprocess.Popen(
            [sys.executable, "-m", "tests.runtime_support.source_publication_lock", str(root), "nested-publication"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert publisher.stdout is not None and publisher.stdin is not None
        ready, _, _ = select.select([publisher.stdout], [], [], 10)
        assert ready and publisher.stdout.readline().strip() == "outer"
        inspector = subprocess.Popen(
            [sys.executable, "-m", "tests.runtime_support.source_publication_lock", str(root), "inspection"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert inspector.stdout is not None
        ready, _, _ = select.select([inspector.stdout], [], [], 10)
        assert ready and inspector.stdout.readline().strip() == "blocked"
        publisher.stdin.write("continue\n")
        publisher.stdin.flush()
        output, errors = publisher.communicate(timeout=10)
        assert publisher.returncode == 0, errors
        assert output.strip() == "nested"
        output, errors = inspector.communicate(timeout=10)
        assert inspector.returncode == 0, errors
        assert output.strip() == "entered"
    finally:
        for process in (publisher, inspector):
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=10)
