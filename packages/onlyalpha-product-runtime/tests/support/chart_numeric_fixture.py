"""Technical zero-input vectors executed by the exact isolated algorithm SDK."""
import json
from onlyalpha_plugin_indicators.chart_factory import ChartFactory

factory = ChartFactory()
cases = []
for row in sorted(factory.catalog(), key=lambda value: value["descriptor"]["type_id"]):
    descriptor, support = row["descriptor"], row["support"]
    if not support["default_variant"] or descriptor["type_id"].rsplit(".", 1)[-1] not in {"rsi", "atr", "stochastic", "roc", "vwap"}:
        continue
    parameters = support["default_parameters"]
    definition = factory.resolve(descriptor["type_id"], descriptor["semantic_version"], parameters)
    inputs = {port.name: [index * 900_000_000_000 for index in range(30)] if port.data_type.value == "INTEGER" else ["0"] * 30 for port in definition.inputs}
    result = factory.execute(descriptor["type_id"], descriptor["semantic_version"], parameters, inputs, row["implementation_fingerprint"])
    output = support["series"][0]["output_name"]
    nullable = next(port.nullable for port in definition.outputs if port.name == output)
    for index in (0, 29):
        cases.append({"type_id": descriptor["type_id"], "semantic_version": descriptor["semantic_version"], "output_name": output,
            "nullable": nullable, "value": result["outputs"][output]["values"][index], "readiness": result["outputs"][output]["states"][index], "reason": result["outputs"][output]["reasons"][index]})
assert len(cases) == 10
print(json.dumps({"schema_version": 1, "source_kind": "INSTALLED_CALCULATION_BACKEND", "cases": cases}, sort_keys=True))
