"""Source lowers once to bounded data; no supplied Python bytecode is executed."""

import ast
import unittest
from unittest.mock import patch

INPUTS = {"close": {"type": "DECIMAL"}}
PARAMS = {"period": {"type": "INTEGER", "default": 2, "required": False, "minimum": 1, "maximum": 100000}}
OUTPUTS = {"value": {"type": "DECIMAL"}}


def compile(source, parameters=PARAMS):
    from onlyalpha.algorithm.factor_program import compile_factor_source

    return compile_factor_source(
        source, 1, input_contract=INPUTS, parameter_contract=parameters, output_contract=OUTPUTS
    )


def _check_lowering_parses_once_and_emits_data_not_executable_python():
    source = 'def calculate(api, inputs, parameters):\n    a = api.rolling_mean(inputs["close"], parameters["period"])\n    return {"value": api.sub(inputs["close"], a)}\n'
    with patch.object(ast, "parse", wraps=ast.parse) as parse:
        result = compile(source)
        assert parse.call_count == 1
    assert result["numeric_policy"] == "DECIMAL28_HALF_EVEN_Q12_V1"
    assert result["nodes"] == [
        {"op": "input", "name": "close"},
        {"op": "rolling_mean", "args": [0], "period": {"parameter": "period"}},
        {"op": "input", "name": "close"},
        {"op": "sub", "args": [2, 1]},
        {"op": "to_decimal", "args": [3]},
    ]
    assert result["outputs"] == {"value": 4}
    assert "source" not in result


UNSAFE_BODIES = [
    "while True:\n        pass",
    'x = []\n    return {"value": x}',
    'inputs["close"] = 1\n    return {"value": inputs["close"]}',
    'return {"value": open("/tmp/factor-source-executed","w")}',
    'return {"value": api.unknown(inputs["close"])}',
    'return {"value": api.delay(inputs["close"], -1)}',
    'return {"value": inputs["future_close"]}',
    'return {"wrong_output": inputs["close"]}',
]


def _check_unsafe_or_ambiguous_sources_are_rejected_before_execution():
    for body in UNSAFE_BODIES:
        with unittest.TestCase().assertRaises(ValueError):
            compile("def calculate(api, inputs, parameters):\n    " + body + "\n")


def _check_parameter_schema_and_entrypoint_are_part_of_the_program():
    source = 'def calculate(api, inputs, parameters):\n    return {"value": api.add(inputs["close"], parameters["period"])}\n'
    first = compile(source)
    assert first["parameters"][0]["default"] == {"type": "INTEGER", "value": 2}
    assert compile(source, {"period": {**PARAMS["period"], "default": 3}}) != first
    with unittest.TestCase().assertRaises(ValueError):
        compile(source.replace("calculate(api, inputs, parameters)", "calculate(inputs)"))


class FactorProgramCompilerTests(unittest.TestCase):
    test_lowering_parses_once = staticmethod(_check_lowering_parses_once_and_emits_data_not_executable_python)
    test_unsafe_sources = staticmethod(_check_unsafe_or_ambiguous_sources_are_rejected_before_execution)
    test_parameter_identity = staticmethod(_check_parameter_schema_and_entrypoint_are_part_of_the_program)


class InstalledFactorBuildTests(unittest.TestCase):
    def test_public_numeric_contract_is_native_precision_28(self):
        from onlyalpha.algorithm.private_factor import ONLY_PRIVATE_FACTOR_NUMERIC_V1

        self.assertEqual(ONLY_PRIVATE_FACTOR_NUMERIC_V1.precision, 28)

    def test_build_compiler_is_really_confined_and_returns_typed_data(self):
        import json
        import subprocess
        import sys

        payload = {
            "schema_version": 1,
            "contract": "ONLYALPHA_FACTOR_PROGRAM_COMPILE_V1",
            "source": {
                "source_text": 'def calculate(api, inputs, parameters):\n    return {"value": api.sub(inputs["close"], 1)}\n',
                "factor_api_version": 1,
                "input_contract": INPUTS,
                "parameter_contract": {},
                "output_contract": OUTPUTS,
            },
        }
        import hashlib

        from onlyalpha.algorithm.private_factor import ONLY_PRIVATE_FACTOR_API_V1

        payload["source"]["source_sha256"] = hashlib.sha256(payload["source"]["source_text"].encode()).hexdigest()
        payload["source"]["factor_api_contract_fingerprint"] = ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint
        script = 'import sys,json,os,ast\nfrom unittest.mock import patch\nfrom onlyalpha_backend_algorithms.factor_build import compile_request\nwith patch.object(ast,"parse",wraps=ast.parse) as observed:\n    v=compile_request(json.load(sys.stdin))\n    assert observed.call_count==1\ntry:\n    os.open("/tmp/onlyalpha-factor-build-forbidden",os.O_WRONLY|os.O_CREAT,0o600)\nexcept PermissionError:\n    v["actual_file_write_denied"]=True\nelse:\n    raise AssertionError("build confinement allowed write")\nprint(json.dumps(v,sort_keys=True))'
        r = subprocess.run(
            [sys.executable, "-B", "-c", script], input=json.dumps(payload), text=True, capture_output=True, timeout=10
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        v = json.loads(r.stdout)
        self.assertEqual(v["isolation"], "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1")
        self.assertTrue(v["actual_file_write_denied"])
        self.assertEqual(v["parse_count"], 1)
        self.assertEqual(v["program"]["outputs"], {"value": 3})


class RetiredSourceExecutionTests(unittest.TestCase):
    def test_job_source_validation_cannot_parse_or_grant_readiness(self):
        import json
        from pathlib import Path

        from onlyalpha_backend_algorithms.sdk.private_factor_execution import only_validate_private_factor_revision
        from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1

        raw = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())["revision"]
        source = OnlyPrivateFactorExecutableSourceRecordV1.from_dict(
            {k: raw[k] for k in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__}
        )
        with patch.object(ast, "parse", side_effect=AssertionError("job loading attempted AST parsing")):
            evidence = only_validate_private_factor_revision(source)
        self.assertEqual(evidence.validation_disposition.value, "FAIL")
        self.assertIn("PRIVATE_FACTOR_NATIVE_BUILD_REQUIRED", evidence.errors)


class ContractValidationTests(unittest.TestCase):
    def test_required_parameter_inference(self):
        result = compile(
            'def calculate(api, inputs, parameters):\n    return {"value": parameters["period"]}\n',
            {"period": {"type": "INTEGER"}},
        )
        self.assertTrue(result["parameters"][0]["required"])
        self.assertIsNone(result["parameters"][0]["default"])

    def test_malformed_contracts_are_rejected(self):
        from onlyalpha.algorithm.factor_program import compile_factor_source

        source = 'def calculate(api, inputs, parameters):\n    return {"value": inputs["close"]}\n'
        cases = [
            ({"close": {"type": "DECIMAL", "nullable": "yes"}}, PARAMS, OUTPUTS),
            (INPUTS, {"period": {**PARAMS["period"], "enum_values": {"2": True}}}, OUTPUTS),
            (INPUTS, PARAMS, {"value": {"type": "DECIMAL", "missing": 1}}),
        ]
        for inputs, parameters, outputs in cases:
            with self.assertRaises(ValueError):
                compile_factor_source(
                    source, 1, input_contract=inputs, parameter_contract=parameters, output_contract=outputs
                )


class IntegerLiteralTests(unittest.TestCase):
    def test_integer_literal_preserves_the_declared_type(self):
        from onlyalpha.algorithm.factor_program import compile_factor_source

        source = 'def calculate(api, inputs, parameters):\n    return {"value": 7}\n'
        result = compile_factor_source(
            source, 1, input_contract=INPUTS, parameter_contract={}, output_contract={"value": {"type": "INTEGER"}}
        )
        self.assertEqual(result["nodes"], [{"op": "literal", "type": "INTEGER", "value": "7"}])
        promoted = compile(source, {})
        self.assertEqual(promoted["nodes"][-1], {"op": "to_decimal", "args": [0]})
