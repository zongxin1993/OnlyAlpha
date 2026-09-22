from __future__ import annotations

import json
import os
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import threading
import tomllib
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import uvicorn
from fastapi import FastAPI
from onlyalpha_agent_orchestrator.config import OnlyOpenAICompatibleEndpointConfigV1
from onlyalpha_agent_orchestrator.provider_integration import (
    OnlyAgentModelProfileV1,
    OnlyAgentSessionProviderBindingV1,
    OnlyResolvedAgentProviderRuntimeV1,
)
from onlyalpha_http_server.agent_gateway import (
    OnlyAgentNodeGatewayConfigV1,
    OnlyAgentNodeHttpGatewayV1,
    create_agent_gateway_router,
)
from onlyalpha_http_server.agent_provider_runtime import create_agent_provider_runtime_router
from onlyalpha_http_server.research.catalog_context_routes import create_exact_catalog_context_router
from onlyalpha_http_server.research.exact_reference_routes import create_exact_reference_router
from onlyalpha_http_server.research.exact_statistics_routes import create_exact_statistics_router
from onlyalpha_http_server.research.routes import create_artifact_router
from onlyalpha_http_server.research.runtime_generation_routes import create_runtime_generation_router
from onlyalpha_http_server.research.search_authoring_routes import create_search_authoring_router
from onlyalpha_http_server.research.search_provenance_routes import create_search_provenance_router
from onlyalpha_http_server.search.routes import create_search_router
from onlyalpha_http_server.search.schema import (
    SearchCommandResponseDto,
    SearchExperimentResponseDto,
    SearchLedgerResponseDto,
    SearchTerminalResponseDto,
    SymbolicSearchSubmitRequestDto,
)

from onlyalpha.application.integration_configuration import OnlyIntegrationId
from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeBindingV1
from onlyalpha.canonical import only_canonical_json
from onlyalpha.plugin.integration import OnlyIntegrationCategory
from onlyalpha.research.agent.decision import (
    OnlyAgentDecisionKind,
    OnlyAgentEvaluationPathKind,
    OnlyAgentEvidenceObservationCodeV1,
    OnlyAgentEvidenceObservationV1,
    OnlyAgentFollowUpBriefDeltaV1,
    OnlyAgentNextExperimentProposalV1,
    OnlyAgentSymbolicSearchDirectiveV2,
)
from onlyalpha.research.agent.decision_store import (
    OnlyJsonAgentDecisionStore,
    OnlyJsonAgentExperimentLaunchStore,
)
from onlyalpha.research.agent.model import (
    OnlyAgentBudgetV1,
    OnlyAgentResearchBriefV2,
    OnlyAgentSearchMethod,
    OnlyAgentStructuredHypothesisV1,
    OnlyAgentToolClass,
)
from onlyalpha.research.agent.occurrence import OnlyAgentContextReferenceV1
from onlyalpha.research.agent.occurrence_store import (
    OnlyJsonAgentModelOccurrenceStore,
    OnlyJsonAgentToolOccurrenceStore,
)
from onlyalpha.research.experiment import (
    OnlySearchAlgorithmBindingV1,
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchEvaluationContextReferenceV1,
    OnlySearchExperimentManifestV2,
    OnlySearchHypothesisV1,
    OnlySearchRandomnessMode,
    OnlySearchSpaceReferenceV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.query import (
    OnlyResearchArtifactSummary,
    OnlyResearchNumericDescriptor,
    OnlyResearchSeriesReference,
    OnlyResearchStatisticsCatalog,
    OnlyResearchStatisticsDefinitionDescriptor,
    OnlyResearchStatisticsDescriptor,
)
from onlyalpha.research.search.symbolic import only_deterministic_enumeration_implementation
from tests.research.search.symbolic.support import space
from tests.research.search.symbolic.test_research_and_provenance_integration import _evaluation
from tests.runtime.search_ownership_support import _support_wheel

CATALOG, SEARCH_SPACE = space(max_nodes=1)
CATALOG_FP = CATALOG.generation_fingerprint
DATASET_FP = "a" * 64
EVALUATION = _evaluation(DATASET_FP)
ALGORITHM = only_deterministic_enumeration_implementation()
RUNTIME_FP = "b" * 64
ITERATION_FP = "c" * 64
TERMINAL_FP = "d" * 64
RESEARCH_RESULT_FP = "e" * 64
STATISTICS_RESULT_FP = "f" * 64
CONTROL_TOKEN = "agent-control-sentinel"
PRODUCT_TOKEN = "agent-product-sentinel"
MODEL_TOKEN = "agent-model-sentinel"
RUNTIME_TOKEN = "agent-runtime-sentinel"
ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class _Value:
    payload: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _CatalogProjection:
    catalog_generation_fingerprint = CATALOG_FP
    ordered_providers: tuple[object, ...] = ()
    ordered_calculation_capabilities: tuple[object, ...] = ()
    ordered_registered_universes: tuple[object, ...] = ()
    ordered_dataset_field_contracts: tuple[object, ...] = ()
    ordered_statistics_capabilities: tuple[object, ...] = ()
    projection_schema_fingerprint = "1" * 64
    projection_fingerprint = "2" * 64

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "ordered_providers": [],
            "ordered_calculation_capabilities": [],
            "ordered_registered_universes": [],
            "ordered_dataset_field_contracts": [],
            "ordered_statistics_capabilities": [],
            "projection_schema_fingerprint": self.projection_schema_fingerprint,
            "projection_fingerprint": self.projection_fingerprint,
        }


class _CatalogReader:
    def get_exact_catalog_context(self, fingerprint: str) -> _CatalogProjection:
        assert fingerprint == CATALOG_FP
        return _CatalogProjection()


class _ExactReferences:
    snapshot_fingerprint = DATASET_FP
    evaluation_contract_fingerprint = EVALUATION.evaluation_contract_fingerprint
    schema_version = EVALUATION.schema_version

    def load(self, fingerprint: str) -> _ExactReferences:
        assert fingerprint == DATASET_FP
        return self

    def load_evaluation_contract_intrinsic_verified(self, fingerprint: str) -> _ExactReferences:
        assert fingerprint == EVALUATION.evaluation_contract_fingerprint
        return self


class _RuntimeGenerations:
    def projection(self) -> object:
        return SimpleNamespace(active_for_new_work=RUNTIME_FP)

    def require_runtime_generation(self, runtime_generation_fingerprint: str) -> object:
        assert runtime_generation_fingerprint == RUNTIME_FP
        return SimpleNamespace(runtime_generation_fingerprint=runtime_generation_fingerprint)


class _Authoring:
    values = {
        ("SYMBOLIC_SEARCH_SPACE", SEARCH_SPACE.search_space_fingerprint): SEARCH_SPACE,
        ("SEARCH_ALGORITHM", ALGORITHM.implementation_fingerprint): ALGORITHM,
        ("RESEARCH_EVALUATION", EVALUATION.evaluation_contract_fingerprint): EVALUATION,
    }

    def load_search_authoring_input_verified(self, kind: str, fingerprint: str) -> object:
        return self.values[(kind, fingerprint)]


class _SearchAuthority:
    def __init__(self) -> None:
        self.experiment: OnlySearchExperimentManifestV2 | None = None
        self.phase = 0
        self.command_ids: list[str] = []
        self.responses: dict[str, SearchCommandResponseDto] = {}
        self.submit_count = 0
        self.advance_count = 0

    def submit_symbolic(self, command_id: str, request: SymbolicSearchSubmitRequestDto) -> SearchCommandResponseDto:
        if command_id in self.responses:
            return self.responses[command_id].model_copy(update={"replayed": True})
        self.submit_count += 1
        search_space = SEARCH_SPACE.from_dict(request.search_space)
        evaluation = EVALUATION.from_dict(request.evaluation_contract)
        algorithm = ALGORITHM.from_dict(request.algorithm_manifest)
        self.experiment = OnlySearchExperimentManifestV2(
            OnlySearchHypothesisV1.from_dict(request.hypothesis),
            OnlySearchAlgorithmBindingV1(
                algorithm.algorithm_id,
                algorithm.algorithm_semantic_version,
                algorithm.implementation_fingerprint,
                algorithm.source_revision,
            ),
            OnlySearchSpaceReferenceV1(
                "ONLY_SYMBOLIC_FACTOR_SEARCH_SPACE",
                search_space.schema_version,
                search_space.search_space_fingerprint,
            ),
            OnlySearchEvaluationContextReferenceV1(
                "ONLY_SYMBOLIC_RESEARCH_EVALUATION_CONTRACT",
                evaluation.schema_version,
                evaluation.evaluation_contract_fingerprint,
            ),
            OnlySearchRandomnessMode.NONE,
            None,
            OnlySearchBudgetV1.from_dict(request.search_budget),
            request.catalog_generation_fingerprint,
            request.dataset_snapshot_fingerprint,
            OnlySearchWorkflowBindingV1.from_dict(request.workflow_binding),
            OnlySearchDecisionEngineBindingV1.from_dict(request.decision_engine_binding),
            request.parent_experiment_fingerprint,
        )
        response = self._command(command_id)
        self.command_ids.append(command_id)
        self.responses[command_id] = response
        return response

    def submit_parameter(self, *_args: object) -> object:
        raise AssertionError("PARAMETER_SEARCH_NOT_ALLOWED")

    def advance_symbolic(self, command_id: str, request: object) -> SearchCommandResponseDto:
        if command_id in self.responses:
            return self.responses[command_id].model_copy(update={"replayed": True})
        expected = cast(Any, request).expected_state
        assert expected == self._expected_state()
        operation = cast(Any, request).operation
        assert operation == (
            "ADVANCE_ONE_SYMBOLIC_OCCURRENCE" if self.phase == 0 else "RECONCILE_ONE_SYMBOLIC_OCCURRENCE"
        )
        self.phase += 1
        self.advance_count += 1
        response = self._command(command_id)
        self.command_ids.append(command_id)
        self.responses[command_id] = response
        return response

    def advance_parameter(self, *_args: object) -> object:
        raise AssertionError("PARAMETER_SEARCH_NOT_ALLOWED")

    def get_experiment(self, fingerprint: str) -> SearchExperimentResponseDto:
        experiment = self._experiment(fingerprint)
        return SearchExperimentResponseDto(
            experiment_fingerprint=fingerprint,
            method="SYMBOLIC",
            experiment=cast(dict[str, Any], experiment.to_dict()),
        )

    def get_ledger(self, fingerprint: str) -> SearchLedgerResponseDto:
        self._experiment(fingerprint)
        return SearchLedgerResponseDto(
            experiment_fingerprint=fingerprint,
            method="SYMBOLIC",
            ledger=cast(dict[str, Any], self._ledger()),
        )

    def get_terminal(self, fingerprint: str) -> SearchTerminalResponseDto:
        self._experiment(fingerprint)
        return SearchTerminalResponseDto(
            experiment_fingerprint=fingerprint,
            method="SYMBOLIC",
            terminal_kind=("TERMINAL_SYMBOLIC_COMPLETION" if self.phase == 2 else "NON_TERMINAL"),
            terminal_fact=(self._terminal_fact() if self.phase == 2 else None),
            stop_reason=("SEARCH_SPACE_EXHAUSTED" if self.phase == 2 else None),
        )

    def load_iteration_result_verified(self, fingerprint: str) -> _Value:
        assert fingerprint == ITERATION_FP and self.phase == 2
        return _Value(self._iteration_result())

    def load_terminal_projection_verified(self, fingerprint: str) -> _Value:
        assert fingerprint == TERMINAL_FP and self.phase == 2
        return _Value(self._terminal_fact())

    def _experiment(self, fingerprint: str) -> OnlySearchExperimentManifestV2:
        assert self.experiment is not None and self.experiment.experiment_fingerprint == fingerprint
        return self.experiment

    def _expected_state(self) -> dict[str, object]:
        plan_states = []
        if self.phase:
            plan_states = [
                {
                    "plan_fingerprint": "3" * 64,
                    "result_fingerprint": ITERATION_FP if self.phase == 2 else None,
                    "research_product_command_id": "00000000-0000-4000-8000-000000000101",
                    "research_receipt_outcome_id": "00000000-0000-4000-8000-000000000102",
                }
            ]
        return {
            "schema_version": 1,
            "experiment_fingerprint": self._experiment_fingerprint(),
            "enumeration_result_fingerprint": TERMINAL_FP,
            "ordered_plan_states": plan_states,
            "next_iteration_ordinal": 1 if self.phase else 0,
            "research_attempt_count": 1 if self.phase else 0,
            "qualification_attempt_count": 0,
            "target_plan_fingerprint": ("3" * 64 if self.phase == 1 else None),
        }

    def _ledger(self) -> dict[str, object]:
        return {
            "method": "SYMBOLIC",
            "experiment_fingerprint": self._experiment_fingerprint(),
            "plans": ([{"iteration_plan_fingerprint": "3" * 64}] if self.phase else []),
            "results": ([self._iteration_result() if self.phase == 2 else None] if self.phase else []),
            "expected_state": self._expected_state(),
            "enumeration_result": self._terminal_fact(),
            "feedback_decisions": [],
            "frontier_fingerprint": None,
        }

    @staticmethod
    def _iteration_result() -> dict[str, object]:
        return {
            "schema_version": 1,
            "iteration_result_fingerprint": ITERATION_FP,
            "research_result_reference": {"result_fingerprint": RESEARCH_RESULT_FP},
        }

    @staticmethod
    def _terminal_fact() -> dict[str, object]:
        return {"schema_version": 1, "enumeration_result_fingerprint": TERMINAL_FP}

    def _experiment_fingerprint(self) -> str:
        assert self.experiment is not None
        return self.experiment.experiment_fingerprint

    def _command(self, command_id: str) -> SearchCommandResponseDto:
        return SearchCommandResponseDto(
            product_command_id=command_id,
            experiment_fingerprint=self._experiment_fingerprint(),
            method="SYMBOLIC",
            receipt={"command_id": command_id},
            ledger=cast(dict[str, Any], self._ledger()),
            terminal={
                "method": "SYMBOLIC",
                "experiment_fingerprint": self._experiment_fingerprint(),
                "terminal_kind": "TERMINAL_SYMBOLIC_COMPLETION" if self.phase == 2 else "NON_TERMINAL",
                "terminal_fact": self._terminal_fact() if self.phase == 2 else None,
                "stop_reason": "SEARCH_SPACE_EXHAUSTED" if self.phase == 2 else None,
            },
            replayed=False,
        )


def _statistics_catalog() -> OnlyResearchStatisticsCatalog:
    series = OnlyResearchSeriesReference("4" * 64, "5" * 64, "value")
    definition = OnlyResearchStatisticsDefinitionDescriptor(
        "SPEARMAN",
        2,
        "PAIRWISE_COMPLETE",
        "CROSS_SECTIONAL",
        "AVERAGE",
        "EQUAL",
        OnlyResearchNumericDescriptor("DECIMAL", 18, Decimal("0.000001"), "ROUND_HALF_EVEN"),
    )
    descriptor = OnlyResearchStatisticsDescriptor(
        "6" * 64,
        STATISTICS_RESULT_FP,
        "7" * 64,
        1,
        1,
        series,
        series,
        definition,
    )
    return OnlyResearchStatisticsCatalog(RESEARCH_RESULT_FP, (descriptor,))


class _Artifacts:
    def get_artifact_summary(self, fingerprint: str) -> OnlyResearchArtifactSummary:
        assert fingerprint == RESEARCH_RESULT_FP
        return OnlyResearchArtifactSummary(
            "8" * 64,
            "9" * 64,
            RESEARCH_RESULT_FP,
            DATASET_FP,
            "0" * 64,
            1,
            "RESEARCH",
            1,
            1,
            1,
            datetime(2026, 9, 12, tzinfo=UTC),
            candidate_count=1,
        )

    def list_statistics(self, fingerprint: str) -> OnlyResearchStatisticsCatalog:
        assert fingerprint == RESEARCH_RESULT_FP
        return _statistics_catalog()


class _Statistics:
    def load_verified(self, fingerprint: str) -> object:
        assert fingerprint == STATISTICS_RESULT_FP
        manifest = _Value({"schema_version": 1, "statistics_result_fingerprint": STATISTICS_RESULT_FP})
        return SimpleNamespace(
            manifest=SimpleNamespace(
                statistics_result_fingerprint=STATISTICS_RESULT_FP,
                to_dict=manifest.to_dict,
            ),
            rows=(_Value({"metric": "0.25"}),),
        )


def _brief() -> OnlyAgentResearchBriefV2:
    return OnlyAgentResearchBriefV2(
        OnlyAgentStructuredHypothesisV1(
            "symbolic-e2e",
            "Momentum is explanatory.",
            "Deterministic bounded certification.",
            "Positive association.",
            (),
            ("No association.",),
        ),
        CATALOG_FP,
        DATASET_FP,
        OnlySearchEvaluationContextReferenceV1(
            "ONLY_SYMBOLIC_RESEARCH_EVALUATION_CONTRACT",
            EVALUATION.schema_version,
            EVALUATION.evaluation_contract_fingerprint,
        ),
        (OnlyAgentSearchMethod.SYMBOLIC_SEARCH,),
        OnlyAgentBudgetV1(4, 6),
        OnlySearchBudgetV1(1, 1, 1),
        tuple(
            sorted(
                (
                    OnlyAgentContextReferenceV1("SEARCH_ALGORITHM", 1, ALGORITHM.implementation_fingerprint),
                    OnlyAgentContextReferenceV1("SYMBOLIC_SEARCH_SPACE", 1, SEARCH_SPACE.search_space_fingerprint),
                )
            )
        ),
    )


def _model_outputs(brief: OnlyAgentResearchBriefV2) -> dict[str, Mapping[str, object]]:
    statistic = OnlyAgentContextReferenceV1("RESEARCH_STATISTICS", 1, STATISTICS_RESULT_FP)
    directive = OnlyAgentSymbolicSearchDirectiveV2(
        OnlyAgentContextReferenceV1("SYMBOLIC_SEARCH_SPACE", 1, SEARCH_SPACE.search_space_fingerprint),
        OnlyAgentContextReferenceV1("RESEARCH_EVALUATION", 1, EVALUATION.evaluation_contract_fingerprint),
        OnlyAgentContextReferenceV1("SEARCH_ALGORITHM", 1, ALGORITHM.implementation_fingerprint),
        brief.requested_child_search_budget_fingerprint,
    )
    proposal = OnlyAgentNextExperimentProposalV1(
        OnlyAgentEvaluationPathKind.CHILD_SEARCH,
        OnlyAgentContextReferenceV1("SEARCH_TERMINAL_PROJECTION", 1, TERMINAL_FP),
        (OnlyAgentContextReferenceV1("RESEARCH_RESULT", 1, RESEARCH_RESULT_FP),),
        (statistic,),
        (OnlyAgentEvidenceObservationV1(OnlyAgentEvidenceObservationCodeV1.FOLLOW_UP_RECOMMENDED, (statistic,)),),
        OnlyAgentFollowUpBriefDeltaV1("refine", "bounded evidence", ("narrow scope",)),
    )
    return {
        "action": {"action": "PLAN"},
        "router_action": {"router_action": "SYMBOLIC_SEARCH"},
        "action_payload": {"action_payload": directive.to_dict()},
        "evaluation_path_kind": proposal.to_dict(),
    }


def _model_app(outputs: Mapping[str, Mapping[str, object]], calls: list[str]) -> FastAPI:
    app = FastAPI()

    @app.post("/chat/completions")
    def complete(request: dict[str, object]) -> dict[str, object]:
        schema = cast(dict[str, Any], cast(dict[str, Any], request["response_format"])["json_schema"])["schema"]
        properties = cast(dict[str, object], schema["properties"])
        discriminator = next(item for item in outputs if item in properties)
        calls.append(discriminator)
        return {"choices": [{"message": {"content": only_canonical_json(outputs[discriminator]), "refusal": None}}]}

    return app


def _runtime_authority_app(model_url: str) -> tuple[FastAPI, OnlyAgentModelProfileV1]:
    binding = OnlyIntegrationRuntimeBindingV1(
        OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        "8" * 64,
        "openai.compatible.agent_provider",
        OnlyIntegrationCategory.AGENT_PROVIDER,
        "9" * 64,
        "7" * 64,
    )
    profile = OnlyAgentModelProfileV1(
        binding.integration_id.value,
        binding.revision_fingerprint,
        binding.runtime_configuration_fingerprint,
        "onlyalpha-research-v1",
        "2026-09-01",
        ("CHAT", "STRUCTURED_OUTPUT"),
    )
    runtime = OnlyResolvedAgentProviderRuntimeV1(
        binding,
        profile,
        OnlyOpenAICompatibleEndpointConfigV1(
            model_url,
            MODEL_TOKEN,
            "openai-compatible",
            profile.model_id,
            profile.model_version,
        ),
    )

    class Resolver:
        def admit_new(self, selected):  # type: ignore[no-untyped-def]
            assert selected == profile
            return runtime

        def continue_exact(self, evidence, selected):  # type: ignore[no-untyped-def]
            assert isinstance(evidence, OnlyAgentSessionProviderBindingV1)
            assert evidence.provider_binding == binding
            assert selected == profile
            return runtime

    app = FastAPI()
    app.include_router(create_agent_provider_runtime_router(Resolver(), RUNTIME_TOKEN))  # type: ignore[arg-type]
    return app, profile


def _product_app(agent_url: str, search: _SearchAuthority) -> FastAPI:
    app = FastAPI()

    exact = _ExactReferences()
    app.include_router(
        create_agent_gateway_router(OnlyAgentNodeHttpGatewayV1(OnlyAgentNodeGatewayConfigV1(agent_url, CONTROL_TOKEN)))
    )
    app.include_router(create_exact_catalog_context_router(cast(Any, _CatalogReader())))
    app.include_router(create_exact_reference_router(cast(Any, exact), cast(Any, exact)))
    app.include_router(create_runtime_generation_router(cast(Any, _RuntimeGenerations())))
    app.include_router(create_search_authoring_router(cast(Any, _Authoring())))
    app.include_router(create_search_router(search))
    app.include_router(create_search_provenance_router(search, search))
    app.include_router(create_artifact_router(cast(Any, _Artifacts())))
    app.include_router(create_exact_statistics_router(cast(Any, _Statistics())))
    return app


@contextmanager
def _serve(app: FastAPI) -> Iterator[str]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    started = threading.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        started.set()
        yield

    cast(Any, app.router).lifespan_context = lifespan

    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    assert started.wait(10), "HTTP server startup barrier timed out"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive()


def _free_port() -> int:
    value = socket.socket()
    value.bind(("127.0.0.1", 0))
    port = value.getsockname()[1]
    value.close()
    return cast(int, port)


def _installed_agent(root: Path) -> tuple[Path, dict[str, str]]:
    uv = shutil.which("uv")
    assert uv is not None
    artifacts = root / "artifacts"
    artifacts.mkdir()
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        environment.pop(name, None)
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never"})
    for package in ("onlyalpha", "onlyalpha-agent-orchestrator"):
        subprocess.run(
            [
                uv,
                "build",
                "--offline",
                "--no-build-isolation",
                "--wheel",
                "--package",
                package,
                "--out-dir",
                str(artifacts),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    locked = {
        item["name"]: item["version"]
        for item in tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]
    }
    dependency_names = (
        "annotated-types",
        "annotated-doc",
        "anyio",
        "click",
        "cffi",
        "cryptography",
        "fastapi",
        "h11",
        "idna",
        "pycparser",
        "pydantic",
        "pydantic-core",
        "psycopg",
        "psycopg-binary",
        "pyarrow",
        "pyyaml",
        "starlette",
        "typing-extensions",
        "typing-inspection",
        "tzdata",
        "uvicorn",
    )
    constraints = root / "constraints.txt"
    constraints.write_text(
        "".join(f"{name}=={locked[name]}\n" for name in dependency_names),
        encoding="utf-8",
    )
    support_wheels = root / "runtime-support-wheels"
    for name in dependency_names:
        if name == "tzdata" and sys.platform != "win32":
            continue
        _support_wheel(name, support_wheels)
    runtime = root / "runtime"
    subprocess.run(
        [uv, "venv", "--offline", "--no-project", "--python", sys.executable, str(runtime)],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheels = (
        next(artifacts.glob("onlyalpha-[0-9]*.whl")),
        next(artifacts.glob("onlyalpha_agent_orchestrator-*.whl")),
    )
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--offline",
            "--no-build",
            "--strict",
            "--constraint",
            str(constraints),
            "--find-links",
            str(support_wheels),
            "--python",
            str(python),
            *(str(item) for item in wheels),
        ],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    executable = runtime / ("Scripts/onlyalpha-agent.exe" if os.name == "nt" else "bin/onlyalpha-agent")
    runtime_environment = dict(environment)
    runtime_environment["PATH"] = str(executable.parent)
    return executable, runtime_environment


def _start_agent(
    root: Path,
    product_url: str,
    runtime_authority_url: str,
    port: int,
    executable: Path,
    environment: Mapping[str, str],
) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [
            executable,
            "serve",
            "--durable-root",
            str(root / "facts"),
            "--coordination-root",
            str(root / "locks"),
            "--product-api-url",
            product_url,
            "--product-api-contract",
            str(Path(__file__).resolve().parents[3] / "contracts/product-api/v2/openapi.json"),
            "--product-token-file",
            str(root / "product.secret"),
            "--model-configuration-mode",
            "INTEGRATION_REVISION",
            "--integration-runtime-authority-url",
            runtime_authority_url + "/internal/v1/agent-provider-runtime",
            "--integration-runtime-authority-token-file",
            str(root / "runtime.secret"),
            "--allow-insecure-runtime-authority-transport",
            "--model-profile-file",
            str(root / "model-profile.json"),
            "--control-token-file",
            str(root / "control.secret"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=root,
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    selector = selectors.DefaultSelector()
    assert process.stderr is not None
    selector.register(process.stderr, selectors.EVENT_READ)
    lines: list[str] = []
    while "Application startup complete." not in "".join(lines):
        assert selector.select(timeout=20), "Agent startup barrier timed out"
        lines.append(process.stderr.readline())
        assert process.poll() is None, "Agent exited during startup: " + "".join(lines)
    return process


def _stop_agent(process: subprocess.Popen[str]) -> tuple[str, str]:
    process.send_signal(signal.SIGTERM)
    try:
        output = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        output = process.communicate(timeout=10)
    assert process.returncode in (0, -signal.SIGTERM, -signal.SIGKILL)
    return output


def _post(url: str, payload: Mapping[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=only_canonical_json(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return cast(dict[str, object], json.loads(response.read()))
    except urllib.error.HTTPError as error:
        raise AssertionError((error.code, error.read().decode())) from error


def _get(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
        return cast(dict[str, object], json.loads(response.read()))


def test_packaged_symbolic_search_process_restarts_and_completes_exactly_once(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    for name, value in (
        ("product.secret", PRODUCT_TOKEN),
        ("runtime.secret", RUNTIME_TOKEN),
        ("control.secret", CONTROL_TOKEN),
    ):
        (root / name).write_text(value + "\n", encoding="utf-8")
    brief = _brief()
    executable, environment = _installed_agent(root)
    search = _SearchAuthority()
    model_calls: list[str] = []
    agent_port = _free_port()
    agent_url = f"http://127.0.0.1:{agent_port}"
    agent_outputs: list[tuple[str, str]] = []
    with _serve(_model_app(_model_outputs(brief), model_calls)) as model_url:
        runtime_app, profile = _runtime_authority_app(model_url)
        (root / "model-profile.json").write_text(only_canonical_json(profile.to_dict()), encoding="utf-8")
        with _serve(runtime_app) as runtime_url, _serve(_product_app(agent_url, search)) as product_url:
            process = _start_agent(root, product_url, runtime_url, agent_port, executable, environment)
            try:
                assert _get(agent_url + "/internal/v1/healthz") == {"status": "ALIVE"}
                assert _get(agent_url + "/internal/v1/readyz") == {"status": "READY"}
                admitted = _post(product_url + "/api/v2/agent/sessions", {"research_brief": brief.to_dict()})
                session = cast(str, admitted["session_fingerprint"])
                for _ in range(6):
                    try:
                        _post(product_url + f"/api/v2/agent/sessions/{session}/advance", {})
                    except TimeoutError as error:
                        raise AssertionError(model_calls) from error
            finally:
                if process.poll() is None:
                    agent_outputs.append(_stop_agent(process))

            process = _start_agent(root, product_url, runtime_url, agent_port, executable, environment)
            try:
                for _ in range(30):
                    try:
                        state = _post(product_url + f"/api/v2/agent/sessions/{session}/advance", {})
                    except (AssertionError, TimeoutError) as error:
                        logs = _stop_agent(process)
                        raise AssertionError((model_calls, search.command_ids, logs)) from error
                    if state["derived_status"] == "COMPLETE":
                        break
                else:
                    raise AssertionError("production Session did not reach COMPLETE")

                facts_before = tuple(sorted(path.read_bytes() for path in (root / "facts").rglob("manifest.json")))
                calls_before = (tuple(model_calls), tuple(search.command_ids))
                extra = _post(product_url + f"/api/v2/agent/sessions/{session}/advance", {})
                facts_after = tuple(sorted(path.read_bytes() for path in (root / "facts").rglob("manifest.json")))
            finally:
                if process.poll() is None:
                    agent_outputs.append(_stop_agent(process))

    models = OnlyJsonAgentModelOccurrenceStore(root / "facts")
    tools = OnlyJsonAgentToolOccurrenceStore(root / "facts")
    decisions = OnlyJsonAgentDecisionStore(root / "facts")
    launches = OnlyJsonAgentExperimentLaunchStore(root / "facts")
    assert extra["derived_status"] == "COMPLETE"
    assert facts_after == facts_before
    assert calls_before == (tuple(model_calls), tuple(search.command_ids))
    assert model_calls == ["action", "router_action", "action_payload", "evaluation_path_kind"]
    assert len(set(search.command_ids)) == len(search.command_ids) == 3
    assert search.submit_count == 1
    assert search.advance_count == 2
    provider_binding = json.loads(
        (root / "facts/research/agent-orchestration/provider-bindings" / session / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert provider_binding["provider_binding"]["revision_fingerprint"] == "8" * 64
    assert provider_binding["model_profile_fingerprint"] == profile.model_profile_fingerprint
    assert models.budget_consumed(session) == 4
    assert tools.budget_consumed(session) == 6
    assert decisions.contiguous_count(session) == 3
    admitted_decisions = tuple(
        decisions.load_decision_by_session_ordinal_verified(session, ordinal) for ordinal in range(3)
    )
    assert tuple(item.decision_ordinal for item in admitted_decisions) == (0, 1, 2)
    assert tuple(item.decision_kind for item in admitted_decisions) == (
        OnlyAgentDecisionKind.RESEARCH_PLAN,
        OnlyAgentDecisionKind.SEARCH_DIRECTIVE,
        OnlyAgentDecisionKind.NEXT_EXPERIMENT_PROPOSAL,
    )
    admitted_tools = tuple(tools.load_plan_by_session_ordinal_verified(session, ordinal) for ordinal in range(6))
    assert tuple(item.tool_call_ordinal for item in admitted_tools) == tuple(range(6))
    assert tuple(item.tool_class for item in admitted_tools) == (
        OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        OnlyAgentToolClass.SYMBOLIC_SEARCH,
        OnlyAgentToolClass.SYMBOLIC_SEARCH,
        OnlyAgentToolClass.SYMBOLIC_SEARCH,
        OnlyAgentToolClass.SEARCH_QUERY,
        OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY,
    )
    command_ids = tuple(
        item.product_command_id_or_idempotency_key
        for item in admitted_tools
        if item.product_command_id_or_idempotency_key is not None
    )
    assert command_ids == tuple(search.command_ids)
    assert len(set(command_ids)) == 3
    assert all(tools.result_exists(item.tool_call_plan_fingerprint) for item in admitted_tools)
    analyst = models.load_plan_by_session_ordinal_verified(session, 3)
    assert tuple((item.reference_kind, item.locator_value) for item in analyst.ordered_context_references) == (
        ("SEARCH_TERMINAL_PROJECTION", TERMINAL_FP),
        ("RESEARCH_RESULT", RESEARCH_RESULT_FP),
        ("RESEARCH_STATISTICS", STATISTICS_RESULT_FP),
    )
    assert launches.launch_exists(session)
    launch_files = tuple((root / "facts/research/agent-orchestration/launch-records/sha256").glob("*/*/manifest.json"))
    assert len(launch_files) == 1
    assert search.experiment is not None
    assert search.experiment.search_budget == brief.requested_child_search_budget
    all_bytes = b"".join(path.read_bytes() for path in (root / "facts").rglob("*") if path.is_file())
    for secret in (CONTROL_TOKEN, PRODUCT_TOKEN, MODEL_TOKEN, RUNTIME_TOKEN):
        assert secret.encode() not in all_bytes
        assert secret not in "".join(value for output in agent_outputs for value in output)
