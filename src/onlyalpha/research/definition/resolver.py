"""Deterministic Research Definition to existing Specification/Workload lowering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import NoReturn

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    FACTOR_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationKind,
    OnlyCalculationScalar,
    OnlyCalculationTypeDefinition,
    OnlyOutputDefinition,
    only_calculation_scalar_sort_key,
)
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.dataset import OnlyResearchDatasetDefinition
from onlyalpha.research.specification.model import (
    OnlyResearchCalculationSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSpecification,
    OnlyResearchStatisticsSpec,
)
from onlyalpha.research.specification.resolver import (
    OnlyResearchSpecificationResolution,
    OnlyResearchSpecificationResolver,
)
from onlyalpha.research.sweep.definition import (
    OnlyResearchSweepParameterDimension,
    OnlyResearchSweepParameterTarget,
)
from onlyalpha.research.sweep.template import (
    OnlyResearchGraphTemplate,
    OnlyResearchGraphTemplateNode,
    OnlyResearchTemplateInputBinding,
    OnlyResearchTemplateReference,
)
from onlyalpha.research.workload import OnlyResearchWorkloadPlan

from .errors import OnlyResearchDefinitionError, OnlyResearchDefinitionPhase
from .expression import (
    OnlyResearchAnd,
    OnlyResearchBooleanExpression,
    OnlyResearchComparison,
    OnlyResearchDatasetFieldRef,
    OnlyResearchNot,
    OnlyResearchOperand,
    OnlyResearchTypedLiteral,
    OnlyResearchVariableRef,
    only_canonicalize_research_expression,
    only_research_expression_fingerprint,
)
from .model import (
    OnlyResearchCalculationInput,
    OnlyResearchCalculationInstance,
    OnlyResearchDefinition,
    OnlyResearchFixedParameter,
    OnlyResearchSweepParameter,
    OnlyResearchUniverseKind,
)
from .ports import OnlyResearchDefinitionDatasetResolver, OnlyResearchUniverseResolver
from .primitives import only_register_research_predicate_primitives, only_research_predicate_type_reference

DEFAULT_RESEARCH_DEFINITION_MAX_CANDIDATES = 256
_DATASET_TYPES = {
    "open": OnlyCalculationDataType.DECIMAL,
    "high": OnlyCalculationDataType.DECIMAL,
    "low": OnlyCalculationDataType.DECIMAL,
    "close": OnlyCalculationDataType.DECIMAL,
    "volume": OnlyCalculationDataType.DECIMAL,
    "quote_volume": OnlyCalculationDataType.DECIMAL,
    "turnover_amount": OnlyCalculationDataType.DECIMAL,
    "trade_count": OnlyCalculationDataType.INTEGER,
    "open_interest": OnlyCalculationDataType.DECIMAL,
}


@dataclass(frozen=True, slots=True)
class OnlyResearchDefinitionCandidate:
    ordinal: int
    assignment: Mapping[str, OnlyCalculationScalar]
    candidate_fingerprint: str
    calculation_fingerprint: str
    graph_fingerprint: str
    node_fingerprints: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "assignment", MappingProxyType(dict(sorted(self.assignment.items()))))
        object.__setattr__(self, "node_fingerprints", MappingProxyType(dict(sorted(self.node_fingerprints.items()))))


@dataclass(frozen=True, slots=True)
class OnlyResearchPublishedVariableLineage:
    variable: OnlyResearchVariableRef
    template_node_id: str
    data_type: OnlyCalculationDataType
    semantic_type: str


@dataclass(frozen=True, slots=True)
class OnlyResearchDefinitionResolution:
    definition_fingerprint: str
    dataset_definition: OnlyResearchDatasetDefinition
    dataset_snapshot_fingerprint: str
    resolved_calculations: tuple[OnlyResearchCalculationInstance, ...]
    resolved_targets: tuple[OnlyResearchCalculationInstance, ...]
    published_variables: tuple[OnlyResearchPublishedVariableLineage, ...]
    candidates: tuple[OnlyResearchDefinitionCandidate, ...]
    decision_graph_template: OnlyResearchGraphTemplate
    specification: OnlyResearchSpecification
    specification_fingerprint: str
    specification_resolution: OnlyResearchSpecificationResolution
    workload: OnlyResearchWorkloadPlan
    diagnostics: tuple[object, ...] = ()


class OnlyResearchDefinitionResolver:
    def __init__(
        self,
        calculation_registry: OnlyCalculationRegistry,
        dataset_resolver: OnlyResearchDefinitionDatasetResolver,
        *,
        universe_resolver: OnlyResearchUniverseResolver | None = None,
        max_candidates: int = DEFAULT_RESEARCH_DEFINITION_MAX_CANDIDATES,
    ) -> None:
        if not isinstance(calculation_registry, OnlyCalculationRegistry):
            raise TypeError("Research Definition Resolver requires the Calculation Registry")
        if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or max_candidates <= 0:
            raise ValueError("max_candidates must be a positive integer")
        self._registry = calculation_registry
        self._datasets = dataset_resolver
        self._universes = universe_resolver
        self._max_candidates = max_candidates
        only_register_research_predicate_primitives(calculation_registry)

    def resolve(self, definition: OnlyResearchDefinition) -> OnlyResearchDefinitionResolution:
        if not isinstance(definition, OnlyResearchDefinition):
            self._fail(
                OnlyResearchDefinitionPhase.SCHEMA,
                "RESEARCH_DEFINITION_INVALID",
                "$",
                "resolve requires OnlyResearchDefinition",
            )
        instruments = self._resolve_universe(definition)
        try:
            dataset_definition = definition.dataset.to_dataset_definition(instruments)
            verified = self._datasets.resolve_verified(dataset_definition)
        except OnlyResearchDefinitionError:
            raise
        except Exception as exc:
            self._fail(
                OnlyResearchDefinitionPhase.DATASET, "RESEARCH_DEFINITION_DATASET_UNRESOLVED", "dataset", str(exc), exc
            )
        if verified.snapshot.definition != dataset_definition:
            self._fail(
                OnlyResearchDefinitionPhase.DATASET,
                "RESEARCH_DEFINITION_DATASET_MISMATCH",
                "dataset",
                "verified Snapshot does not match resolved Dataset Definition",
            )

        normalized, variables = self._resolve_calculations(definition.calculations, target=False)
        targets, target_variables = self._resolve_calculations(definition.targets, target=True)
        graph_nodes = self._calculation_nodes(normalized, variables)
        dimensions = self._dimensions(normalized)
        candidate_count = 1
        for dimension in dimensions:
            candidate_count *= len(dimension.candidates)
            if candidate_count > self._max_candidates:
                self._fail(
                    OnlyResearchDefinitionPhase.CANDIDATE,
                    "RESEARCH_DEFINITION_CANDIDATE_CARDINALITY_EXCEEDED",
                    "calculations",
                    f"global Candidate Space has {candidate_count} candidates; limit is {self._max_candidates}",
                )

        builder = _ExpressionLowerer(variables, graph_nodes)
        for role, expression in (
            ("eligibility", definition.eligibility),
            ("entry_signal", definition.signals.entry),
            ("exit_signal", definition.signals.exit),
        ):
            if expression is not None:
                try:
                    builder.lower_terminal(role, expression)
                except OnlyResearchDefinitionError:
                    raise
                except Exception as exc:
                    self._fail(
                        OnlyResearchDefinitionPhase.EXPRESSION,
                        "RESEARCH_DEFINITION_EXPRESSION_INVALID",
                        f"signals.{role}",
                        str(exc),
                        exc,
                    )
        decision_template = OnlyResearchGraphTemplate(tuple(builder.nodes.values()))
        calculations = [OnlyResearchCalculationSpec("decision", decision_template, dimensions)]
        for target in targets:
            target_template = OnlyResearchGraphTemplate((self._target_node(target),))
            calculations.append(OnlyResearchCalculationSpec(f"target.{target.instance_key}", target_template))

        statistics = self._statistics(definition, variables, target_variables)
        specification = OnlyResearchSpecification(
            verified.snapshot.snapshot_fingerprint,
            tuple(calculations),
            statistics,
        )
        try:
            specification_resolution = OnlyResearchSpecificationResolver(
                self._registry, max_cells=self._max_candidates
            ).resolve(specification)
        except Exception as exc:
            self._fail(
                OnlyResearchDefinitionPhase.SPECIFICATION,
                "RESEARCH_DEFINITION_SPECIFICATION_INVALID",
                "specification",
                str(exc),
                exc,
            )
        decision_candidates = tuple(
            item for item in specification_resolution.candidates if item.calculation_id == "decision"
        )
        candidates = tuple(
            OnlyResearchDefinitionCandidate(
                ordinal,
                lineage.assignment,
                only_canonical_fingerprint(
                    {
                        "schema_version": 1,
                        "definition_fingerprint": definition.definition_fingerprint,
                        "dataset_snapshot_fingerprint": verified.snapshot.snapshot_fingerprint,
                        "assignment": lineage.assignment,
                        "calculation_fingerprint": lineage.calculation_fingerprint,
                    }
                ),
                lineage.calculation_fingerprint,
                lineage.graph_fingerprint,
                lineage.node_fingerprints,
            )
            for ordinal, lineage in enumerate(decision_candidates)
        )
        published = tuple(
            OnlyResearchPublishedVariableLineage(ref, ref.instance_key, output.data_type, output.semantic_type)
            for ref, output in sorted(variables.items(), key=lambda item: item[0])
        )
        return OnlyResearchDefinitionResolution(
            definition.definition_fingerprint,
            dataset_definition,
            verified.snapshot.snapshot_fingerprint,
            normalized,
            targets,
            published,
            candidates,
            decision_template,
            specification,
            specification.specification_fingerprint,
            specification_resolution,
            specification_resolution.workload,
        )

    def _resolve_universe(self, definition: OnlyResearchDefinition) -> tuple[str, ...]:
        selection = definition.dataset.universe
        if selection.kind in {
            OnlyResearchUniverseKind.SINGLE_INSTRUMENT,
            OnlyResearchUniverseKind.EXPLICIT_INSTRUMENT_SET,
        }:
            return selection.instrument_ids
        if self._universes is None:
            self._fail(
                OnlyResearchDefinitionPhase.UNIVERSE,
                "RESEARCH_DEFINITION_UNIVERSE_UNRESOLVED",
                "dataset.universe",
                "registered Universe resolver is unavailable",
            )
        try:
            values = tuple(sorted(self._universes.resolve(selection)))
        except Exception as exc:
            self._fail(
                OnlyResearchDefinitionPhase.UNIVERSE,
                "RESEARCH_DEFINITION_UNIVERSE_UNRESOLVED",
                "dataset.universe",
                str(exc),
                exc,
            )
        if not values or len(values) != len(set(values)):
            self._fail(
                OnlyResearchDefinitionPhase.UNIVERSE,
                "RESEARCH_DEFINITION_UNIVERSE_INVALID",
                "dataset.universe",
                "resolved instruments must be non-empty and unique",
            )
        return values

    def _resolve_calculations(
        self, instances: tuple[OnlyResearchCalculationInstance, ...], *, target: bool
    ) -> tuple[tuple[OnlyResearchCalculationInstance, ...], dict[OnlyResearchVariableRef, OnlyOutputDefinition]]:
        result: list[OnlyResearchCalculationInstance] = []
        variables: dict[OnlyResearchVariableRef, OnlyOutputDefinition] = {}
        for instance in instances:
            path = f"{'targets' if target else 'calculations'}[{instance.instance_key}]"
            try:
                type_definition = self._registry.resolve_type(instance.type_reference)
                self._registry.resolve(
                    instance.type_reference.kind,
                    instance.type_reference.type_id,
                    instance.type_reference.semantic_version,
                    OnlyCalculationBackendKind.RESEARCH,
                )
            except ValueError as exc:
                code = (
                    "RESEARCH_DEFINITION_CALCULATION_VERSION_UNKNOWN"
                    if "semantic version" in str(exc)
                    else "RESEARCH_DEFINITION_CALCULATION_UNKNOWN"
                )
                self._fail(OnlyResearchDefinitionPhase.CALCULATION, code, f"{path}.type_reference", str(exc), exc)
            expected = OnlyCalculationKind.TARGET if target else None
            if target and type_definition.kind is not expected:
                self._fail(
                    OnlyResearchDefinitionPhase.TARGET,
                    "RESEARCH_DEFINITION_TARGET_KIND_INVALID",
                    path,
                    "Target instance must reference TARGET kind",
                )
            if not target and type_definition.kind not in {OnlyCalculationKind.INDICATOR, OnlyCalculationKind.FACTOR}:
                self._fail(
                    OnlyResearchDefinitionPhase.CALCULATION,
                    "RESEARCH_DEFINITION_CALCULATION_KIND_INVALID",
                    path,
                    "Decision Calculation must be Indicator or Factor",
                )
            normalized_parameters = self._normalize_parameters(instance, type_definition, path, target=target)
            outputs = {item.name: item for item in type_definition.outputs}
            for output_name in instance.published_outputs:
                output = outputs.get(output_name)
                if output is None:
                    self._fail(
                        OnlyResearchDefinitionPhase.CALCULATION,
                        "RESEARCH_DEFINITION_OUTPUT_UNKNOWN",
                        f"{path}.published_outputs",
                        output_name,
                    )
                variables[OnlyResearchVariableRef(instance.instance_key, output_name)] = output
            result.append(
                OnlyResearchCalculationInstance(
                    instance.instance_key,
                    instance.type_reference,
                    normalized_parameters,
                    instance.published_outputs,
                    instance.input_bindings,
                    instance.primary_output,
                )
            )
        return tuple(result), variables

    def _normalize_parameters(
        self,
        instance: OnlyResearchCalculationInstance,
        type_definition: OnlyCalculationTypeDefinition,
        path: str,
        *,
        target: bool,
    ) -> Mapping[str, OnlyResearchFixedParameter | OnlyResearchSweepParameter]:
        known = {item.name: item for item in type_definition.parameters.fields}
        required = {item.name for item in type_definition.parameters.fields if item.required}
        if not required.issubset(instance.parameters) or not set(instance.parameters).issubset(known):
            missing, unknown = required - set(instance.parameters), set(instance.parameters) - set(known)
            self._fail(
                OnlyResearchDefinitionPhase.CALCULATION,
                "RESEARCH_DEFINITION_PARAMETER_INVALID",
                f"{path}.parameters",
                f"missing={sorted(missing)}, unknown={sorted(unknown)}",
            )
        normalized: dict[str, OnlyResearchFixedParameter | OnlyResearchSweepParameter] = {}
        for name, parameter in known.items():
            if name not in instance.parameters:
                normalized[name] = OnlyResearchFixedParameter(parameter.normalize(parameter.default))
        for name, binding in instance.parameters.items():
            parameter = known[name]
            values = (binding.value,) if isinstance(binding, OnlyResearchFixedParameter) else binding.values
            admitted: list[OnlyCalculationScalar] = []
            for value in values:
                try:
                    item = parameter.normalize(value)
                except (TypeError, ValueError) as exc:
                    self._fail(
                        OnlyResearchDefinitionPhase.CALCULATION,
                        "RESEARCH_DEFINITION_PARAMETER_INVALID",
                        f"{path}.parameters.{name}",
                        str(exc),
                        exc,
                    )
                if any(type(item) is type(existing) and item == existing for existing in admitted):
                    self._fail(
                        OnlyResearchDefinitionPhase.CANDIDATE,
                        "RESEARCH_DEFINITION_SWEEP_DUPLICATE",
                        f"{path}.parameters.{name}",
                        "duplicate normalized Sweep value",
                    )
                admitted.append(item)
            if target and isinstance(binding, OnlyResearchSweepParameter):
                self._fail(
                    OnlyResearchDefinitionPhase.TARGET,
                    "RESEARCH_DEFINITION_TARGET_SWEEP_FORBIDDEN",
                    f"{path}.parameters.{name}",
                    "Target V1 parameters must be Fixed",
                )
            admitted.sort(key=only_calculation_scalar_sort_key)
            normalized[name] = (
                OnlyResearchFixedParameter(admitted[0])
                if isinstance(binding, OnlyResearchFixedParameter)
                else OnlyResearchSweepParameter(tuple(admitted))
            )
        return MappingProxyType(normalized)

    def _calculation_nodes(
        self,
        instances: tuple[OnlyResearchCalculationInstance, ...],
        variables: Mapping[OnlyResearchVariableRef, OnlyOutputDefinition],
    ) -> dict[str, OnlyResearchGraphTemplateNode]:
        nodes: dict[str, OnlyResearchGraphTemplateNode] = {}
        for instance in instances:
            parameters = {
                name: binding.value if isinstance(binding, OnlyResearchFixedParameter) else binding.values[0]
                for name, binding in instance.parameters.items()
            }
            bindings = tuple(
                self._template_input(item, variables, f"calculations.{instance.instance_key}.input_bindings")
                for item in instance.input_bindings
            )
            nodes[instance.instance_key] = OnlyResearchGraphTemplateNode(
                instance.instance_key, instance.type_reference, parameters, bindings
            )
        return nodes

    def _target_node(self, instance: OnlyResearchCalculationInstance) -> OnlyResearchGraphTemplateNode:
        parameters = {
            name: binding.value
            for name, binding in instance.parameters.items()
            if isinstance(binding, OnlyResearchFixedParameter)
        }
        bindings = tuple(
            self._template_input(item, {}, f"targets.{instance.instance_key}.input_bindings", target=True)
            for item in instance.input_bindings
        )
        return OnlyResearchGraphTemplateNode(instance.instance_key, instance.type_reference, parameters, bindings)

    def _template_input(
        self,
        item: OnlyResearchCalculationInput,
        variables: Mapping[OnlyResearchVariableRef, OnlyOutputDefinition],
        path: str,
        *,
        target: bool = False,
    ) -> OnlyResearchTemplateInputBinding:
        source = item.source
        if isinstance(source, str):
            field = source.removeprefix("bar.")
            if field not in _DATASET_TYPES:
                self._fail(
                    OnlyResearchDefinitionPhase.CALCULATION, "RESEARCH_DEFINITION_DATASET_FIELD_UNKNOWN", path, source
                )
            return OnlyResearchTemplateInputBinding(
                item.input_name, OnlyResearchTemplateReference(None, item.input_name, f"bar.{field}")
            )
        if target:
            self._fail(
                OnlyResearchDefinitionPhase.TARGET,
                "RESEARCH_DEFINITION_TARGET_DEPENDENCY_INVALID",
                path,
                "Target V1 may consume only Dataset sources",
            )
        if source not in variables:
            self._fail(
                OnlyResearchDefinitionPhase.CALCULATION,
                "RESEARCH_DEFINITION_VARIABLE_UNPUBLISHED",
                path,
                f"{source.instance_key}.{source.output_name}",
            )
        return OnlyResearchTemplateInputBinding(
            item.input_name, OnlyResearchTemplateReference(source.instance_key, source.output_name)
        )

    @staticmethod
    def _dimensions(
        instances: tuple[OnlyResearchCalculationInstance, ...],
    ) -> tuple[OnlyResearchSweepParameterDimension, ...]:
        return tuple(
            OnlyResearchSweepParameterDimension(
                OnlyResearchSweepParameterTarget(instance.instance_key, name), binding.values
            )
            for instance in instances
            for name, binding in instance.parameters.items()
            if isinstance(binding, OnlyResearchSweepParameter)
        )

    def _statistics(
        self,
        definition: OnlyResearchDefinition,
        variables: Mapping[OnlyResearchVariableRef, OnlyOutputDefinition],
        target_variables: Mapping[OnlyResearchVariableRef, OnlyOutputDefinition],
    ) -> tuple[OnlyResearchStatisticsSpec, ...]:
        result: list[OnlyResearchStatisticsSpec] = []
        for index, request in enumerate(definition.statistics):
            output = variables.get(request.variable)
            if output is None:
                self._fail(
                    OnlyResearchDefinitionPhase.STATISTICS,
                    "RESEARCH_DEFINITION_STATISTICS_VARIABLE_UNPUBLISHED",
                    f"statistics[{index}].variable",
                    f"{request.variable.instance_key}.{request.variable.output_name}",
                )
            instance = next(
                item for item in definition.calculations if item.instance_key == request.variable.instance_key
            )
            if instance.type_reference.kind is not OnlyCalculationKind.FACTOR or output.semantic_type not in {
                FACTOR_VALUE_SEMANTIC_TYPE,
                FACTOR_SCORE_SEMANTIC_TYPE,
            }:
                self._fail(
                    OnlyResearchDefinitionPhase.STATISTICS,
                    "RESEARCH_DEFINITION_STATISTICS_INCOMPATIBLE",
                    f"statistics[{index}]",
                    "current Statistics capability requires Factor Value/Score",
                )
            target = next(
                (item for item in definition.targets if item.instance_key == request.target_instance_key), None
            )
            if target is None:
                self._fail(
                    OnlyResearchDefinitionPhase.STATISTICS,
                    "RESEARCH_DEFINITION_STATISTICS_TARGET_UNKNOWN",
                    f"statistics[{index}].target_instance_key",
                    request.target_instance_key,
                )
            output_name = target.published_outputs[0]
            if OnlyResearchVariableRef(target.instance_key, output_name) not in target_variables:
                self._fail(
                    OnlyResearchDefinitionPhase.STATISTICS,
                    "RESEARCH_DEFINITION_STATISTICS_TARGET_UNKNOWN",
                    f"statistics[{index}]",
                    output_name,
                )
            result.append(
                OnlyResearchStatisticsSpec(
                    OnlyResearchSeriesSelector("decision", request.variable.instance_key, request.variable.output_name),
                    OnlyResearchSeriesSelector(f"target.{target.instance_key}", target.instance_key, output_name),
                    request.definition,
                )
            )
        return tuple(result)

    @staticmethod
    def _fail(
        phase: OnlyResearchDefinitionPhase, code: str, path: str, detail: str, cause: Exception | None = None
    ) -> NoReturn:
        error = OnlyResearchDefinitionError(phase, code, path, detail)
        if cause is None:
            raise error
        raise error from cause


class _ExpressionLowerer:
    def __init__(
        self,
        variables: Mapping[OnlyResearchVariableRef, OnlyOutputDefinition],
        nodes: dict[str, OnlyResearchGraphTemplateNode],
    ) -> None:
        self.variables = variables
        self.nodes = nodes

    def lower_terminal(self, role: str, expression: OnlyResearchBooleanExpression) -> None:
        canonical = only_canonicalize_research_expression(expression)
        root = self._lower(canonical)
        node_id = f"{role}_terminal"
        self.nodes[node_id] = OnlyResearchGraphTemplateNode(
            node_id,
            only_research_predicate_type_reference(f"terminal.{role}"),
            {},
            (OnlyResearchTemplateInputBinding("value", OnlyResearchTemplateReference(root, "value")),),
        )

    def _lower(self, expression: OnlyResearchBooleanExpression) -> str:
        node_id = f"predicate_{only_research_expression_fingerprint(expression)}"
        if node_id in self.nodes:
            return node_id
        if isinstance(expression, OnlyResearchComparison):
            node = self._comparison(node_id, expression)
        elif isinstance(expression, OnlyResearchNot):
            child = self._lower(expression.operand)
            node = OnlyResearchGraphTemplateNode(
                node_id,
                only_research_predicate_type_reference("boolean.not"),
                {},
                (OnlyResearchTemplateInputBinding("value", OnlyResearchTemplateReference(child, "value")),),
            )
        else:
            children = [self._lower(item) for item in expression.operands]
            current = children[0]
            name = "and" if isinstance(expression, OnlyResearchAnd) else "or"
            for ordinal, child in enumerate(children[1:], start=1):
                intermediate = node_id if ordinal == len(children) - 1 else f"{node_id}_{ordinal}"
                self.nodes[intermediate] = OnlyResearchGraphTemplateNode(
                    intermediate,
                    only_research_predicate_type_reference(f"boolean.{name}"),
                    {},
                    (
                        OnlyResearchTemplateInputBinding("left", OnlyResearchTemplateReference(current, "value")),
                        OnlyResearchTemplateInputBinding("right", OnlyResearchTemplateReference(child, "value")),
                    ),
                )
                current = intermediate
            return current
        self.nodes[node_id] = node
        return node_id

    def _comparison(self, node_id: str, expression: OnlyResearchComparison) -> OnlyResearchGraphTemplateNode:
        left_type = self._operand_type(expression.left)
        right_type = self._operand_type(expression.right)
        if left_type is not right_type:
            raise OnlyResearchDefinitionError(
                OnlyResearchDefinitionPhase.EXPRESSION,
                "RESEARCH_DEFINITION_COMPARISON_TYPE_INVALID",
                "expression",
                f"{left_type.value} cannot compare with {right_type.value}",
            )
        if left_type in {
            OnlyCalculationDataType.STRING,
            OnlyCalculationDataType.BOOLEAN,
        } and expression.operator.value not in {"==", "!="}:
            raise OnlyResearchDefinitionError(
                OnlyResearchDefinitionPhase.EXPRESSION,
                "RESEARCH_DEFINITION_COMPARISON_TYPE_INVALID",
                "expression",
                f"{left_type.value} supports only == and !=",
            )
        left_literal, right_literal = (
            isinstance(expression.left, OnlyResearchTypedLiteral),
            isinstance(expression.right, OnlyResearchTypedLiteral),
        )
        if left_literal and right_literal:
            raise OnlyResearchDefinitionError(
                OnlyResearchDefinitionPhase.EXPRESSION,
                "RESEARCH_DEFINITION_COMPARISON_INVALID",
                "expression",
                "literal-to-literal comparison is not an observation expression",
            )
        operator = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}[expression.operator.value]
        if not left_literal and not right_literal:
            return OnlyResearchGraphTemplateNode(
                node_id,
                only_research_predicate_type_reference(f"compare.{operator}.{left_type.value.lower()}.refs"),
                {},
                (self._operand_binding("left", expression.left), self._operand_binding("right", expression.right)),
            )
        if isinstance(expression.left, OnlyResearchTypedLiteral):
            literal = expression.left
            reference = expression.right
        elif isinstance(expression.right, OnlyResearchTypedLiteral):
            literal = expression.right
            reference = expression.left
        else:  # guarded above
            raise TypeError("comparison literal is missing")
        return OnlyResearchGraphTemplateNode(
            node_id,
            only_research_predicate_type_reference(f"compare.{operator}.{left_type.value.lower()}.literal"),
            {"literal": literal.value, "literal_left": left_literal},
            (self._operand_binding("left", reference),),
        )

    def _operand_type(self, operand: OnlyResearchOperand) -> OnlyCalculationDataType:
        if isinstance(operand, OnlyResearchTypedLiteral):
            return operand.data_type
        if isinstance(operand, OnlyResearchDatasetFieldRef):
            try:
                return _DATASET_TYPES[operand.field_name]
            except KeyError as exc:
                raise OnlyResearchDefinitionError(
                    OnlyResearchDefinitionPhase.EXPRESSION,
                    "RESEARCH_DEFINITION_DATASET_FIELD_UNKNOWN",
                    "expression",
                    operand.field_name,
                ) from exc
        output = self.variables.get(operand)
        if output is None:
            raise OnlyResearchDefinitionError(
                OnlyResearchDefinitionPhase.EXPRESSION,
                "RESEARCH_DEFINITION_VARIABLE_UNPUBLISHED",
                "expression",
                f"{operand.instance_key}.{operand.output_name}",
            )
        return output.data_type

    def _operand_binding(self, name: str, operand: OnlyResearchOperand) -> OnlyResearchTemplateInputBinding:
        if isinstance(operand, OnlyResearchDatasetFieldRef):
            return OnlyResearchTemplateInputBinding(
                name, OnlyResearchTemplateReference(None, name, f"bar.{operand.field_name}")
            )
        if isinstance(operand, OnlyResearchVariableRef):
            return OnlyResearchTemplateInputBinding(
                name, OnlyResearchTemplateReference(operand.instance_key, operand.output_name)
            )
        raise TypeError("literal cannot be lowered as an input reference")


__all__ = [
    name for name in globals() if name.startswith(("OnlyResearchDefinition", "OnlyResearchPublished", "DEFAULT_"))
]
