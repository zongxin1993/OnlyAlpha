from __future__ import annotations

from onlyalpha_agent_orchestrator.semantic_bundle import load_production_semantic_bundle_v1

from onlyalpha.research.agent import (
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentPromptTemplatePayloadV1,
    OnlyAgentStructuredOutputSchemaPayloadV1,
    validate_agent_strict_schema,
)


def test_production_bundle_has_exact_four_roles_and_strict_packaged_schemas() -> None:
    first = load_production_semantic_bundle_v1()
    second = load_production_semantic_bundle_v1()
    assert first.resources == second.resources
    assert len(first.role_policy_fingerprints) == 4
    prompts = tuple(
        item.canonical_payload
        for item in first.resources
        if item.resource_kind is OnlyAgentOrchestrationResourceKind.PROMPT_TEMPLATE
    )
    assert len(prompts) == 4
    assert all(
        isinstance(prompt, OnlyAgentPromptTemplatePayloadV1) and "{{ context_json }}" in prompt.template_content
        for prompt in prompts
    )
    schemas = tuple(
        item.canonical_payload
        for item in first.resources
        if item.resource_kind is OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA
    )
    assert len(schemas) == 4
    for schema in schemas:
        assert isinstance(schema, OnlyAgentStructuredOutputSchemaPayloadV1)
        validate_agent_strict_schema(schema.exact_schema, root_type="object")


def test_invocation_bindings_are_explicit_for_every_role_and_non_secret() -> None:
    bundle = load_production_semantic_bundle_v1()
    for role in ("RESEARCH_PLANNER", "SEARCH_ROUTER", "FACTOR_DESIGNER", "EVIDENCE_ANALYST"):
        binding = bundle.invocation_bindings.load_model_invocation_binding_verified(role)
        assert binding.logical_role == role
        assert binding.provider_id == "openai-compatible"
        assert not {"token", "secret", "base_url", "timeout"}.intersection(binding.to_dict())
