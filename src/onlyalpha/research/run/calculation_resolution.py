"""Strict calculation-publication compilation proof, not Run admission or execution.

The hosted compiler owns normalized Graph derivation. This DTO checks structural
closure and exact identities; the execution port, not a receiver Registry, proves
that the manifest came from the requested immutable Runtime Generation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyFactorKind,
    only_calculation_execution_shape,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.calculation.implementation import (
    OnlyCalculationImplementationManifest,
)
from onlyalpha.research.calculation.execution import OnlyResearchCalculationImplementationBinding
from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationContract
from onlyalpha.research.dataset.strict import require_exact_fields, require_int, require_mapping, require_sha256
from onlyalpha.research.job.plan import OnlyResearchJobPlan
from onlyalpha.research.result.plan import OnlyResearchResultPlan
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.research.workload import OnlyResearchWorkloadPlan

_CONTEXT = "Research calculation Runtime resolution"


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationRuntimeResolutionV1:
    runtime_generation_fingerprint: str
    specification: OnlyResearchSpecification
    specification_fingerprint: str
    job_plan: OnlyResearchJobPlan
    result_plan: OnlyResearchResultPlan
    calculation_id: str
    node_fingerprints: Mapping[str, str]
    research_implementation_bindings: tuple[OnlyResearchCalculationImplementationBinding, ...]
    implementation_manifest: OnlyCalculationImplementationManifest

    def __post_init__(self) -> None:
        require_sha256({"generation": self.runtime_generation_fingerprint}, "generation", _CONTEXT)
        if type(self.specification) is not OnlyResearchSpecification or self.specification.schema_version != 3:
            raise ValueError("calculation resolution requires Specification V3")
        if self.specification_fingerprint != self.specification.specification_fingerprint:
            raise ValueError("calculation resolution Specification identity differs")
        if type(self.job_plan) is not OnlyResearchJobPlan or self.job_plan.schema_version != 2:
            raise ValueError("calculation resolution requires Job Plan V2")
        if type(self.result_plan) is not OnlyResearchResultPlan or self.result_plan.schema_version != 4:
            raise ValueError("calculation resolution requires Result Plan V4")
        OnlyResearchWorkloadPlan((self.job_plan,), (), (), self.result_plan)
        spec = self.specification
        graph = self.job_plan.calculation_graph
        if len(graph.nodes) != 1 or spec.dataset_snapshot_fingerprint != self.job_plan.dataset_snapshot_fingerprint:
            raise ValueError("calculation resolution Graph or Dataset differs")
        if only_calculation_execution_shape(graph.nodes[0].definition) is not OnlyFactorKind.TIME_SERIES:
            raise ValueError("calculation resolution requires TIME_SERIES")
        if (
            spec.publication != self.result_plan.publication
            or self.calculation_id != spec.calculations[0].calculation_id
        ):
            raise ValueError("calculation resolution selection differs")
        template = spec.calculations[0].graph_template
        if len(template.nodes) != 1:
            raise ValueError("calculation resolution template node coverage differs")
        template_node, node = template.nodes[0], graph.nodes[0]
        mapping = dict(require_mapping(self.node_fingerprints, _CONTEXT))
        if mapping != {template_node.template_node_id: node.fingerprint}:
            raise ValueError("calculation resolution complete node mapping differs")
        object.__setattr__(self, "node_fingerprints", MappingProxyType(mapping))
        reference = template_node.type_reference
        if (reference.kind, reference.type_id, reference.semantic_version) != (
            node.definition.kind,
            node.definition.type_id,
            node.definition.semantic_version,
        ):
            raise ValueError("calculation resolution type reference differs")
        source_bindings = {item.input_name: item.reference for item in template_node.input_bindings}
        # Defaults and parameter normalization belong to the exact hosted compiler.
        # Explicit source references remain structural relations; omitted bindings
        # may be populated by the registered Definition resolver.
        if set(source_bindings) - set(node.definition.input_bindings):
            raise ValueError("calculation resolution explicit input coverage differs")
        for name, source in source_bindings.items():
            actual = node.definition.input_bindings[name]
            if source.template_node_id is not None or (actual.node_fingerprint, actual.output_name, actual.source) != (
                None,
                source.output_name,
                source.source,
            ):
                raise ValueError("calculation resolution input source differs")
        selector = spec.published_series[0]
        if selector.template_node_id not in mapping or not any(
            output.name == selector.output_name for output in node.definition.outputs
        ):
            raise ValueError("calculation resolution selector output absent")
        members = self.result_plan.published_series
        if len(members) != 1 or (members[0].node_fingerprint, members[0].output_name) != (
            node.fingerprint,
            selector.output_name,
        ):
            raise ValueError("calculation resolution published selector differs")
        if type(self.implementation_manifest) is not OnlyCalculationImplementationManifest:
            raise ValueError("calculation resolution implementation manifest missing")
        manifest = OnlyCalculationImplementationManifest.from_dict(self.implementation_manifest.to_dict())
        if (
            manifest.backend_kind is not OnlyCalculationBackendKind.RESEARCH
            or manifest.calculation_type_reference != reference
        ):
            raise ValueError("calculation resolution implementation family differs")
        expected = (
            OnlyResearchCalculationImplementationBinding(node.fingerprint, manifest.implementation_fingerprint),
        )
        if (
            type(self.research_implementation_bindings) is not tuple
            or self.research_implementation_bindings != expected
        ):
            raise ValueError("calculation resolution implementation binding differs")

    @property
    def calculation_graph(self) -> OnlyCalculationGraphDefinition:
        return self.job_plan.calculation_graph

    @property
    def graph_fingerprint(self) -> str:
        return self.calculation_graph.fingerprint

    @property
    def calculation_fingerprint(self) -> str:
        return self.job_plan.calculation_fingerprint

    def to_dict(self) -> dict[str, object]:
        assert self.job_plan.publication is not None
        return {
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "specification": self.specification.to_dict(),
            "specification_fingerprint": self.specification_fingerprint,
            "job_plan": {
                "schema_version": self.job_plan.schema_version,
                "dataset_snapshot_fingerprint": self.job_plan.dataset_snapshot_fingerprint,
                "calculation_graph": self.calculation_graph.to_dict(),
                "publication": self.job_plan.publication.to_dict(),
            },
            "result_plan": self.result_plan.to_dict(),
            "calculation_id": self.calculation_id,
            "node_fingerprints": dict(self.node_fingerprints),
            "research_implementation_bindings": [
                {
                    "node_fingerprint": item.node_fingerprint,
                    "research_implementation_fingerprint": item.research_implementation_fingerprint,
                }
                for item in self.research_implementation_bindings
            ],
            "implementation_manifest": self.implementation_manifest.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCalculationRuntimeResolutionV1:
        payload = require_mapping(payload, _CONTEXT)
        require_exact_fields(
            payload,
            {
                "runtime_generation_fingerprint",
                "specification",
                "specification_fingerprint",
                "job_plan",
                "result_plan",
                "calculation_id",
                "node_fingerprints",
                "research_implementation_bindings",
                "implementation_manifest",
            },
            _CONTEXT,
        )
        job = require_mapping(payload["job_plan"], _CONTEXT)
        require_exact_fields(
            job, {"schema_version", "dataset_snapshot_fingerprint", "calculation_graph", "publication"}, _CONTEXT
        )
        bindings = []
        raw_bindings = payload["research_implementation_bindings"]
        if type(raw_bindings) is not list:
            raise ValueError("calculation resolution bindings must be an array")
        for raw in raw_bindings:
            raw = require_mapping(raw, _CONTEXT)
            require_exact_fields(raw, {"node_fingerprint", "research_implementation_fingerprint"}, _CONTEXT)
            bindings.append(
                OnlyResearchCalculationImplementationBinding(
                    require_sha256(raw, "node_fingerprint", _CONTEXT),
                    require_sha256(raw, "research_implementation_fingerprint", _CONTEXT),
                )
            )
        return cls(
            require_sha256(payload, "runtime_generation_fingerprint", _CONTEXT),
            OnlyResearchSpecification.from_dict(require_mapping(payload["specification"], _CONTEXT)),
            require_sha256(payload, "specification_fingerprint", _CONTEXT),
            OnlyResearchJobPlan(
                require_sha256(job, "dataset_snapshot_fingerprint", _CONTEXT),
                OnlyCalculationGraphDefinition.from_dict(require_mapping(job["calculation_graph"], _CONTEXT)),
                require_int(job, "schema_version", _CONTEXT),
                OnlyResearchCalculationPublicationContract.from_dict(require_mapping(job["publication"], _CONTEXT)),
            ),
            OnlyResearchResultPlan.from_dict(require_mapping(payload["result_plan"], _CONTEXT)),
            _string(payload["calculation_id"]),
            cast(Mapping[str, str], require_mapping(payload["node_fingerprints"], _CONTEXT)),
            tuple(bindings),
            OnlyCalculationImplementationManifest.from_dict(
                require_mapping(payload["implementation_manifest"], _CONTEXT)
            ),
        )


def _string(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError("calculation resolution requires a nonempty string")
    return value
