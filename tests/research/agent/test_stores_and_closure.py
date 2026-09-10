from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.agent import (
    OnlyAgentCommitDisposition,
    OnlyAgentContextError,
    OnlyAgentOrchestrationResourceKind,
    OnlyJsonAgentOrchestrationResourceStore,
    OnlyJsonAgentResearchBriefStore,
    OnlyJsonAgentSessionManifestStore,
)

from .support import make_context


def _commit_context(root: Path):
    context = make_context(root)
    resource_store = OnlyJsonAgentOrchestrationResourceStore(root)
    for item in context.resources:
        resource_store.commit_resource(item)
    brief_store = OnlyJsonAgentResearchBriefStore(root, context.readers)
    brief_store.commit_research_brief(context.brief)
    session_store = OnlyJsonAgentSessionManifestStore(root, briefs=brief_store, resources=resource_store)
    session_store.commit_session_manifest(context.session)
    return context, resource_store, brief_store, session_store


def _manifest_path(root: Path, category: str, fingerprint: str) -> Path:
    return (
        root
        / "research"
        / "agent-orchestration"
        / category
        / "sha256"
        / fingerprint[:2]
        / fingerprint
        / "manifest.json"
    )


def test_resource_commit_exact_load_reuse_kind_and_missing(tmp_path) -> None:
    context = make_context(tmp_path)
    store = OnlyJsonAgentOrchestrationResourceStore(tmp_path)
    value = context.resources[0]
    assert store.commit_resource(value).disposition is OnlyAgentCommitDisposition.CREATED
    assert store.commit_resource(value).disposition is OnlyAgentCommitDisposition.REUSED
    assert store.load_resource_verified(value.resource_kind, value.resource_fingerprint) == value
    with pytest.raises(OnlyAgentContextError) as wrong_kind:
        store.load_resource_verified(OnlyAgentOrchestrationResourceKind.TOOL_POLICY, value.resource_fingerprint)
    assert wrong_kind.value.code == "AGENT_ORCHESTRATION_RESOURCE_MISMATCH"
    with pytest.raises(OnlyAgentContextError) as missing:
        store.load_resource_verified(value.resource_kind, "f" * 64)
    assert missing.value.code == "AGENT_ORCHESTRATION_RESOURCE_MISSING"


def test_resource_store_rejects_tamper_noncanonical_extra_file_and_wrong_path(tmp_path) -> None:
    context = make_context(tmp_path)
    store = OnlyJsonAgentOrchestrationResourceStore(tmp_path)
    values = context.resources[:4]
    for value in values:
        store.commit_resource(value)

    tampered = _manifest_path(tmp_path, "resources", values[0].resource_fingerprint)
    payload = json.loads(tampered.read_text(encoding="utf-8"))
    payload["resource_semantic_version"] = "2.0.0"
    tampered.write_text(only_canonical_json(payload), encoding="utf-8")
    noncanonical = _manifest_path(tmp_path, "resources", values[1].resource_fingerprint)
    noncanonical.write_text(json.dumps(json.loads(noncanonical.read_text()), indent=2), encoding="utf-8")
    extra = _manifest_path(tmp_path, "resources", values[2].resource_fingerprint).parent
    (extra / "unexpected").write_text("x", encoding="utf-8")
    wrong_path = _manifest_path(tmp_path, "resources", values[3].resource_fingerprint)
    destination = wrong_path.parents[1] / ("e" * 64)
    destination.parent.mkdir(parents=True, exist_ok=True)
    wrong_path.parent.rename(destination)

    for fingerprint in (values[0].resource_fingerprint, values[1].resource_fingerprint, values[2].resource_fingerprint):
        with pytest.raises(OnlyAgentContextError) as raised:
            store.load_resource_verified(values[0].resource_kind, fingerprint)
        assert raised.value.code == "AGENT_ORCHESTRATION_RESOURCE_MISMATCH"
    with pytest.raises(OnlyAgentContextError):
        store.load_resource_verified(values[3].resource_kind, "e" * 64)


def test_resource_store_rejects_symlinked_authority_path(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    context = make_context(real)
    store = OnlyJsonAgentOrchestrationResourceStore(linked)
    with pytest.raises(OnlyAgentContextError) as raised:
        store.commit_resource(context.resources[0])
    assert raised.value.code == "AGENT_CONTEXT_UNSAFE_PATH"


def test_concurrent_identical_resource_commit_converges(tmp_path) -> None:
    context = make_context(tmp_path)
    value = context.resources[0]

    def commit_once() -> OnlyAgentCommitDisposition:
        return OnlyJsonAgentOrchestrationResourceStore(tmp_path).commit_resource(value).disposition

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = tuple(executor.map(lambda _: commit_once(), range(8)))
    assert outcomes.count(OnlyAgentCommitDisposition.CREATED) == 1
    assert outcomes.count(OnlyAgentCommitDisposition.REUSED) == 7
    store = OnlyJsonAgentOrchestrationResourceStore(tmp_path)
    assert store.load_resource_verified(value.resource_kind, value.resource_fingerprint) == value


def test_brief_rejects_each_invalid_external_reference_before_commit(tmp_path) -> None:
    context = make_context(tmp_path)
    store = OnlyJsonAgentResearchBriefStore(tmp_path, context.readers)
    variants = (
        replace(context.brief, catalog_generation_fingerprint="d" * 64, research_brief_fingerprint=""),
        replace(context.brief, dataset_snapshot_fingerprint="d" * 64, research_brief_fingerprint=""),
        replace(
            context.brief,
            evaluation_context_reference=replace(
                context.brief.evaluation_context_reference, evaluation_fingerprint="d" * 64
            ),
            research_brief_fingerprint="",
        ),
    )
    for value in variants:
        with pytest.raises(OnlyAgentContextError) as raised:
            store.commit_research_brief(value)
        assert raised.value.code == "AGENT_RESEARCH_BRIEF_REFERENCE_INVALID"


def test_session_rejects_missing_wrong_kind_disagreement_and_unresolved_role_resource(tmp_path) -> None:
    context = make_context(tmp_path)
    resources = OnlyJsonAgentOrchestrationResourceStore(tmp_path)
    briefs = OnlyJsonAgentResearchBriefStore(tmp_path, context.readers)
    sessions = OnlyJsonAgentSessionManifestStore(tmp_path, briefs=briefs, resources=resources)
    with pytest.raises(OnlyAgentContextError):
        sessions.commit_session_manifest(context.session)
    briefs.commit_research_brief(context.brief)
    for item in context.resources:
        resources.commit_resource(item)
    bad_values = (
        replace(context.session, agent_workflow_source_revision="2" * 40, session_fingerprint=""),
        replace(
            context.session,
            workflow_implementation_resource_fingerprint=context.resources[0].resource_fingerprint,
            session_fingerprint="",
        ),
        replace(context.session, ordered_role_policy_fingerprints=("e" * 64,), session_fingerprint=""),
    )
    for value in bad_values:
        with pytest.raises(OnlyAgentContextError) as raised:
            sessions.commit_session_manifest(value)
        assert raised.value.code == "AGENT_SESSION_RESOURCE_MISMATCH"


def test_historical_session_load_is_runtime_independent_and_complete(tmp_path) -> None:
    context, _, _, sessions = _commit_context(tmp_path)
    verified = sessions.load_session_manifest_verified(context.session.session_fingerprint)
    assert verified.session == context.session
    assert verified.research_brief == context.brief
    assert len(verified.ordered_role_policy_resources) == 1
    assert {item.resource_kind for item in verified.supporting_resources} == {
        OnlyAgentOrchestrationResourceKind.PROMPT_TEMPLATE,
        OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA,
        OnlyAgentOrchestrationResourceKind.MODEL_EXECUTION_POLICY,
    }


def test_fresh_process_reconstructs_full_context_without_git_network_model_or_local_state(tmp_path) -> None:
    context, _, _, _ = _commit_context(tmp_path)
    script = """
import json, sys
from pathlib import Path
from onlyalpha.research.agent import OnlyAgentResearchBriefReferenceReadersV1, OnlyJsonAgentOrchestrationResourceStore, OnlyJsonAgentResearchBriefStore, OnlyJsonAgentSessionManifestStore
root = Path(sys.argv[1])
class Value:
    def __init__(self, **values): self.__dict__.update(values)
    @property
    def snapshot(self): return self
class External:
    def load(self): return json.loads((root / "external-authorities.json").read_text())
    def generation(self, fingerprint):
        if self.load()["catalog"] != fingerprint: raise LookupError(fingerprint)
        return Value(generation_fingerprint=fingerprint)
    def load_verified_table(self, fingerprint):
        if self.load()["dataset"] != fingerprint: raise LookupError(fingerprint)
        return Value(snapshot_fingerprint=fingerprint)
    def load_evaluation_context_verified(self, reference):
        if self.load()["evaluation"] != reference.to_dict(): raise LookupError(reference.evaluation_fingerprint)
        return Value(evaluation_kind=reference.evaluation_kind, evaluation_schema_version=reference.evaluation_schema_version, evaluation_fingerprint=reference.evaluation_fingerprint)
external = External()
readers = OnlyAgentResearchBriefReferenceReadersV1(external, external, external)
resources = OnlyJsonAgentOrchestrationResourceStore(root)
briefs = OnlyJsonAgentResearchBriefStore(root, readers)
sessions = OnlyJsonAgentSessionManifestStore(root, briefs=briefs, resources=resources)
verified = sessions.load_session_manifest_verified(sys.argv[2])
print(json.dumps({"session": verified.session.session_fingerprint, "brief": verified.research_brief.research_brief_fingerprint, "supporting": len(verified.supporting_resources)}, sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script, str(tmp_path), context.session.session_fingerprint],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "brief": context.brief.research_brief_fingerprint,
        "session": context.session.session_fingerprint,
        "supporting": 3,
    }
