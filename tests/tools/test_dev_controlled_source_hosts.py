"""Real temporary-file CAS/write faults; root UID checks are simulated, not root evidence.

The formal Shipping runner separately proves the authorized real-container root
entry. These tests never open /etc/hosts, /root, or the actual validation lock.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import dev_verification as owner

OP = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def hosts_owner(monkeypatch, tmp_path):
    original = b"127.0.0.1 localhost\n::1 localhost\n"
    hosts = tmp_path / "hosts"
    hosts.write_bytes(original)
    hosts.chmod(0o644)
    lock = tmp_path / "validation.lock"
    lock.touch(mode=0o600)
    lock_inode = lock.stat().st_ino
    backups = tmp_path / "root-backups"
    (tmp_path / owner.CUT_METADATA).write_text(json.dumps({"operation_id": OP}))
    real_fstat, real_lstat = os.fstat, Path.lstat

    def uid(record, value):
        fields = list(record)
        fields[4] = value
        return os.stat_result(fields)

    # Only ownership observations and fixed deployment paths are simulated.
    # All file descriptors, inodes, flock, writes, fsync and CAS remain real.
    monkeypatch.setattr(owner, "ROOT", tmp_path)
    monkeypatch.setattr(owner, "Path", lambda path: tmp_path if path == "/workspace" else Path(path))
    monkeypatch.setattr(owner, "CONTROLLED_HOSTS", hosts)
    monkeypatch.setattr(owner, "CONTAINER_LOCK", lock)
    monkeypatch.setattr(owner, "CONTROLLED_HOSTS_BACKUPS", backups)
    monkeypatch.setattr(owner.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        owner.os, "fstat", lambda fd: uid(real_fstat(fd), 10001 if real_fstat(fd).st_ino == lock_inode else 0)
    )
    monkeypatch.setattr(Path, "lstat", lambda path: uid(real_lstat(path), 0))
    return SimpleNamespace(hosts=hosts, original=original, backups=backups, backup=backups / OP)


def test_hosts_restore_replay_is_read_only_and_retains_the_original_identity(hosts_owner, monkeypatch):
    case = hosts_owner
    begun = owner.controlled_https_root("begin", OP)
    assert case.hosts.read_bytes() == owner.controlled_hosts_bytes(case.original, OP)
    restored = owner.controlled_https_root("restore", OP)
    assert case.hosts.read_bytes() == case.original
    assert all(restored[key] == begun[key] for key in ("device", "inode", "original_sha256", "mapped_sha256"))
    monkeypatch.setattr(owner.os, "pwrite", lambda *args: pytest.fail("replay attempted a second write"))
    assert owner.controlled_https_root("restore", OP) == restored


@pytest.mark.parametrize("mutation", ["bytes", "inode", "operation"])
def test_hosts_restore_rejects_changed_occurrence_without_writing(hosts_owner, mutation):
    case = hosts_owner
    owner.controlled_https_root("begin", OP)
    operation = OP
    if mutation == "bytes":
        case.hosts.write_bytes(case.hosts.read_bytes() + b"127.0.0.2 unrelated\n")
    elif mutation == "inode":
        case.hosts.rename(case.hosts.with_suffix(".original-inode"))
        case.hosts.write_bytes(owner.controlled_hosts_bytes(case.original, OP))
        case.hosts.chmod(0o644)
    else:
        operation = "00000000-0000-4000-8000-000000000002"
    before = case.hosts.read_bytes()
    identity = case.hosts.stat()
    with pytest.raises(ValueError, match="RESTORE_CAS_REFUSED|RESTORE_IDENTITY_REFUSED|SOURCE_CUT_REFUSED"):
        owner.controlled_https_root("restore", operation)
    assert case.hosts.read_bytes() == before
    assert case.hosts.stat().st_ino == identity.st_ino
    assert not (case.backup / "restore-proof.json").exists()


def test_partial_hosts_write_cannot_be_relabelled_as_a_complete_mapping_or_restoration(hosts_owner, monkeypatch):
    case = hosts_owner
    real_write = os.pwrite
    writes = 0

    def interrupted(fd, raw, offset):
        nonlocal writes
        writes += 1
        if writes > 1:
            raise OSError("controlled partial write")
        return real_write(fd, raw[: len(case.original) + 7], offset)

    with monkeypatch.context() as patch:
        patch.setattr(owner.os, "pwrite", interrupted)
        with pytest.raises(OSError, match="controlled partial write"):
            owner.controlled_https_root("begin", OP)
    partial = case.hosts.read_bytes()
    assert partial != case.original
    assert partial != owner.controlled_hosts_bytes(case.original, OP)
    assert (case.backup / "original").read_bytes() == case.original
    assert not (case.backup / "begin-proof.json").exists()
    with pytest.raises(ValueError, match="RESTORE_CAS_REFUSED"):
        owner.controlled_https_root("restore", OP)
    assert case.hosts.read_bytes() == partial


@pytest.mark.parametrize("checkpoint", ["fsync", "proof"])
def test_completed_bytes_without_restore_proof_remain_unknown(hosts_owner, monkeypatch, checkpoint):
    case = hosts_owner
    owner.controlled_https_root("begin", OP)
    host_inode = case.hosts.stat().st_ino
    real_sync, real_record = os.fsync, owner._root_record

    def interrupted_sync(fd):
        if os.fstat(fd).st_ino == host_inode:
            raise OSError("controlled hosts fsync loss")
        return real_sync(fd)

    def interrupted_record(directory, name, raw):
        if name == "restore-proof.json":
            raise OSError("controlled restore proof loss")
        return real_record(directory, name, raw)

    with monkeypatch.context() as patch:
        if checkpoint == "fsync":
            patch.setattr(owner.os, "fsync", interrupted_sync)
        else:
            patch.setattr(owner, "_root_record", interrupted_record)
        with pytest.raises(OSError, match="controlled"):
            owner.controlled_https_root("restore", OP)
    assert case.hosts.read_bytes() == case.original
    assert not (case.backup / "restore-proof.json").exists()
    with pytest.raises(ValueError, match="RESTORE_CAS_REFUSED"):
        owner.controlled_https_root("restore", OP)


@pytest.mark.parametrize("checkpoint", ["fsync", "proof"])
def test_lost_begin_proof_keeps_backup_and_requires_explicit_exact_restore(hosts_owner, monkeypatch, checkpoint):
    case = hosts_owner
    real_record, real_sync = owner._root_record, os.fsync
    host_inode = case.hosts.stat().st_ino

    def interrupted_sync(fd):
        if os.fstat(fd).st_ino == host_inode:
            raise OSError("controlled begin fsync loss")
        return real_sync(fd)

    def interrupted(directory, name, raw):
        if name == "begin-proof.json":
            raise OSError("controlled begin proof loss")
        return real_record(directory, name, raw)

    with monkeypatch.context() as patch:
        if checkpoint == "fsync":
            patch.setattr(owner.os, "fsync", interrupted_sync)
        else:
            patch.setattr(owner, "_root_record", interrupted)
        with pytest.raises(OSError, match="controlled begin"):
            owner.controlled_https_root("begin", OP)
    assert case.hosts.read_bytes() == owner.controlled_hosts_bytes(case.original, OP)
    assert not (case.backup / "begin-proof.json").exists()
    assert (case.backup / "original").read_bytes() == case.original
    # This explicit same-UUID owner action is recovery, never automatic begin replay.
    owner.controlled_https_root("restore", OP)
    assert case.hosts.read_bytes() == case.original


def test_root_entry_rejects_an_unprivileged_caller_before_touching_hosts(hosts_owner, monkeypatch):
    monkeypatch.setattr(owner.os, "geteuid", lambda: 10001)
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        owner.controlled_https_root("begin", OP)
    assert hosts_owner.hosts.read_bytes() == hosts_owner.original
    assert not hosts_owner.backups.exists()


def test_restore_replay_rejects_path_rebound_after_reading_completed_proof(hosts_owner, monkeypatch):
    case = hosts_owner
    owner.controlled_https_root("begin", OP)
    owner.controlled_https_root("restore", OP)
    original_inode = case.hosts.stat().st_ino
    read = owner._root_read
    rebound = None

    def replace_after_proof(path):
        nonlocal rebound
        raw = read(path)
        if path.name == "restore-proof.json":
            case.hosts.rename(case.hosts.with_suffix(".held-original"))
            case.hosts.write_bytes(case.original)
            case.hosts.chmod(0o644)
            rebound = case.hosts.stat().st_ino
            assert rebound != original_inode
        return raw

    monkeypatch.setattr(owner, "_root_read", replace_after_proof)
    monkeypatch.setattr(owner.os, "pwrite", lambda *args: pytest.fail("replay wrote the rebound hosts"))
    with pytest.raises(ValueError, match="RESTORE_IDENTITY_REFUSED"):
        owner.controlled_https_root("restore", OP)
    assert rebound is not None and case.hosts.stat().st_ino == rebound
    assert case.hosts.read_bytes() == case.original
