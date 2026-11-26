"""Installed session admission refuses source-only Factor artifacts."""

import json
import subprocess
from pathlib import Path


def test_installed_trading_session_refuses_source_only_factor_admission(tmp_path: Path) -> None:
    from onlyalpha.calculation.definition import OnlyCalculationReference
    from onlyalpha_backend_algorithms.sdk import private_factor_execution as execution
    from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1

    from scripts.build_algorithm_sdk import ROOT, install

    installation = tmp_path / "installed"
    install(tmp_path / "wheels", installation)
    fixture = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    source = {key: fixture["revision"][key] for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__}
    record = OnlyPrivateFactorExecutableSourceRecordV1.from_dict(source)
    definition = execution.OnlyPrivateFactorDefinitionResolverV1(
        execution.only_private_factor_type_definition(record)
    ).resolve({}, {name: OnlyCalculationReference(None, "value", name) for name in record.input_contract})
    request = {"source": source, "nodes": {"factor": dict(definition.to_dict())}}
    code = r"""
import json, sys
from onlyalpha_backend_algorithms.chart_isolation import restrict
from onlyalpha_backend_algorithms.trading_session import TradingGraphSession

p = json.loads(sys.stdin.read())
assert restrict() == 'LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1'

for sources, nodes, expected in (
    ([p['source']], p['nodes'], 'PRIVATE_FACTOR_VALIDATION_EVIDENCE_MISMATCH'),
    ([p['source']], {'\n': p['nodes']['factor']}, 'TRADING_ALGORITHM_NODE_INVALID'),
    ([p['source']], {str(i): p['nodes']['factor'] for i in range(129)}, 'TRADING_ALGORITHM_BUDGET_EXCEEDED'),
):
    try:
        TradingGraphSession(sources, nodes)
    except ValueError as error:
        assert str(error) == expected
    else:
        raise AssertionError('source-only Trading session was admitted')
assert not any(name.startswith(('onlyalpha.application','onlyalpha.runtime','onlyalpha.strategy','onlyalpha.persistence','onlyalpha.execution','onlyalpha.account','onlyalpha.risk','onlyalpha.broker')) for name in sys.modules)
assert not any(name.startswith('onlyalpha_plugin_operators') for name in sys.modules)
print('source-only Factor admission refused')
"""
    result = subprocess.run(
        [str(installation / "bin/python"), "-B", "-I", "-c", code],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        env={},
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "source-only Factor admission refused"
