"""Registered Chart capabilities remain exact, complete and non-publishing."""

from decimal import Decimal

import pyarrow as pa

from onlyalpha.application.chart_study_numeric import OnlyChartStudyInvocation
from onlyalpha.quant_assets.catalog import only_discover_quant_asset_providers


def test_all_fourteen_families_have_one_explicit_default_and_backend_quality():
    catalog = only_discover_quant_asset_providers()
    invocation = OnlyChartStudyInvocation(catalog.calculation_registry(), catalog)
    admissions = invocation.admissions
    defaults = [item for item in admissions if item.support.default_variant]
    assert len(defaults) == 14
    assert len({item.registration.type_definition.type_id for item in defaults}) == 14
    for admission in admissions:
        descriptor = admission.registration.type_definition
        definition = admission.registration.definition_resolver.resolve(admission.support.default_parameters, {})
        inputs = {
            name: pa.array([index * 900_000_000_000 for index in range(70)], type=pa.int64())
            if binding.source == "bar.start_ns"
            else pa.array([str(100 + index % 13) for index in range(70)], type=pa.string()).cast(pa.decimal128(38, 18))
            for name, binding in definition.input_bindings.items()
        }
        parameters = {
            field.name: Decimal(admission.support.default_parameters[field.name])
            if field.parameter_type.value == "DECIMAL"
            else admission.support.default_parameters[field.name]
            for field in descriptor.parameters.fields
        }
        result = invocation._invoke_numeric(
            parameters,
            inputs,
            type_id=descriptor.type_id,
            semantic_version=descriptor.semantic_version,
            capability_fingerprint=admission.fingerprint,
        )
        assert set(result.outputs) == set(result.readiness) == {item.name for item in definition.outputs}
        assert all(len(column) == 70 for column in result.outputs.values())
        assert all(len(item.states) == 70 for item in result.readiness.values())
