"""Exact validation, artifacts and execution bindings for DB-native Private Factor V1."""

from __future__ import annotations

import ast
import hashlib
import multiprocessing
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.decimal_execution import ONLY_DECIMAL_EXECUTION_POLICY_V1
from onlyalpha.calculation.definition import (
    FACTOR_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeDefinition,
    OnlyCalculationTypeReference,
    OnlyFactorKind,
    OnlyInputDefinition,
    OnlyMissingValuePolicy,
    OnlyNumericDefinition,
    OnlyOutputDefinition,
    OnlyParameterDefinition,
    OnlyParameterSchema,
    OnlyParameterType,
    OnlyPreReadyOutput,
    OnlyTimestampSemantic,
    OnlyWarmupDefinition,
)
from onlyalpha.calculation.implementation import (
    OnlyCalculationImplementationManifest,
    OnlyCalculationSemanticDependency,
    OnlyCalculationStateCapability,
    only_implementation_manifest_from_bytes,
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration
from onlyalpha.calculation.value_semantics import OnlyCanonicalValueSemanticsV1
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.quant_assets.private import OnlyPrivateFactorRevision, only_private_factor_source_sha256


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


_OPERATIONS = (
    "add",
    "and_",
    "coalesce",
    "div",
    "eq",
    "ge",
    "gt",
    "is_missing",
    "le",
    "lt",
    "max",
    "min",
    "mul",
    "ne",
    "negate",
    "not_",
    "or_",
    "sub",
    "where",
)
_ADAPTER_FINGERPRINTS = {
    "RESEARCH": only_canonical_fingerprint({"adapter": "ONLYALPHA_PRIVATE_FACTOR_RESEARCH_V1"}),
    "TRADING": only_canonical_fingerprint({"adapter": "ONLYALPHA_PRIVATE_FACTOR_TRADING_V1"}),
}

ONLY_PRIVATE_FACTOR_NUMERIC_V1 = OnlyNumericDefinition(
    representation="DECIMAL",
    precision=38,
    output_quantum=Decimal("0.000000000001"),
    rounding=ROUND_HALF_EVEN,
)


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorApiContractV1:
    api_version: int = 1
    contract_name: str = "ONLYALPHA_PRIVATE_FACTOR_API_V1"

    @property
    def api_contract_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "contract": self.contract_name,
                "api_version": self.api_version,
                "operations": list(_OPERATIONS),
                "values": "NONE_OR_EXACT_DECIMAL_INTEGER_BOOLEAN",
                "missing": "NONE_PROPAGATES_EXCEPT_IS_MISSING_COALESCE_AND_OR",
                "division_by_zero": "NONE",
                "condition": "TRUE_FALSE_NONE;NONE_RETURNS_NONE",
                "ordering": "DECLARED_OUTPUT_ORDER",
                "errors": "INVALID_VALUE_OR_EXECUTION_FAILED",
                "decimal_execution_policy": ONLY_DECIMAL_EXECUTION_POLICY_V1.fingerprint,
                "numeric": {
                    "representation": ONLY_PRIVATE_FACTOR_NUMERIC_V1.representation,
                    "precision": ONLY_PRIVATE_FACTOR_NUMERIC_V1.precision,
                    "output_quantum": str(ONLY_PRIVATE_FACTOR_NUMERIC_V1.output_quantum),
                    "rounding": ONLY_PRIVATE_FACTOR_NUMERIC_V1.rounding,
                },
                "determinism": "STATELESS_POINTWISE",
            }
        )


ONLY_PRIVATE_FACTOR_API_V1 = OnlyPrivateFactorApiContractV1()


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorValidationPolicyV1:
    policy_name: str = "ONLYALPHA_PRIVATE_FACTOR_VALIDATION_V1"

    @property
    def validation_policy_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "policy": self.policy_name,
                "entrypoint": "calculate(api, inputs, parameters)",
                "allowed_operations": list(_OPERATIONS),
                "imports": False,
                "helpers": False,
                "builtins": False,
                "state": False,
            }
        )


ONLY_PRIVATE_FACTOR_VALIDATION_POLICY_V1 = OnlyPrivateFactorValidationPolicyV1()


class OnlyPrivateFactorValidationDisposition(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorValidationEvidenceV1:
    revision_fingerprint: str
    source_sha256: str
    factor_api_version: int
    factor_api_contract_fingerprint: str
    validation_policy_fingerprint: str
    entrypoint_signature_fingerprint: str
    input_contract_fingerprint: str
    parameter_contract_fingerprint: str
    output_contract_fingerprint: str
    validation_disposition: OnlyPrivateFactorValidationDisposition
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (
            self.revision_fingerprint,
            self.source_sha256,
            self.factor_api_contract_fingerprint,
            self.validation_policy_fingerprint,
            self.entrypoint_signature_fingerprint,
            self.input_contract_fingerprint,
            self.parameter_contract_fingerprint,
            self.output_contract_fingerprint,
        ):
            if not _is_sha(value):
                raise ValueError("PRIVATE_FACTOR_VALIDATION_EVIDENCE_INVALID")
        if (self.validation_disposition is OnlyPrivateFactorValidationDisposition.PASS) == bool(self.errors):
            raise ValueError("PRIVATE_FACTOR_VALIDATION_EVIDENCE_INVALID")

    @property
    def validation_evidence_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            name: (value.value if isinstance(value, StrEnum) else list(value) if isinstance(value, tuple) else value)
            for name, value in ((field, getattr(self, field)) for field in self.__dataclass_fields__)
        }


class _SourcePolicy(ast.NodeVisitor):
    _allowed = (
        ast.Module,
        ast.FunctionDef,
        ast.arguments,
        ast.arg,
        ast.Assign,
        ast.Return,
        ast.If,
        ast.While,
        ast.Expr,
        ast.Name,
        ast.Load,
        ast.Store,
        ast.Constant,
        ast.Dict,
        ast.Tuple,
        ast.List,
        ast.Subscript,
        ast.Call,
        ast.Attribute,
    )

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, self._allowed):
            raise ValueError(f"PRIVATE_FACTOR_FORBIDDEN_AST:{type(node).__name__}")
        super().generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            not isinstance(node.func, ast.Attribute)
            or not isinstance(node.func.value, ast.Name)
            or node.func.value.id != "api"
            or node.func.attr not in _OPERATIONS
            or node.keywords
        ):
            raise ValueError("PRIVATE_FACTOR_FORBIDDEN_CALL")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if not isinstance(node.value, ast.Name) or node.value.id != "api" or node.attr not in _OPERATIONS:
            raise ValueError("PRIVATE_FACTOR_FORBIDDEN_ATTRIBUTE")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__") or node.id in {
            "eval",
            "exec",
            "compile",
            "open",
            "input",
            "globals",
            "locals",
            "vars",
            "getattr",
            "setattr",
            "delattr",
        }:
            raise ValueError("PRIVATE_FACTOR_FORBIDDEN_NAME")


def only_validate_private_factor_revision(revision: OnlyPrivateFactorRevision) -> OnlyPrivateFactorValidationEvidenceV1:
    errors: list[str] = []
    if revision.factor_api_version != 1:
        errors.append("PRIVATE_FACTOR_API_VERSION_UNSUPPORTED")
    if revision.factor_api_contract_fingerprint != ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint:
        errors.append("PRIVATE_FACTOR_API_CONTRACT_MISMATCH")
    if revision.source_sha256 != only_private_factor_source_sha256(revision.source_text):
        errors.append("PRIVATE_FACTOR_SOURCE_HASH_MISMATCH")
    try:
        tree = ast.parse(revision.source_text, mode="exec")
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if (
            len(tree.body) != 1
            or len(functions) != 1
            or not isinstance(functions[0], ast.FunctionDef)
            or functions[0].name != "calculate"
        ):
            raise ValueError("PRIVATE_FACTOR_ENTRYPOINT_INVALID")
        function = functions[0]
        args = function.args
        if (
            [item.arg for item in args.args] != ["api", "inputs", "parameters"]
            or args.posonlyargs
            or args.kwonlyargs
            or args.vararg
            or args.kwarg
            or args.defaults
            or args.kw_defaults
            or function.decorator_list
        ):
            raise ValueError("PRIVATE_FACTOR_ENTRYPOINT_SIGNATURE_INVALID")
        _SourcePolicy().visit(tree)
    except (SyntaxError, ValueError) as exc:
        errors.append(str(exc))
    return OnlyPrivateFactorValidationEvidenceV1(
        revision.revision_fingerprint,
        revision.source_sha256,
        revision.factor_api_version,
        revision.factor_api_contract_fingerprint,
        ONLY_PRIVATE_FACTOR_VALIDATION_POLICY_V1.validation_policy_fingerprint,
        only_canonical_fingerprint({"entrypoint": "calculate(api, inputs, parameters)"}),
        only_canonical_fingerprint(revision.input_contract),
        only_canonical_fingerprint(revision.parameter_contract),
        only_canonical_fingerprint(revision.output_contract),
        OnlyPrivateFactorValidationDisposition.FAIL if errors else OnlyPrivateFactorValidationDisposition.PASS,
        tuple(errors),
    )


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorSourceArtifactManifestV1:
    factor_id: str
    semantic_version: str
    revision_fingerprint: str
    source_sha256: str
    source_size: int
    factor_api_version: int
    factor_api_contract_fingerprint: str
    validation_policy_fingerprint: str
    validation_evidence_fingerprint: str

    @property
    def source_artifact_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.__dataclass_fields__}
        if include_fingerprint:
            result["source_artifact_fingerprint"] = self.source_artifact_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateFactorSourceArtifactManifestV1:
        fields = set(cls.__dataclass_fields__)
        if set(payload) != fields | {"source_artifact_fingerprint"}:
            raise ValueError("PRIVATE_FACTOR_SOURCE_ARTIFACT_MISMATCH")
        result = cls(*(payload[name] for name in cls.__dataclass_fields__))  # type: ignore[arg-type]
        if payload["source_artifact_fingerprint"] != result.source_artifact_fingerprint:
            raise ValueError("PRIVATE_FACTOR_SOURCE_ARTIFACT_MISMATCH")
        return result

    @classmethod
    def materialize(
        cls, revision: OnlyPrivateFactorRevision, evidence: OnlyPrivateFactorValidationEvidenceV1
    ) -> tuple[OnlyPrivateFactorSourceArtifactManifestV1, bytes]:
        if (
            evidence != only_validate_private_factor_revision(revision)
            or evidence.validation_disposition is not OnlyPrivateFactorValidationDisposition.PASS
            or evidence.revision_fingerprint != revision.revision_fingerprint
            or evidence.source_sha256 != revision.source_sha256
            or evidence.factor_api_contract_fingerprint != revision.factor_api_contract_fingerprint
            or evidence.validation_policy_fingerprint
            != ONLY_PRIVATE_FACTOR_VALIDATION_POLICY_V1.validation_policy_fingerprint
        ):
            raise ValueError("PRIVATE_FACTOR_VALIDATION_EVIDENCE_MISMATCH")
        source = revision.source_text.encode("utf-8")
        manifest = cls(
            revision.factor_id,
            revision.semantic_version,
            revision.revision_fingerprint,
            revision.source_sha256,
            len(source),
            revision.factor_api_version,
            revision.factor_api_contract_fingerprint,
            evidence.validation_policy_fingerprint,
            evidence.validation_evidence_fingerprint,
        )
        manifest.verify(source)
        return manifest, source

    def verify(self, source: bytes) -> None:
        if (
            len(source) != self.source_size
            or hashlib.sha256(source).hexdigest() != self.source_sha256
            or self.factor_api_version != 1
            or self.factor_api_contract_fingerprint != ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint
        ):
            raise ValueError("PRIVATE_FACTOR_SOURCE_ARTIFACT_MISMATCH")


class _PrivateFactorAstInterpreter:
    def __init__(
        self,
        function: ast.FunctionDef,
        api: OnlyCanonicalValueSemanticsV1,
        inputs: dict[str, object],
        parameters: dict[str, object],
    ) -> None:
        self._function = function
        self._values: dict[str, object] = {"api": api, "inputs": inputs, "parameters": parameters}

    def run(self) -> object:
        returned, result = self._execute_block(self._function.body)
        return result if returned else None

    def _execute_block(self, statements: Sequence[ast.stmt]) -> tuple[bool, object]:
        for statement in statements:
            returned, result = self._execute_statement(statement)
            if returned:
                return True, result
        return False, None

    def _execute_statement(self, statement: ast.stmt) -> tuple[bool, object]:
        if isinstance(statement, ast.Assign):
            value = self._evaluate(statement.value)
            for target in statement.targets:
                self._assign(target, value)
            return False, None
        if isinstance(statement, ast.Return):
            return True, None if statement.value is None else self._evaluate(statement.value)
        if isinstance(statement, ast.Expr):
            self._evaluate(statement.value)
            return False, None
        if isinstance(statement, ast.If):
            branch = statement.body if self._evaluate(statement.test) else statement.orelse
            return self._execute_block(branch)
        if isinstance(statement, ast.While):
            while self._evaluate(statement.test):
                returned, result = self._execute_block(statement.body)
                if returned:
                    return True, result
            return self._execute_block(statement.orelse)
        raise ValueError(f"PRIVATE_FACTOR_FORBIDDEN_AST:{type(statement).__name__}")

    def _assign(self, target: ast.expr, value: object) -> None:
        if isinstance(target, ast.Name):
            self._values[target.id] = value
            return
        if isinstance(target, ast.Subscript):
            container = self._evaluate(target.value)
            key = self._evaluate(target.slice)
            cast(Any, container)[key] = value
            return
        raise ValueError(f"PRIVATE_FACTOR_FORBIDDEN_AST:{type(target).__name__}")

    def _evaluate(self, expression: ast.expr) -> object:
        if isinstance(expression, ast.Name):
            return self._values[expression.id]
        if isinstance(expression, ast.Constant):
            return expression.value
        if isinstance(expression, ast.Dict):
            if any(key is None for key in expression.keys):
                raise ValueError("PRIVATE_FACTOR_FORBIDDEN_AST:DictUnpack")
            return {
                self._evaluate(cast(ast.expr, key)): self._evaluate(value)
                for key, value in zip(expression.keys, expression.values, strict=True)
            }
        if isinstance(expression, ast.Tuple):
            return tuple(self._evaluate(item) for item in expression.elts)
        if isinstance(expression, ast.List):
            return [self._evaluate(item) for item in expression.elts]
        if isinstance(expression, ast.Subscript):
            return cast(Any, self._evaluate(expression.value))[self._evaluate(expression.slice)]
        if isinstance(expression, ast.Attribute):
            if (
                not isinstance(expression.value, ast.Name)
                or expression.value.id != "api"
                or expression.attr not in _OPERATIONS
            ):
                raise ValueError("PRIVATE_FACTOR_FORBIDDEN_ATTRIBUTE")
            return getattr(self._values["api"], expression.attr)
        if isinstance(expression, ast.Call):
            if not isinstance(expression.func, ast.Attribute) or expression.keywords:
                raise ValueError("PRIVATE_FACTOR_FORBIDDEN_CALL")
            function = self._evaluate(expression.func)
            return cast(Any, function)(*(self._evaluate(argument) for argument in expression.args))
        raise ValueError(f"PRIVATE_FACTOR_FORBIDDEN_AST:{type(expression).__name__}")


def _execute_child(
    connection: Connection, source: bytes, inputs: Mapping[str, object], parameters: Mapping[str, object]
) -> None:
    os.environ.clear()
    try:
        tree = ast.parse(source.decode("utf-8"), mode="exec")
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef) or tree.body[0].name != "calculate":
            raise ValueError("PRIVATE_FACTOR_ENTRYPOINT_INVALID")
        result = _PrivateFactorAstInterpreter(
            tree.body[0],
            OnlyCanonicalValueSemanticsV1(ONLY_PRIVATE_FACTOR_NUMERIC_V1),
            dict(inputs),
            dict(parameters),
        ).run()
        connection.send((True, result))
    except BaseException as exc:
        connection.send((False, f"{type(exc).__name__}:{exc}"))
    finally:
        connection.close()


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorIsolatedProgramHost:
    timeout_seconds: float = 3.0

    def execute(
        self,
        manifest: OnlyPrivateFactorSourceArtifactManifestV1,
        source: bytes,
        inputs: Mapping[str, object],
        parameters: Mapping[str, object],
    ) -> object:
        manifest.verify(source)
        parent, child = multiprocessing.get_context("spawn").Pipe(False)
        process = multiprocessing.get_context("spawn").Process(
            target=_execute_child, args=(child, source, dict(inputs), dict(parameters))
        )
        process.start()
        child.close()
        if not parent.poll(self.timeout_seconds):
            process.kill()
            process.join(timeout=self.timeout_seconds)
            raise TimeoutError("PRIVATE_FACTOR_EXECUTION_TIMEOUT")
        success, result = parent.recv()
        process.join(timeout=self.timeout_seconds)
        if process.is_alive():
            process.kill()
            process.join(timeout=self.timeout_seconds)
            raise ValueError("PRIVATE_FACTOR_EXECUTION_FAILED:PROCESS_DID_NOT_EXIT")
        if not success or process.exitcode != 0:
            raise ValueError(f"PRIVATE_FACTOR_EXECUTION_FAILED:{result}")
        return result


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorAdapterV1:
    backend: str
    adapter_fingerprint: str
    host: OnlyPrivateFactorIsolatedProgramHost

    def __post_init__(self) -> None:
        if self.backend not in {"RESEARCH", "TRADING"} or not _is_sha(self.adapter_fingerprint):
            raise ValueError("PRIVATE_FACTOR_ADAPTER_INVALID")

    def implementation_fingerprint(self, manifest: OnlyPrivateFactorSourceArtifactManifestV1) -> str:
        return only_canonical_fingerprint(
            {
                "factor_id": manifest.factor_id,
                "semantic_version": manifest.semantic_version,
                "revision_fingerprint": manifest.revision_fingerprint,
                "source_artifact_fingerprint": manifest.source_artifact_fingerprint,
                "factor_api_contract_fingerprint": manifest.factor_api_contract_fingerprint,
                "adapter_fingerprint": self.adapter_fingerprint,
                "backend": self.backend,
            }
        )

    def execute(
        self,
        manifest: OnlyPrivateFactorSourceArtifactManifestV1,
        source: bytes,
        observations: Sequence[Mapping[str, object]],
        parameters: Mapping[str, object],
    ) -> tuple[object, ...]:
        return tuple(self.host.execute(manifest, source, item, parameters) for item in observations)


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorDefinitionResolverV1:
    type_definition: OnlyCalculationTypeDefinition

    def resolve(
        self,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
    ) -> OnlyCalculationDefinition:
        return self.type_definition.resolve(
            parameters,
            input_bindings,
            OnlyWarmupDefinition(1, "point inputs are available", OnlyPreReadyOutput.NULL, "STATELESS"),
        )


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorResearchBackendV1:
    artifact: OnlyPrivateFactorSourceArtifactManifestV1
    source: bytes
    adapter: OnlyPrivateFactorAdapterV1

    def execute(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> Mapping[str, pa.Array]:
        if set(inputs) != {item.name for item in definition.inputs}:
            raise ValueError("PRIVATE_FACTOR_RESEARCH_INPUT_MISMATCH")
        columns = {name: tuple(value.to_pylist()) for name, value in inputs.items()}
        lengths = {len(value) for value in columns.values()}
        if len(lengths) != 1:
            raise ValueError("PRIVATE_FACTOR_RESEARCH_INPUT_MISMATCH")
        count = next(iter(lengths), 0)
        observations = tuple({name: columns[name][index] for name in sorted(columns)} for index in range(count))
        outputs = self.adapter.execute(self.artifact, self.source, observations, definition.parameters)
        expected = {item.name: item for item in definition.outputs}
        rows = [_normalize_output(cast(Mapping[str, object], output), definition.outputs) for output in outputs]
        return {
            name: pa.array([row[name] for row in rows], type=_arrow_type(contract.data_type))
            for name, contract in expected.items()
        }


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorTradingBackendV1:
    definition: OnlyCalculationDefinition
    artifact: OnlyPrivateFactorSourceArtifactManifestV1
    source: bytes
    adapter: OnlyPrivateFactorAdapterV1

    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]:
        result = self.adapter.execute(self.artifact, self.source, (inputs,), self.definition.parameters)[0]
        if not isinstance(result, Mapping):
            raise ValueError("PRIVATE_FACTOR_OUTPUT_MISMATCH")
        return _normalize_output(cast(Mapping[str, object], result), self.definition.outputs)


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorTradingBackendFactoryV1:
    artifact: OnlyPrivateFactorSourceArtifactManifestV1
    source: bytes
    adapter: OnlyPrivateFactorAdapterV1

    def create(self, definition: OnlyCalculationDefinition, request: object) -> OnlyPrivateFactorTradingBackendV1:
        del request
        return OnlyPrivateFactorTradingBackendV1(definition, self.artifact, self.source, self.adapter)


def only_private_factor_type_definition(revision: OnlyPrivateFactorRevision) -> OnlyCalculationTypeDefinition:
    return OnlyCalculationTypeDefinition(
        OnlyCalculationKind.FACTOR,
        revision.factor_id,
        revision.semantic_version,
        OnlyParameterSchema(
            tuple(_parameter(name, value) for name, value in sorted(revision.parameter_contract.items()))
        ),
        tuple(_input(name, value) for name, value in sorted(revision.input_contract.items())),
        tuple(_output(name, value) for name, value in sorted(revision.output_contract.items())),
        OnlyMissingValuePolicy.PROPAGATE,
        OnlyTimestampSemantic.EVENT_TIME,
        ONLY_PRIVATE_FACTOR_NUMERIC_V1,
        OnlyFactorKind.TIME_SERIES,
    )


def only_private_factor_backend_registrations(
    revision: OnlyPrivateFactorRevision,
    artifact: OnlyPrivateFactorSourceArtifactManifestV1,
    source: bytes,
    research: OnlyPrivateFactorAdapterV1,
    trading: OnlyPrivateFactorAdapterV1,
) -> tuple[OnlyCalculationBackendRegistration, OnlyCalculationBackendRegistration]:
    artifact.verify(source)
    if artifact.revision_fingerprint != revision.revision_fingerprint:
        raise ValueError("PRIVATE_FACTOR_SOURCE_ARTIFACT_MISMATCH")
    definition = only_private_factor_type_definition(revision)
    resolver = OnlyPrivateFactorDefinitionResolverV1(definition)
    reference = OnlyCalculationTypeReference(definition.kind, definition.type_id, definition.semantic_version)
    adapter_source = Path(__file__).read_bytes()
    dependencies = (
        OnlyCalculationSemanticDependency(
            "onlyalpha.private-factor.api", "1", artifact.factor_api_contract_fingerprint
        ),
        OnlyCalculationSemanticDependency(
            "onlyalpha.private-factor.source-artifact", "1", artifact.source_artifact_fingerprint
        ),
    )

    def implementation(
        backend: OnlyCalculationBackendKind, adapter: OnlyPrivateFactorAdapterV1
    ) -> OnlyCalculationImplementationManifest:
        return only_implementation_manifest_from_bytes(
            calculation_type_reference=reference,
            backend_kind=backend,
            entrypoint_identity=(
                "onlyalpha.quant_assets.private_factor_execution:OnlyPrivateFactorResearchBackendV1"
                if backend is OnlyCalculationBackendKind.RESEARCH
                else "onlyalpha.quant_assets.private_factor_execution:OnlyPrivateFactorTradingBackendFactoryV1"
            ),
            resources={
                "private_factor/source.py": source,
                f"private_factor/{backend.value.lower()}-adapter.py": adapter_source,
                f"private_factor/{backend.value.lower()}-identity.txt": adapter.adapter_fingerprint.encode(),
            },
            semantic_dependencies=dependencies,
        )

    return (
        OnlyCalculationBackendRegistration(
            definition,
            OnlyCalculationBackendKind.RESEARCH,
            OnlyPrivateFactorResearchBackendV1(artifact, source, research),
            resolver,
            implementation(OnlyCalculationBackendKind.RESEARCH, research),
        ),
        OnlyCalculationBackendRegistration(
            definition,
            OnlyCalculationBackendKind.TRADING,
            OnlyPrivateFactorTradingBackendFactoryV1(artifact, source, trading),
            resolver,
            implementation(OnlyCalculationBackendKind.TRADING, trading),
            OnlyCalculationStateCapability.STATELESS,
        ),
    )


def _contract(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"PRIVATE_FACTOR_{name.upper()}_CONTRACT_INVALID")
    return cast(Mapping[str, object], value)


def _data_type(value: Mapping[str, object]) -> OnlyCalculationDataType:
    try:
        raw = value["type"]
        if not isinstance(raw, str):
            raise TypeError
        return OnlyCalculationDataType(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("PRIVATE_FACTOR_DATA_TYPE_INVALID") from exc


def _input(name: str, value: object) -> OnlyInputDefinition:
    contract = _contract(value, "input")
    if not {"type"} <= set(contract) <= {"type", "nullable", "missing"} or {
        "nullable",
        "missing",
    } <= set(contract):
        raise ValueError("PRIVATE_FACTOR_INPUT_CONTRACT_INVALID")
    return OnlyInputDefinition(name, _data_type(contract), _nullable(contract, "INPUT"))


def _output(name: str, value: object) -> OnlyOutputDefinition:
    contract = _contract(value, "output")
    if not {"type"} <= set(contract) <= {"type", "nullable", "missing", "semantic_type"} or {
        "nullable",
        "missing",
    } <= set(contract):
        raise ValueError("PRIVATE_FACTOR_OUTPUT_CONTRACT_INVALID")
    semantic_type = contract.get("semantic_type", FACTOR_VALUE_SEMANTIC_TYPE)
    if not isinstance(semantic_type, str) or not semantic_type:
        raise ValueError("PRIVATE_FACTOR_OUTPUT_CONTRACT_INVALID")
    return OnlyOutputDefinition(
        name,
        _data_type(contract),
        _nullable(contract, "OUTPUT"),
        semantic_type=semantic_type,
    )


def _parameter(name: str, value: object) -> OnlyParameterDefinition:
    contract = _contract(value, "parameter")
    if not {"type"} <= set(contract) <= {"type", "required", "default"}:
        raise ValueError("PRIVATE_FACTOR_PARAMETER_CONTRACT_INVALID")
    try:
        raw_type = contract["type"]
        if not isinstance(raw_type, str):
            raise TypeError
        parameter_type = OnlyParameterType(raw_type)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("PRIVATE_FACTOR_PARAMETER_CONTRACT_INVALID") from exc
    required = contract.get("required", "default" not in contract)
    if not isinstance(required, bool):
        raise ValueError("PRIVATE_FACTOR_PARAMETER_CONTRACT_INVALID")
    return OnlyParameterDefinition(name, parameter_type, required, cast(Any, contract.get("default")))


def _nullable(contract: Mapping[str, object], owner: str) -> bool:
    value = contract.get("nullable", contract.get("missing", False))
    if not isinstance(value, bool):
        raise ValueError(f"PRIVATE_FACTOR_{owner}_CONTRACT_INVALID")
    return value


def _arrow_type(value: OnlyCalculationDataType) -> pa.DataType:
    return {
        OnlyCalculationDataType.DECIMAL: pa.decimal128(38, 12),
        OnlyCalculationDataType.INTEGER: pa.int64(),
        OnlyCalculationDataType.BOOLEAN: pa.bool_(),
        OnlyCalculationDataType.STRING: pa.string(),
    }[value]


def _normalize_output(values: Mapping[str, object], outputs: tuple[OnlyOutputDefinition, ...]) -> Mapping[str, object]:
    expected = {item.name: item for item in outputs}
    if set(values) != set(expected):
        raise ValueError("PRIVATE_FACTOR_OUTPUT_MISMATCH")
    try:
        normalized = {
            name: pa.scalar(values[name], type=_arrow_type(item.data_type)).as_py() for name, item in expected.items()
        }
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("PRIVATE_FACTOR_OUTPUT_MISMATCH") from exc
    if any(normalized[item.name] is None and not item.nullable for item in outputs):
        raise ValueError("PRIVATE_FACTOR_OUTPUT_MISMATCH")
    return normalized


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1:
    revision_fingerprint: str
    source_artifact_fingerprint: str
    factor_api_contract_fingerprint: str
    research_adapter_fingerprint: str
    trading_adapter_fingerprint: str
    research_implementation_fingerprint: str
    trading_implementation_fingerprint: str
    test_vector_set_fingerprint: str
    research_output_fingerprint: str
    trading_output_fingerprint: str
    disposition: str = "PASS"

    def __post_init__(self) -> None:
        if (
            any(
                not _is_sha(value)
                for value in (
                    self.revision_fingerprint,
                    self.source_artifact_fingerprint,
                    self.factor_api_contract_fingerprint,
                    self.research_adapter_fingerprint,
                    self.trading_adapter_fingerprint,
                    self.research_implementation_fingerprint,
                    self.trading_implementation_fingerprint,
                    self.test_vector_set_fingerprint,
                    self.research_output_fingerprint,
                    self.trading_output_fingerprint,
                )
            )
            or self.disposition != "PASS"
            or self.research_output_fingerprint != self.trading_output_fingerprint
        ):
            raise ValueError("PRIVATE_FACTOR_EQUIVALENCE_EVIDENCE_MISMATCH")

    @property
    def equivalence_evidence_fingerprint(self) -> str:
        return only_canonical_fingerprint({field: getattr(self, field) for field in self.__dataclass_fields__})

    def to_dict(self) -> dict[str, object]:
        return {
            **{field: getattr(self, field) for field in self.__dataclass_fields__},
            "equivalence_evidence_fingerprint": self.equivalence_evidence_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1:
        fields = set(cls.__dataclass_fields__)
        if set(payload) != fields | {"equivalence_evidence_fingerprint"}:
            raise ValueError("PRIVATE_FACTOR_EQUIVALENCE_EVIDENCE_MISMATCH")
        result = cls(*(payload[name] for name in cls.__dataclass_fields__))  # type: ignore[arg-type]
        if (
            payload["equivalence_evidence_fingerprint"] != result.equivalence_evidence_fingerprint
            or result.disposition != "PASS"
        ):
            raise ValueError("PRIVATE_FACTOR_EQUIVALENCE_EVIDENCE_MISMATCH")
        return result

    @classmethod
    def certify(
        cls,
        manifest: OnlyPrivateFactorSourceArtifactManifestV1,
        source: bytes,
        registrations: tuple[OnlyCalculationBackendRegistration, OnlyCalculationBackendRegistration],
        vectors: Sequence[Mapping[str, object]],
        parameters: Mapping[str, object],
    ) -> OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1:
        by_backend = {item.backend: item for item in registrations}
        if set(by_backend) != {OnlyCalculationBackendKind.RESEARCH, OnlyCalculationBackendKind.TRADING} or not vectors:
            raise ValueError("PRIVATE_FACTOR_EQUIVALENCE_ADAPTER_MISMATCH")
        research_registration = by_backend[OnlyCalculationBackendKind.RESEARCH]
        trading_registration = by_backend[OnlyCalculationBackendKind.TRADING]
        if (
            research_registration.definition_resolver is None
            or research_registration.implementation_manifest is None
            or trading_registration.implementation_manifest is None
            or not isinstance(research_registration.provider, OnlyPrivateFactorResearchBackendV1)
            or not isinstance(trading_registration.provider, OnlyPrivateFactorTradingBackendFactoryV1)
        ):
            raise ValueError("PRIVATE_FACTOR_EQUIVALENCE_ADAPTER_MISMATCH")
        definition = research_registration.definition_resolver.resolve(
            parameters,
            {
                item.name: OnlyCalculationReference(None, item.name, item.name)
                for item in research_registration.type_definition.inputs
            },
        )
        expected_inputs = {item.name: item for item in definition.inputs}
        if any(set(vector) != set(expected_inputs) for vector in vectors):
            raise ValueError("PRIVATE_FACTOR_EQUIVALENCE_INPUT_MISMATCH")
        research_columns = {
            name: pa.array([vector[name] for vector in vectors], type=_arrow_type(item.data_type))
            for name, item in expected_inputs.items()
        }
        research_columns_out = research_registration.provider.execute(definition, research_columns)
        research_outputs = tuple(
            {name: values[index].as_py() for name, values in research_columns_out.items()}
            for index in range(len(vectors))
        )
        trading_backend = trading_registration.provider.create(definition, object())
        trading_outputs = tuple(dict(trading_backend.update(vector)) for vector in vectors)
        research_fp = only_canonical_fingerprint(research_outputs)
        trading_fp = only_canonical_fingerprint(trading_outputs)
        if research_fp != trading_fp:
            raise ValueError("PRIVATE_FACTOR_EQUIVALENCE_FAILED")
        research = research_registration.provider.adapter
        trading = trading_registration.provider.adapter
        return cls(
            manifest.revision_fingerprint,
            manifest.source_artifact_fingerprint,
            manifest.factor_api_contract_fingerprint,
            research.adapter_fingerprint,
            trading.adapter_fingerprint,
            research_registration.implementation_manifest.implementation_fingerprint,
            trading_registration.implementation_manifest.implementation_fingerprint,
            only_canonical_fingerprint({"vectors": list(vectors), "parameters": parameters}),
            research_fp,
            trading_fp,
        )


@dataclass(frozen=True, order=True, slots=True)
class OnlyPrivateFactorProviderSnapshotEntryV1:
    factor_id: str
    semantic_version: str
    revision_fingerprint: str
    source_sha256: str
    source_artifact_fingerprint: str
    factor_api_version: int
    factor_api_contract_fingerprint: str
    research_adapter_fingerprint: str
    trading_adapter_fingerprint: str
    research_implementation_fingerprint: str
    trading_implementation_fingerprint: str
    equivalence_evidence_fingerprint: str

    @classmethod
    def derive(
        cls,
        manifest: OnlyPrivateFactorSourceArtifactManifestV1,
        evidence: OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1,
    ) -> OnlyPrivateFactorProviderSnapshotEntryV1:
        if (
            evidence.revision_fingerprint != manifest.revision_fingerprint
            or evidence.source_artifact_fingerprint != manifest.source_artifact_fingerprint
            or evidence.factor_api_contract_fingerprint != manifest.factor_api_contract_fingerprint
            or evidence.disposition != "PASS"
        ):
            raise ValueError("PRIVATE_FACTOR_EQUIVALENCE_EVIDENCE_MISMATCH")
        return cls(
            manifest.factor_id,
            manifest.semantic_version,
            manifest.revision_fingerprint,
            manifest.source_sha256,
            manifest.source_artifact_fingerprint,
            manifest.factor_api_version,
            manifest.factor_api_contract_fingerprint,
            evidence.research_adapter_fingerprint,
            evidence.trading_adapter_fingerprint,
            evidence.research_implementation_fingerprint,
            evidence.trading_implementation_fingerprint,
            evidence.equivalence_evidence_fingerprint,
        )

    def to_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateFactorProviderSnapshotEntryV1:
        if set(payload) != set(cls.__dataclass_fields__):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        values = [payload[field] for field in cls.__dataclass_fields__]
        if any(not isinstance(value, str) for value in values[:5] + values[6:]):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        if isinstance(values[5], bool) or not isinstance(values[5], int):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        return cls(*cast(list[Any], values))


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorProviderSnapshotV1:
    entries: tuple[OnlyPrivateFactorProviderSnapshotEntryV1, ...]

    def __post_init__(self) -> None:
        canonical = tuple(sorted(self.entries))
        if not canonical or len({item.factor_id for item in canonical}) != len(canonical):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        object.__setattr__(self, "entries", canonical)

    @property
    def snapshot_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "contract": "ONLYALPHA_PRIVATE_FACTOR_PROVIDER_SNAPSHOT_V1",
                "entries": [item.to_dict() for item in self.entries],
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "entries": [item.to_dict() for item in self.entries],
            "snapshot_fingerprint": self.snapshot_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateFactorProviderSnapshotV1:
        if set(payload) != {"entries", "snapshot_fingerprint"} or not isinstance(payload["entries"], list):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        result = cls(
            tuple(
                OnlyPrivateFactorProviderSnapshotEntryV1.from_dict(cast(Mapping[str, object], item))
                for item in payload["entries"]
                if isinstance(item, Mapping)
            )
        )
        if (
            len(result.entries) != len(payload["entries"])
            or payload["snapshot_fingerprint"] != result.snapshot_fingerprint
        ):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        return result


@dataclass(frozen=True, slots=True, init=False)
class OnlyPrivateFactorExecutableClosureV1:
    revision: OnlyPrivateFactorRevision
    validation_evidence: OnlyPrivateFactorValidationEvidenceV1
    source_artifact: OnlyPrivateFactorSourceArtifactManifestV1
    source: bytes
    registrations: tuple[OnlyCalculationBackendRegistration, OnlyCalculationBackendRegistration]
    equivalence_evidence: OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1
    provider_snapshot: OnlyPrivateFactorProviderSnapshotV1
    certification_vectors: tuple[Mapping[str, object], ...]
    certification_parameters: Mapping[str, object]

    def __init__(self) -> None:
        raise TypeError("PRIVATE_FACTOR_EXECUTABLE_CLOSURE_CANONICAL_PRODUCER_REQUIRED")

    def verify_canonical(self) -> None:
        validation = only_validate_private_factor_revision(self.revision)
        artifact, source = OnlyPrivateFactorSourceArtifactManifestV1.materialize(self.revision, validation)
        by_backend = {item.backend: item for item in self.registrations}
        research = by_backend.get(OnlyCalculationBackendKind.RESEARCH)
        trading = by_backend.get(OnlyCalculationBackendKind.TRADING)
        if (
            type(self) is not OnlyPrivateFactorExecutableClosureV1
            or validation != self.validation_evidence
            or artifact != self.source_artifact
            or source != self.source
            or research is None
            or trading is None
            or type(research.provider) is not OnlyPrivateFactorResearchBackendV1
            or type(trading.provider) is not OnlyPrivateFactorTradingBackendFactoryV1
            or type(research.provider.adapter) is not OnlyPrivateFactorAdapterV1
            or type(trading.provider.adapter) is not OnlyPrivateFactorAdapterV1
            or type(research.provider.adapter.host) is not OnlyPrivateFactorIsolatedProgramHost
            or type(trading.provider.adapter.host) is not OnlyPrivateFactorIsolatedProgramHost
            or research.provider.adapter.backend != "RESEARCH"
            or trading.provider.adapter.backend != "TRADING"
            or research.provider.adapter.adapter_fingerprint != _ADAPTER_FINGERPRINTS["RESEARCH"]
            or trading.provider.adapter.adapter_fingerprint != _ADAPTER_FINGERPRINTS["TRADING"]
        ):
            raise ValueError("PRIVATE_FACTOR_EXECUTABLE_CLOSURE_MISMATCH")
        registrations = only_private_factor_backend_registrations(
            self.revision,
            artifact,
            source,
            research.provider.adapter,
            trading.provider.adapter,
        )
        equivalence = OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1.certify(
            artifact,
            source,
            registrations,
            self.certification_vectors,
            self.certification_parameters,
        )
        snapshot = OnlyPrivateFactorProviderSnapshotV1(
            (OnlyPrivateFactorProviderSnapshotEntryV1.derive(artifact, equivalence),)
        )
        if (
            registrations != self.registrations
            or equivalence != self.equivalence_evidence
            or snapshot != self.provider_snapshot
        ):
            raise ValueError("PRIVATE_FACTOR_EXECUTABLE_CLOSURE_MISMATCH")

    @classmethod
    def create(
        cls,
        revision: OnlyPrivateFactorRevision,
        vectors: Sequence[Mapping[str, object]],
        parameters: Mapping[str, object],
        *,
        host: OnlyPrivateFactorIsolatedProgramHost | None = None,
    ) -> OnlyPrivateFactorExecutableClosureV1:
        validation = only_validate_private_factor_revision(revision)
        artifact, source = OnlyPrivateFactorSourceArtifactManifestV1.materialize(revision, validation)
        isolated = host or OnlyPrivateFactorIsolatedProgramHost()
        research = OnlyPrivateFactorAdapterV1(
            "RESEARCH",
            _ADAPTER_FINGERPRINTS["RESEARCH"],
            isolated,
        )
        trading = OnlyPrivateFactorAdapterV1(
            "TRADING",
            _ADAPTER_FINGERPRINTS["TRADING"],
            isolated,
        )
        registrations = only_private_factor_backend_registrations(revision, artifact, source, research, trading)
        research_manifest = registrations[0].implementation_manifest
        trading_manifest = registrations[1].implementation_manifest
        if research_manifest is None or trading_manifest is None:
            raise ValueError("PRIVATE_FACTOR_IMPLEMENTATION_IDENTITY_MISSING")
        equivalence = OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1.certify(
            artifact,
            source,
            registrations,
            vectors,
            parameters,
        )
        snapshot = OnlyPrivateFactorProviderSnapshotV1(
            (OnlyPrivateFactorProviderSnapshotEntryV1.derive(artifact, equivalence),)
        )
        certification_vectors = tuple(dict(item) for item in vectors)
        certification_parameters = dict(parameters)
        result = object.__new__(cls)
        for name, value in (
            ("revision", revision),
            ("validation_evidence", validation),
            ("source_artifact", artifact),
            ("source", source),
            ("registrations", registrations),
            ("equivalence_evidence", equivalence),
            ("provider_snapshot", snapshot),
            ("certification_vectors", certification_vectors),
            ("certification_parameters", certification_parameters),
        ):
            object.__setattr__(result, name, value)
        result.verify_canonical()
        return result


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "ONLY_"))]
