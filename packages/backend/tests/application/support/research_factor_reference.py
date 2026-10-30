"""Independent SDK contract vector; never a Product admission or executable grant.

Regenerate from repo root:
python packages/backend/tests/application/support/research_factor_reference.py --output test-results/research-factor-reference.json
Copy that output to tests/application/fixtures/research_factor.json in this package after the run.
"""

import argparse
import json
from pathlib import Path

from onlyalpha_backend_algorithms.sdk.private_factor_execution import (
    OnlyPrivateFactorDefinitionResolverV1,
    only_private_factor_type_definition,
)
from onlyalpha_plugin_operators.registration import DELAY, ROLLING_MEAN, resolve_operator

from onlyalpha.algorithm.private_factor import ONLY_PRIVATE_FACTOR_API_V1
from onlyalpha.calculation.definition import OnlyCalculationReference
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition
from onlyalpha.quant_assets.private import OnlyPrivateFactorDraft, OnlyPrivateFactorRevision

FIXTURE = Path(__file__).parent.parent / "fixtures/research_factor.json"


def reference() -> dict[str, object]:
    expression = {
        "op": "mul",
        "left": {
            "op": "sub",
            "left": {"op": "div", "left": {"input": "close"}, "right": {"input": "close", "lag": 20}},
            "right": {"integer": 1},
        },
        "right": {
            "op": "div",
            "left": {"input": "volume"},
            "right": {"input": "volume", "mean": 20},
        },
    }
    source = (
        "def calculate(api, inputs, parameters):\n"
        "    return {'value': api.mul(api.sub(api.div(inputs['close'], inputs['close_lag_20']), parameters['literal_1']), "
        "api.div(inputs['volume'], inputs['volume_mean_20']))}\n"
    )
    hypothesis = "放量时历史动量可能持续"
    draft = OnlyPrivateFactorDraft.from_dict(
        {
            "schema_version": 1,
            "factor_id": "private.factor.volume_momentum",
            "base_revision_fingerprint": None,
            "semantic_version": "1",
            "source_text": source,
            "factor_api_version": 1,
            "factor_api_contract_fingerprint": ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
            "input_contract": {
                name: {"type": "DECIMAL", "missing": True}
                for name in ("close", "close_lag_20", "volume", "volume_mean_20")
            },
            "parameter_contract": {"literal_1": {"type": "DECIMAL", "required": False, "default": "1"}},
            "output_contract": {"value": {"type": "DECIMAL", "missing": True}},
            "description": hypothesis,
            "economic_rationale": hypothesis,
            "category": "chat",
            "tags": [],
        }
    )
    revision = OnlyPrivateFactorRevision.from_draft(draft)
    delay = resolve_operator(DELAY, {"period": 20}, value=OnlyCalculationReference(None, "value", "close"))
    mean = resolve_operator(ROLLING_MEAN, {"period": 20}, value=OnlyCalculationReference(None, "value", "volume"))
    root = OnlyPrivateFactorDefinitionResolverV1(only_private_factor_type_definition(revision)).resolve(
        {},
        {
            "close": OnlyCalculationReference(None, "value", "close"),
            "volume": OnlyCalculationReference(None, "value", "volume"),
            "close_lag_20": OnlyCalculationReference(delay.fingerprint, "value"),
            "volume_mean_20": OnlyCalculationReference(mean.fingerprint, "value"),
        },
    )
    graph = OnlyCalculationGraphDefinition(tuple(OnlyCalculationNodeDefinition(d) for d in (delay, mean, root)))
    return {
        "candidate": {
            "name": "放量动量",
            "purpose": "观察放量与动量的关系",
            "hypothesis": hypothesis,
            "expression": expression,
        },
        "draft": draft.to_dict(),
        "revision": revision.to_dict(),
        "graph": graph.to_dict(),
        "graph_fingerprint": graph.fingerprint,
        "root_fingerprint": root.fingerprint,
        "required_history_bars": 20,
    }


def test_reference_matches_current_algorithm_contract() -> None:
    assert json.loads(FIXTURE.read_text()) == reference()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reference(), ensure_ascii=False, sort_keys=True, indent=2) + "\n")
