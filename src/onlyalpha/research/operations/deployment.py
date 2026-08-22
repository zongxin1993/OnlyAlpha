"""Research deployment-to-semantic-store compatibility authority."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

SEMANTIC_STORE_IDENTITY_FILE = ".onlyalpha-semantic-store.json"
SEMANTIC_STORE_IDENTITY_SCHEMA_VERSION = 1


class OnlyResearchDeploymentErrorCode(StrEnum):
    DEPLOYMENT_BINDING_MISSING = "DEPLOYMENT_BINDING_MISSING"
    SEMANTIC_STORE_IDENTITY_MISSING = "SEMANTIC_STORE_IDENTITY_MISSING"
    SEMANTIC_STORE_IDENTITY_CORRUPT = "SEMANTIC_STORE_IDENTITY_CORRUPT"
    SEMANTIC_STORE_IDENTITY_UNSUPPORTED = "SEMANTIC_STORE_IDENTITY_UNSUPPORTED"
    SEMANTIC_STORE_IDENTITY_MISMATCH = "SEMANTIC_STORE_IDENTITY_MISMATCH"
    SEMANTIC_STORE_NOT_EMPTY = "SEMANTIC_STORE_NOT_EMPTY"


class OnlyResearchDeploymentError(RuntimeError):
    def __init__(self, code: OnlyResearchDeploymentErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class OnlyResearchSemanticStoreId:
    value: str

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.value)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("semantic-store ID must be a canonical UUID4") from exc
        if parsed.version != 4 or str(parsed) != self.value:
            raise ValueError("semantic-store ID must be a canonical UUID4")

    @classmethod
    def new(cls) -> OnlyResearchSemanticStoreId:
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value


class OnlyResearchDeploymentBindingReader(Protocol):
    def load_semantic_store_id(self) -> OnlyResearchSemanticStoreId: ...


class OnlyResearchSemanticStoreIdentity:
    """Immutable namespace metadata; never an object catalog or semantic index."""

    def __init__(self, research_root: Path) -> None:
        self._root = research_root
        self._path = research_root / SEMANTIC_STORE_IDENTITY_FILE

    @property
    def path(self) -> Path:
        return self._path

    def load_verified(self) -> OnlyResearchSemanticStoreId:
        if self._root.is_symlink() or self._path.is_symlink():
            raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_CORRUPT)
        if not self._path.is_file():
            raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISSING)
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != {"schema_version", "store_id"}:
                raise ValueError("identity document shape is invalid")
            if payload["schema_version"] != SEMANTIC_STORE_IDENTITY_SCHEMA_VERSION:
                raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_UNSUPPORTED)
            store_id = payload["store_id"]
            if not isinstance(store_id, str):
                raise ValueError("store_id must be a string")
            return OnlyResearchSemanticStoreId(store_id)
        except OnlyResearchDeploymentError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_CORRUPT) from exc

    def initialize(self) -> OnlyResearchSemanticStoreId:
        if self._path.exists() or self._path.is_symlink():
            return self.load_verified()
        if self._root.exists():
            if self._root.is_symlink() or not self._root.is_dir():
                raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_CORRUPT)
            if any(self._root.iterdir()):
                raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_NOT_EMPTY)
        else:
            self._root.mkdir(parents=True)
        identity = OnlyResearchSemanticStoreId.new()
        payload = json.dumps(
            {"schema_version": SEMANTIC_STORE_IDENTITY_SCHEMA_VERSION, "store_id": str(identity)},
            sort_keys=True,
            separators=(",", ":"),
        )
        temporary = self._root / f".{SEMANTIC_STORE_IDENTITY_FILE}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self._path)
            except FileExistsError:
                return self.load_verified()
            directory = os.open(self._root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return self.load_verified()
        finally:
            temporary.unlink(missing_ok=True)


class OnlyResearchDeploymentCoherenceVerifier:
    def __init__(
        self,
        local_identity: OnlyResearchSemanticStoreIdentity,
        binding: OnlyResearchDeploymentBindingReader,
    ) -> None:
        self._local_identity = local_identity
        self._binding = binding

    def verify(self) -> OnlyResearchSemanticStoreId:
        local = self._local_identity.load_verified()
        expected = self._binding.load_semantic_store_id()
        if local != expected:
            raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISMATCH)
        return local


class OnlyResearchFrozenDeploymentCheck:
    """One process-startup deployment verdict; it never dynamically rebinds."""

    def __init__(self, verifier: OnlyResearchDeploymentCoherenceVerifier) -> None:
        try:
            verifier.verify()
        except Exception as exc:
            self._error: Exception | None = exc
        else:
            self._error = None

    def assert_compatible(self) -> None:
        if self._error is not None:
            raise self._error


__all__ = [name for name in globals() if name.startswith(("Only", "SEMANTIC_"))]
