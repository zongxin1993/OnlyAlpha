"""Agent Provenance Authority's own closed inventory, including occurrence locators."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from onlyalpha.research.source_cut import (
    OnlySourceClosedCutV1,
    OnlySourceCutError,
    OnlySourceObservationV1,
    _OnlyFileSourceCutAuthority,
)

from .decision import OnlyAgentDecisionV1, OnlyAgentExperimentLaunchRecordV1
from .decision_store import _DecisionLocatorV1
from .model import (
    OnlyAgentOrchestrationResourceV1,
    OnlyAgentSessionManifestV1,
    only_agent_research_brief_from_dict,
)
from .occurrence import (
    OnlyAgentModelCallPlanV1,
    OnlyAgentModelCallResultV1,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolCallResultV1,
)
from .occurrence_store import _OccurrenceLocatorV1
from .store import _identity, _OnlyJsonPutOnceStore, _payload

_PARSERS: dict[str, Callable[[Mapping[str, object]], object]] = {
    "resources": OnlyAgentOrchestrationResourceV1.from_dict,
    "briefs": only_agent_research_brief_from_dict,
    "sessions": OnlyAgentSessionManifestV1.from_dict,
    "decisions": OnlyAgentDecisionV1.from_dict,
    "decisions/by-session-ordinal": _DecisionLocatorV1.from_dict,
    "launch-records": OnlyAgentExperimentLaunchRecordV1.from_dict,
    "launch-records/by-session": _DecisionLocatorV1.from_dict,
    "model-calls/plans": OnlyAgentModelCallPlanV1.from_dict,
    "model-calls/results": OnlyAgentModelCallResultV1.from_dict,
    "model-calls/by-session-ordinal": _OccurrenceLocatorV1.from_dict,
    "model-calls/result-by-plan": _OccurrenceLocatorV1.from_dict,
    "tool-calls/plans": OnlyAgentToolCallPlanV1.from_dict,
    "tool-calls/results": OnlyAgentToolCallResultV1.from_dict,
    "tool-calls/by-session-ordinal": _OccurrenceLocatorV1.from_dict,
    "tool-calls/result-by-plan": _OccurrenceLocatorV1.from_dict,
}


class OnlyAgentProvenanceClosedCutAuthority:
    """The fixed Agent family schema is internal; callers cannot select a subset."""

    def __init__(self, semantic_root: Path) -> None:
        self._semantic_root = semantic_root
        self._root = semantic_root / "research" / "agent-orchestration"
        self._stores = {
            kind: _OnlyJsonPutOnceStore(semantic_root, Path("research/agent-orchestration") / kind) for kind in _PARSERS
        }
        self._source_cuts = _OnlyFileSourceCutAuthority(self._root, "AGENT_PROVENANCE", 2, self._inventory, self._read)

    def capture_closed_cut(self) -> OnlySourceClosedCutV1:
        return self._source_cuts.capture_closed_cut()

    def load_closed_cut_verified(self, fingerprint: str) -> OnlySourceClosedCutV1:
        return self._source_cuts.load_closed_cut_verified(fingerprint)

    def iter_closed_cut_observations_verified(self, fingerprint: str) -> tuple[OnlySourceObservationV1, ...]:
        return self._source_cuts.iter_closed_cut_observations_verified(fingerprint)

    def _inventory(self) -> tuple[str, ...]:
        if not self._root.exists():
            return ()
        if self._root.is_symlink() or {item.name for item in self._root.iterdir()} - {
            "resources",
            "briefs",
            "sessions",
            "decisions",
            "launch-records",
            "model-calls",
            "tool-calls",
            "closed-cuts",
            ".source-cut.lock",
        }:
            raise OnlySourceCutError("AGENT_CUT_UNKNOWN_ENTRY")
        for branch in ("model-calls", "tool-calls"):
            parent = self._root / branch
            if parent.exists() and (
                parent.is_symlink()
                or {item.name for item in parent.iterdir()}
                - {"plans", "results", "by-session-ordinal", "result-by-plan"}
            ):
                raise OnlySourceCutError("AGENT_CUT_UNKNOWN_ENTRY")
        locators: list[str] = []
        for kind in _PARSERS:
            root = self._root / kind
            if not root.exists():
                continue
            allowed = {"sha256"}
            if kind == "decisions":
                allowed.update({"publication-locks", "by-session-ordinal"})
            elif kind == "launch-records":
                allowed.update({"publication-locks", "by-session"})
            elif kind in {"model-calls/plans", "model-calls/results", "tool-calls/plans", "tool-calls/results"}:
                allowed = {"sha256"}
            if root.is_symlink() or {item.name for item in root.iterdir()} - allowed:
                raise OnlySourceCutError("AGENT_CUT_UNKNOWN_ENTRY")
            hashed = root / "sha256"
            if not hashed.exists():
                continue
            if hashed.is_symlink() or not hashed.is_dir():
                raise OnlySourceCutError("AGENT_CUT_UNKNOWN_ENTRY")
            for prefix in hashed.iterdir():
                if (
                    prefix.is_symlink()
                    or not prefix.is_dir()
                    or len(prefix.name) != 2
                    or any(char not in "0123456789abcdef" for char in prefix.name)
                ):
                    raise OnlySourceCutError("AGENT_CUT_UNKNOWN_ENTRY")
                for target in prefix.iterdir():
                    name = target.name
                    if name.startswith(".") and (name.endswith(".lock") or name.endswith(".stage")):
                        continue
                    if (
                        len(name) != 64
                        or any(char not in "0123456789abcdef" for char in name)
                        or name[:2] != prefix.name
                    ):
                        raise OnlySourceCutError("AGENT_CUT_UNKNOWN_ENTRY")
                    locators.append(f"{kind}/{name}")
        self._verify_occurrence_closure(locators)
        return tuple(locators)

    def _read(self, locator: str) -> tuple[str, Mapping[str, object]]:
        kind, _, identity = locator.rpartition("/")
        if kind not in _PARSERS:
            raise OnlySourceCutError("AGENT_CUT_LOCATOR_INVALID")
        value = self._stores[kind].load(identity, _PARSERS[kind], "AGENT_CUT_MISSING", "AGENT_CUT_CORRUPT")
        return _identity(value), _payload(value)

    def _verify_occurrence_closure(self, locators: list[str]) -> None:
        identities: dict[str, set[str]] = defaultdict(set)
        for locator in locators:
            kind, _, identity = locator.rpartition("/")
            identities[kind].add(identity)
        pairs = (
            ("decisions", "decisions/by-session-ordinal"),
            ("launch-records", "launch-records/by-session"),
            ("model-calls/plans", "model-calls/by-session-ordinal"),
            ("model-calls/results", "model-calls/result-by-plan"),
            ("tool-calls/plans", "tool-calls/by-session-ordinal"),
            ("tool-calls/results", "tool-calls/result-by-plan"),
        )
        for facts, index in pairs:
            targets: list[str] = []
            ordinals: dict[str, set[int]] = defaultdict(set)
            for identity in identities[index]:
                value = cast(
                    _DecisionLocatorV1 | _OccurrenceLocatorV1,
                    self._stores[index].load(identity, _PARSERS[index], "AGENT_CUT_MISSING", "AGENT_CUT_CORRUPT"),
                )
                targets.append(value.target_fingerprint)
                ordinal = value.ordinal
                if ordinal is not None:
                    owner = (
                        value.owner_fingerprint
                        if isinstance(value, _OccurrenceLocatorV1)
                        else value.session_fingerprint
                    )
                    ordinals[owner].add(ordinal)
            if len(targets) != len(set(targets)) or set(targets) != identities[facts]:
                raise OnlySourceCutError("AGENT_CUT_OCCURRENCE_GAP")
            for observed in ordinals.values():
                if observed != set(range(max(observed) + 1)):
                    raise OnlySourceCutError("AGENT_CUT_ORDINAL_GAP")
